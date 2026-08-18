# Generated manually: backfill CtwaReferralSource.org from CTWA channels

import logging
from collections import defaultdict

from django.db import migrations, transaction

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def org_channels_by_source_id(source_ids, CTWA, Channel):
    """Map each referral source id to {org_id: [channel_uuid, ...]} of its CTWA channels."""
    if not source_ids:
        return {}

    ctwa_rows = CTWA.objects.filter(referral_source_id__in=source_ids).values_list(
        "referral_source_id", "channel_uuid"
    )
    channel_uuids = {str(channel_uuid) for _, channel_uuid in ctwa_rows}
    org_by_channel = {
        str(uuid): org_id
        for uuid, org_id in Channel.objects.filter(uuid__in=channel_uuids, org_id__isnull=False).values_list(
            "uuid", "org_id"
        )
    }

    channels_by_source_org = defaultdict(lambda: defaultdict(list))
    for source_id, channel_uuid in ctwa_rows:
        org_id = org_by_channel.get(str(channel_uuid))
        if org_id is not None:
            channels_by_source_org[source_id][org_id].append(channel_uuid)

    return {
        source_id: dict(sorted(org_channels.items())) for source_id, org_channels in channels_by_source_org.items()
    }


def apply_orgs_to_source(source, channels_by_org, CtwaReferralSource, CTWA):
    """Assign the anchor org to source and clone it for each extra org, retargeting CTWAs."""
    if not channels_by_org:
        return

    anchor_org_id = source.org_id or next(iter(channels_by_org))
    if source.org_id != anchor_org_id:
        CtwaReferralSource.objects.filter(id=source.id).update(org_id=anchor_org_id)
        source.org_id = anchor_org_id

    for org_id, channel_uuids in channels_by_org.items():
        if org_id == anchor_org_id:
            continue
        clone, _ = CtwaReferralSource.objects.get_or_create(
            org_id=org_id,
            source_id=source.source_id,
            source_type=source.source_type,
            defaults={
                "source_url": source.source_url,
                "headline": source.headline,
                "body": source.body,
            },
        )
        CTWA.objects.filter(referral_source_id=source.id, channel_uuid__in=channel_uuids).update(
            referral_source_id=clone.id
        )


def backfill_ctwa_referral_source_org(CtwaReferralSource, CTWA, Channel, batch_size=BATCH_SIZE, source_ids=None):
    max_id = 0
    while True:
        queryset = CtwaReferralSource.objects.filter(id__gt=max_id).order_by("id")
        if source_ids is not None:
            queryset = queryset.filter(id__in=source_ids)
        else:
            queryset = queryset.filter(org_id__isnull=True)

        batch = list(queryset[:batch_size])
        if not batch:
            break

        with transaction.atomic():
            org_map = org_channels_by_source_id([source.id for source in batch], CTWA, Channel)
            for source in batch:
                channels_by_org = org_map.get(source.id, {})
                if not channels_by_org:
                    logger.warning(
                        f"Could not resolve org for CtwaReferralSource id={source.id} "
                        f"source_id={source.source_id} source_type={source.source_type}"
                    )
                    continue
                if source.org_id is not None and source.org_id not in channels_by_org:
                    logger.warning(
                        f"CtwaReferralSource id={source.id} has org_id={source.org_id} "
                        f"but its CTWAs resolve to org_ids={list(channels_by_org)}"
                    )
                apply_orgs_to_source(source, channels_by_org, CtwaReferralSource, CTWA)

        max_id = batch[-1].id


def forwards(apps, schema_editor):
    CtwaReferralSource = apps.get_model("conversion_events", "CtwaReferralSource")
    CTWA = apps.get_model("conversion_events", "CTWA")
    Channel = apps.get_model("channels", "Channel")
    backfill_ctwa_referral_source_org(CtwaReferralSource, CTWA, Channel)


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("conversion_events", "0003_ctwareferralsource_org"),
        ("channels", "0137_alter_channel_name"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
