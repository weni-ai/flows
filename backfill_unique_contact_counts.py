"""
Backfill script for UniqueContactCount model.

Usage:
    # Inside the Django project directory, with virtualenv activated:
    python backfill_unique_contact_counts.py

    # Dry run (only shows what would be done):
    python backfill_unique_contact_counts.py --dry-run

    # Custom parameters:
    python backfill_unique_contact_counts.py --start-date 2026-01-15 --end-date 2026-01-20 --sleep 1.0

    # Test with a single org first:
    python backfill_unique_contact_counts.py --org-id 11251 --dry-run
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import django
import pytz

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "temba.settings")
django.setup()

from temba.msgs.models import Msg  # noqa: E402
from temba.orgs.models import Org, UniqueContactCount  # noqa: E402


def backfill(start_date, end_date, sleep_between_orgs, sleep_between_days, specific_org_id, dry_run):
    # Get orgs to process
    if specific_org_id:
        orgs = list(Org.objects.filter(id=specific_org_id, is_active=True).only("id", "name"))
        if not orgs:
            print(f"ERROR: Active org with id={specific_org_id} not found")
            return
    else:
        orgs = list(Org.objects.filter(is_active=True).only("id", "name").order_by("id"))

    total_days = (end_date - start_date).days + 1
    total_operations = total_days * len(orgs)

    print(
        f"\n{'[DRY RUN] ' if dry_run else ''}"
        f"Backfilling UniqueContactCount\n"
        f"  Date range: {start_date} to {end_date} ({total_days} days)\n"
        f"  Orgs: {len(orgs)}\n"
        f"  Total queries: {total_operations}\n"
        f"  Sleep between orgs: {sleep_between_orgs}s\n"
        f"  Sleep between days: {sleep_between_days}s\n"
    )

    processed = 0
    created = 0
    updated = 0
    errors = 0
    start_time = time.time()

    current_day = start_date
    while current_day <= end_date:
        day_start = datetime.combine(current_day, datetime.min.time()).replace(tzinfo=pytz.UTC)
        day_end = datetime.combine(current_day + timedelta(days=1), datetime.min.time()).replace(tzinfo=pytz.UTC)

        print(f"\n--- Processing {current_day} ---")

        for org in orgs:
            try:
                # Count distinct contacts that sent incoming messages on this day
                # Uses index: msgs_msg_org_id_created_on_id_idx on (org_id, created_on, id)
                count = (
                    Msg.objects.filter(
                        org_id=org.id,
                        direction=Msg.DIRECTION_IN,
                        created_on__gte=day_start,
                        created_on__lt=day_end,
                    )
                    .values("contact_id")
                    .distinct()
                    .count()
                )

                processed += 1

                if dry_run:
                    if count > 0:
                        print(f"  [DRY RUN] org={org.id} ({org.name}): {count} unique contacts")
                else:
                    _, was_created = UniqueContactCount.objects.update_or_create(
                        org=org,
                        day=current_day,
                        defaults={"count": count},
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1

                    if count > 0:
                        print(
                            f"  org={org.id} ({org.name}): {count} unique contacts "
                            f"({'created' if was_created else 'updated'})"
                        )

            except Exception as e:
                errors += 1
                print(f"  ERROR org={org.id} ({org.name}): {e}")

            # Sleep between org queries
            time.sleep(sleep_between_orgs)

            # Progress report every 1000 operations
            if processed % 1000 == 0 and processed > 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (total_operations - processed) / rate if rate > 0 else 0
                print(
                    f"  Progress: {processed}/{total_operations} "
                    f"({processed * 100 // total_operations}%) "
                    f"- {rate:.1f} ops/s "
                    f"- ETA: {remaining / 60:.1f} min"
                )

        # Sleep between days
        print(f"  Day {current_day} done. Sleeping {sleep_between_days}s...")
        time.sleep(sleep_between_days)

        current_day += timedelta(days=1)

    # Final summary
    elapsed = time.time() - start_time
    print(
        f"\n{'[DRY RUN] ' if dry_run else ''}"
        f"Backfill completed!\n"
        f"  Processed: {processed}\n"
        f"  Created: {created}\n"
        f"  Updated: {updated}\n"
        f"  Errors: {errors}\n"
        f"  Time: {elapsed / 60:.1f} minutes\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill UniqueContactCount from msgs_msg")
    parser.add_argument("--start-date", type=str, default="2026-01-01", help="Start date YYYY-MM-DD (default: 2026-01-01)")
    parser.add_argument("--end-date", type=str, default="2026-02-04", help="End date YYYY-MM-DD (default: 2026-02-04)")
    parser.add_argument("--sleep", type=float, default=0.1, help="Seconds between org queries (default: 0.1)")
    parser.add_argument("--batch-sleep", type=float, default=0.0, help="Seconds between days (default: 0.0)")
    parser.add_argument("--org-id", type=int, default=None, help="Process only this org ID")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()

    if start_date > end_date:
        print("ERROR: start-date must be before or equal to end-date")
        sys.exit(1)

    backfill(start_date, end_date, args.sleep, args.batch_sleep, args.org_id, args.dry_run)
