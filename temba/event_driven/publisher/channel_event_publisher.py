from typing import Optional

from weni.eda.django.connection_params import AMQConnectionParamsFactory
from weni.eda.eda_publisher import EDAPublisher
from weni.eda.events import Event

from django.conf import settings

CHANNEL_EVENT_PRODUCER = "flows"
DEFAULT_CHANNEL_EVENTS_EXCHANGE = "flows-channel-events.topic"


class ChannelEventPublisher:
    """Publishes channel lifecycle events to Amazon MQ.

    The body is the full event envelope. ``event_type`` is not forwarded to
    ``EDAPublisher.send_message`` because that method would wrap the body again.
    """

    def __init__(self, publisher: Optional[EDAPublisher] = None):
        self._publisher = publisher

    def publish(self, event_type: str, data: dict, routing_key: str) -> None:
        publisher = self._publisher or EDAPublisher(AMQConnectionParamsFactory)
        publisher.send_message(
            body=Event.build(
                event_type, data, producer=CHANNEL_EVENT_PRODUCER
            ).to_dict(),
            exchange=getattr(
                settings, "CHANNEL_EVENTS_EXCHANGE", DEFAULT_CHANNEL_EVENTS_EXCHANGE
            ),
            routing_key=routing_key,
        )
