import time
from datetime import date, datetime, timedelta

import pytz

from django.core.management.base import BaseCommand
from django.db.models import Count

from temba.msgs.models import Msg
from temba.orgs.models import Org, UniqueContactCount


class Command(BaseCommand):  # pragma: no cover
    help = (
        "Backfills UniqueContactCount from msgs_msg for a date range. "
        "Processes one org/day at a time with configurable sleep to avoid overloading the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            default="2026-01-01",
            help="Start date in YYYY-MM-DD format (inclusive). Default: 2026-01-01",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="2026-02-04",
            help="End date in YYYY-MM-DD format (inclusive). Default: 2026-02-04",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.5,
            help="Seconds to sleep between each org/day query. Default: 0.5",
        )
        parser.add_argument(
            "--batch-sleep",
            type=float,
            default=5.0,
            help="Seconds to sleep between each day (after processing all orgs for that day). Default: 5.0",
        )
        parser.add_argument(
            "--org-id",
            type=int,
            default=None,
            help="Process only this specific org ID. Default: all active orgs.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show what would be done, without writing to the database.",
        )

    def handle(self, *args, **options):
        start_date = datetime.strptime(options["start_date"], "%Y-%m-%d").date()
        end_date = datetime.strptime(options["end_date"], "%Y-%m-%d").date()
        sleep_between_orgs = options["sleep"]
        sleep_between_days = options["batch_sleep"]
        specific_org_id = options["org_id"]
        dry_run = options["dry_run"]

        if start_date > end_date:
            self.stderr.write(self.style.ERROR("start-date must be before or equal to end-date"))
            return

        # Get orgs to process
        if specific_org_id:
            orgs = list(Org.objects.filter(id=specific_org_id, is_active=True).only("id", "name"))
            if not orgs:
                self.stderr.write(self.style.ERROR(f"Active org with id={specific_org_id} not found"))
                return
        else:
            orgs = list(Org.objects.filter(is_active=True).only("id", "name").order_by("id"))

        total_days = (end_date - start_date).days + 1
        total_operations = total_days * len(orgs)

        self.stdout.write(
            self.style.WARNING(
                f"\n{'[DRY RUN] ' if dry_run else ''}"
                f"Backfilling UniqueContactCount\n"
                f"  Date range: {start_date} to {end_date} ({total_days} days)\n"
                f"  Orgs: {len(orgs)}\n"
                f"  Total queries: {total_operations}\n"
                f"  Sleep between orgs: {sleep_between_orgs}s\n"
                f"  Sleep between days: {sleep_between_days}s\n"
            )
        )

        processed = 0
        created = 0
        updated = 0
        skipped = 0
        errors = 0
        start_time = time.time()

        current_day = start_date
        while current_day <= end_date:
            day_start = datetime.combine(current_day, datetime.min.time()).replace(tzinfo=pytz.UTC)
            day_end = datetime.combine(current_day + timedelta(days=1), datetime.min.time()).replace(tzinfo=pytz.UTC)

            self.stdout.write(f"\n--- Processing {current_day} ---")

            for org in orgs:
                try:
                    # Count distinct contacts that sent incoming messages on this day for this org
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
                        self.stdout.write(f"  [DRY RUN] org={org.id} ({org.name}): {count} unique contacts")
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
                            self.stdout.write(
                                f"  org={org.id} ({org.name}): {count} unique contacts "
                                f"({'created' if was_created else 'updated'})"
                            )

                except Exception as e:
                    errors += 1
                    self.stderr.write(
                        self.style.ERROR(f"  ERROR org={org.id} ({org.name}): {e}")
                    )

                # Sleep between org queries to avoid overloading the database
                time.sleep(sleep_between_orgs)

                # Progress report every 100 operations
                if processed % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    remaining = (total_operations - processed) / rate if rate > 0 else 0
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Progress: {processed}/{total_operations} "
                            f"({processed * 100 // total_operations}%) "
                            f"- {rate:.1f} ops/s "
                            f"- ETA: {remaining / 60:.1f} min"
                        )
                    )

            # Sleep between days to give the database a longer break
            self.stdout.write(f"  Day {current_day} done. Sleeping {sleep_between_days}s...")
            time.sleep(sleep_between_days)

            current_day += timedelta(days=1)

        # Final summary
        elapsed = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'[DRY RUN] ' if dry_run else ''}"
                f"Backfill completed!\n"
                f"  Processed: {processed}\n"
                f"  Created: {created}\n"
                f"  Updated: {updated}\n"
                f"  Errors: {errors}\n"
                f"  Time: {elapsed / 60:.1f} minutes\n"
            )
        )
