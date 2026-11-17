"""
Reconciliation of the KubeVoIP objects Flows created with the TPH channels in the database (spec 019, FR-013).

It corrects the two ways the cluster and the database drift apart: objects whose channel is gone (a revocation that
failed), and channels whose SIP user is gone (for example after a cluster rebuild). It only ever looks at objects that
carry the Flows label, and it caps the number of deletions per run so a bug cannot erase every customer credential.
"""

import logging
from datetime import datetime, timezone

from . import constants, manifests, provisioning
from .provisioning import SIPProvisioner, SIPProvisioningError

TPH_CHANNEL_TYPE = "TPH"

logger = logging.getLogger(__name__)


def reconcile(active_channels, provisioner=None, now=None):
    """
    ``active_channels`` is every active TPH channel. Returns a summary dict. A failure on one channel is logged and does
    not stop the others. A failure to list the cluster stops the run (nothing is known to be orphaned).
    """
    provisioner = provisioner or SIPProvisioner()
    now = now or datetime.now(timezone.utc)
    summary = {"deleted": 0, "recreated": 0, "errors": 0, "capped": False}

    managed = provisioner.list_managed()
    channels_by_uuid = {str(channel.uuid): channel for channel in active_channels}

    # objects of channels that are inactive or do not exist
    for channel_uuid in sorted(set(managed) - set(channels_by_uuid)):
        if _is_too_new(managed[channel_uuid]["newest"], now):
            continue  # most likely a claim still running in a transaction
        if summary["deleted"] >= constants.RECONCILE_MAX_DELETIONS_PER_RUN:
            summary["capped"] = True
            logger.error(
                "tph sip: reconciliation deletion cap reached, stopping",
                extra={"event": "reconcile", "outcome": "capped", "cap": constants.RECONCILE_MAX_DELETIONS_PER_RUN},
            )
            break
        logger.info(
            "tph sip: deleting objects of a channel that is not active",
            extra={
                "event": "reconcile",
                "channel_uuid": channel_uuid,
                "kinds": sorted(managed[channel_uuid]["kinds"]),
            },
        )
        try:
            provisioner.deprovision(channel_uuid)
        except SIPProvisioningError as e:
            summary["errors"] += 1
            provisioning.report(e.__cause__ or e, event="reconcile_delete", channel_uuid=channel_uuid)
        else:
            summary["deleted"] += 1

    # active channels whose SIP user disappeared
    for channel_uuid, channel in channels_by_uuid.items():
        if not provisioning.channel_is_provisioned(channel):
            continue
        if constants.KIND_SIP_USER in managed.get(channel_uuid, {}).get("kinds", {}):
            continue

        try:
            _recreate(provisioner, channel)
        except SIPProvisioningError as e:
            summary["errors"] += 1
            provisioning.report(
                e.__cause__ or e,
                event="reconcile_recreate",
                channel_uuid=channel_uuid,
                org_id=channel.org_id,
                user_id=channel.created_by_id,
            )
        else:
            summary["recreated"] += 1

    return summary


def _is_too_new(newest, now):
    """``newest`` is an RFC 3339 UTC timestamp from the cluster. An unreadable one is treated as new, the safe side."""
    if not newest:
        return False
    try:
        created = datetime.strptime(newest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (now - created).total_seconds() < constants.RECONCILE_MIN_AGE_SECS


def _recreate(provisioner, channel):
    name = manifests.resource_name(channel.uuid)
    # when the password entry survived, the password the customer already holds still works: no reset is needed
    had_password = provisioner.has_password_entry(name)

    provisioner.provision(channel.uuid, channel.id, channel.address)

    if not had_password:
        config = dict(channel.config or {})
        config[constants.CONFIG_SIP_RESET_REQUIRED] = True
        channel.config = config
        channel.save(update_fields=["config"])

    logger.warning(
        "tph sip: recreated the objects of a channel",
        extra={
            "event": "reconcile",
            "outcome": "recreated",
            "channel_uuid": str(channel.uuid),
            "org_id": channel.org_id,
            "reset_required": not had_password,
        },
    )


def run_reconciliation():
    """
    Entry point of the periodic task. Does nothing while provisioning is turned off, so a cluster without the Flows
    role is never contacted. Returns the summary, or None when it did not run.
    """
    if not provisioning.is_enabled():
        return None

    from temba.channels.models import Channel

    channels = Channel.objects.filter(is_active=True, channel_type=TPH_CHANNEL_TYPE)
    summary = reconcile(list(channels.only("id", "uuid", "address", "config", "org_id", "created_by_id")))
    logger.info("tph sip: reconciliation finished", extra={"event": "reconcile", "outcome": "finished", **summary})
    return summary
