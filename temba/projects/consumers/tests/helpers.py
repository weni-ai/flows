import json
from unittest.mock import Mock, patch

from weni.eda.events import Event

DELIVERY_TAG = "test-delivery-tag"
PRODUCER = "weni-engine"


def handle(consumer, body) -> Mock:
    """
    Delivers a message to consumer.handle() and returns the mocked broker channel, so tests assert on the real ack
    and reject path. The weni-eda signals are patched because their close_old_connections receiver would break the
    test transaction.
    """
    channel = Mock()
    raw = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
    with patch("weni.eda.django.consumers.consumer.message_started"), patch(
        "weni.eda.django.consumers.consumer.message_finished"
    ):
        consumer.handle(Mock(body=raw, delivery_tag=DELIVERY_TAG, channel=channel))
    return channel


def build_envelope(event_type: str, data, **overrides) -> dict:
    envelope = Event.build(event_type, data, producer=PRODUCER).to_dict()
    envelope.update(overrides)
    return envelope


def assert_acked(channel: Mock) -> None:
    channel.basic_ack.assert_called_once_with(DELIVERY_TAG)
    channel.basic_reject.assert_not_called()


def assert_rejected(channel: Mock) -> None:
    channel.basic_reject.assert_called_once_with(DELIVERY_TAG, requeue=False)
    channel.basic_ack.assert_not_called()
