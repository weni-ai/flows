# Generated manually: collapse 0002 1:1 leftover sources into one "legacy" row per org

import logging

from django.db import migrations, transaction
from django.db.models import Count, Max, Min

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
LEGACY_SOURCE_ID = "legacy"
LEGACY_SOURCE_TYPE = "ad"
# POSIX character class: PostgreSQL's ~ operator does not treat \d as digits.
LEGACY_SOURCE_ID_PATTERN = r"^legacy-[0-9]+$"


def legacy_sources(CtwaReferralSource):
    return CtwaReferralSource.objects.filter(
        source_type=LEGACY_SOURCE_TYPE,
        source_id__regex=LEGACY_SOURCE_ID_PATTERN,
    )


def org_ids_with_legacy_sources(CtwaReferralSource):
    return list(
        legacy_sources(CtwaReferralSource).values_list("org_id", flat=True).distinct().order_by("org_id")
    )


def preserve_seen_window(canonical_id, first_seen_at, last_seen_at, CtwaReferralSource):
    """Write the aggregated window with update() so auto_now does not overwrite it."""
    updates = {}
    if first_seen_at is not None:
        updates["first_seen_at"] = first_seen_at
    if last_seen_at is not None:
        updates["last_seen_at"] = last_seen_at
    if not updates:
        return
    CtwaReferralSource.objects.filter(id=canonical_id).update(**updates)


def _merged_seen_window(canonical, first_seen_at, last_seen_at):
    if canonical.first_seen_at is not None and (first_seen_at is None or canonical.first_seen_at < first_seen_at):
        first_seen_at = canonical.first_seen_at
    if canonical.last_seen_at is not None and (last_seen_at is None or canonical.last_seen_at > last_seen_at):
        last_seen_at = canonical.last_seen_at
    return first_seen_at, last_seen_at


def collapse_org_legacy_sources(org_id, CtwaReferralSource, CTWA, batch_size):
    """Repoint this org's 0002 leftover sources onto a single canonical row.

    CTWA.referral_source is PROTECT, so events must be retargeted before the
    leftover source rows can be deleted.
    """
    sources_qs = legacy_sources(CtwaReferralSource).filter(org_id=org_id)
    window = sources_qs.aggregate(
        Min("first_seen_at"),
        Max("last_seen_at"),
        Count("id"),
    )
    collapsed_count = window["id__count"]
    if not collapsed_count:
        return

    with transaction.atomic():
        canonical, created = CtwaReferralSource.objects.get_or_create(
            org_id=org_id,
            source_id=LEGACY_SOURCE_ID,
            source_type=LEGACY_SOURCE_TYPE,
            defaults={
                "source_url": None,
                "headline": None,
                "body": None,
            },
        )

        first_seen_at = window["first_seen_at__min"]
        last_seen_at = window["last_seen_at__max"]
        if not created:
            first_seen_at, last_seen_at = _merged_seen_window(canonical, first_seen_at, last_seen_at)
        preserve_seen_window(canonical.id, first_seen_at, last_seen_at, CtwaReferralSource)

    repointed = 0
    max_id = 0
    while True:
        chunk = list(
            sources_qs.filter(id__gt=max_id).order_by("id").values_list("id", flat=True)[:batch_size]
        )
        if not chunk:
            break

        with transaction.atomic():
            repointed += CTWA.objects.filter(referral_source_id__in=chunk).update(
                referral_source_id=canonical.id
            )
            CtwaReferralSource.objects.filter(id__in=chunk).delete()

        max_id = chunk[-1]

    logger.info(
        f"Collapsed {collapsed_count} legacy CtwaReferralSource rows into canonical id={canonical.id} "
        f"for org_id={org_id}, repointed {repointed} CTWA events"
    )


def collapse_legacy_sources_per_org(CtwaReferralSource, CTWA, batch_size=BATCH_SIZE, org_ids=None):
    if org_ids is None:
        org_ids = org_ids_with_legacy_sources(CtwaReferralSource)
    for org_id in org_ids:
        collapse_org_legacy_sources(org_id, CtwaReferralSource, CTWA, batch_size)


def forwards(apps, schema_editor):
    CtwaReferralSource = apps.get_model("conversion_events", "CtwaReferralSource")
    CTWA = apps.get_model("conversion_events", "CTWA")
    collapse_legacy_sources_per_org(CtwaReferralSource, CTWA)


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("conversion_events", "0005_ctwareferralsource_org_not_null"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
