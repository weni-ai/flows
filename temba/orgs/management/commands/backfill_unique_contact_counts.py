from datetime import datetime, time, timedelta

import pytz

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from temba.msgs.models import Msg
from temba.orgs.models import Org, UniqueContactCount


class Command(BaseCommand):
    help = (
        "Recalculates UniqueContactCount for the given days (UTC) by counting distinct contacts with incoming "
        "messages in the database. Prints the counts without saving unless --commit is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument("days", nargs="+", help="Days to recalculate, as YYYY-MM-DD")
        parser.add_argument("--commit", action="store_true", help="Save the recalculated counts")

    def handle(self, *args, **options):
        days = [self._parse_day(d) for d in options["days"]]

        for day in days:
            self._backfill_day(day, options["commit"])

    def _parse_day(self, value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise CommandError(f"Invalid day '{value}', expected YYYY-MM-DD")

    def _backfill_day(self, day, commit):
        start = datetime.combine(day, time.min).replace(tzinfo=pytz.UTC)
        counts = dict(
            Msg.objects.filter(
                direction=Msg.DIRECTION_IN, created_on__gte=start, created_on__lt=start + timedelta(days=1)
            )
            .values_list("org_id")
            .annotate(count=Count("contact_id", distinct=True))
            .order_by()
        )

        new_counts = {
            org_id: counts.get(org_id, 0) for org_id in Org.objects.filter(is_active=True).values_list("id", flat=True)
        }
        existing = {c.org_id: c for c in UniqueContactCount.objects.filter(day=day)}
        stored_total = sum(c.count for c in existing.values())

        to_update, to_create = [], []
        for org_id, count in new_counts.items():
            record = existing.get(org_id)
            if record is None:
                to_create.append(UniqueContactCount(org_id=org_id, day=day, count=count))
            elif record.count != count:
                record.count = count
                to_update.append(record)

        self.stdout.write(
            f"{day}: stored total={stored_total} ({len(existing)} rows), "
            f"recalculated total={sum(new_counts.values())} "
            f"({sum(1 for c in new_counts.values() if c)} orgs with contacts), "
            f"{len(to_update)} rows to update, {len(to_create)} rows to create"
        )

        if not commit:
            return

        with transaction.atomic():
            UniqueContactCount.objects.bulk_update(to_update, ["count"], batch_size=1000)
            UniqueContactCount.objects.bulk_create(to_create, batch_size=1000)

        self.stdout.write(f"{day}: saved")
