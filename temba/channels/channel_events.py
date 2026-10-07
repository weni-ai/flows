import logging
from enum import Enum
from typing import TYPE_CHECKING

from django.conf import settings

from temba.channels.tasks import task_publish_channel_event
from temba.utils import on_transaction_commit

if TYPE_CHECKING:
    from temba.channels.models import Channel

logger = logging.getLogger(__name__)

WHATSAPP_CHANNEL_TYPES = frozenset({"WAC", "WA"})


class ChannelEventType(str, Enum):
    DELETED = "channel.deleted"


def build_channel_event_data(channel: "Channel") -> dict:
    """Whitelist of channel fields safe to publish.

    ``channel.config`` holds provider tokens and must never be copied whole.
    """
    config = channel.config or {}
    data = {
        "channel_uuid": str(channel.uuid),
        "project_uuid": str(channel.org.proj_uuid),
        "channel_type": channel.channel_type,
        "address": channel.address,
        "is_active": channel.is_active,
        "occurred_at": channel.modified_on.isoformat(),
    }
    if channel.channel_type in WHATSAPP_CHANNEL_TYPES:
        data["whatsapp"] = {
            "phone_number": config.get("wa_number"),
            "phone_number_id": channel.address,
            "waba_id": config.get("wa_waba_id"),
        }
    return data


def build_channel_event_routing_key(event_type: str, channel_type: str) -> str:
    action = event_type.split(".")[-1]
    return f"channel.{action}.{channel_type.lower()}"


def publish_channel_deleted(channel: "Channel") -> None:
    """Enqueue ``channel.deleted`` after the current transaction commits."""
    if not getattr(settings, "CHANNEL_EVENTS_PUBLISH_ENABLED", False):
        return

    if channel.org is None or not channel.org.proj_uuid:
        logger.info(
            f"Skipping channel.deleted channel_type={channel.channel_type} "
            f"channel_uuid={channel.uuid}: channel has no project"
        )
        return

    event_type = ChannelEventType.DELETED.value
    data = build_channel_event_data(channel)
    routing_key = build_channel_event_routing_key(event_type, channel.channel_type)

    on_transaction_commit(
        lambda event_type=event_type, data=data, routing_key=routing_key: task_publish_channel_event.delay(
            event_type, data, routing_key
        )
    )
