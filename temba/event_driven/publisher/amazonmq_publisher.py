import logging
from typing import Dict

from weni.pika_eda.pika_publisher import PikaEDAPublisher

from temba.event_driven.connection.amazonmq_connection import AmazonMQConnectionFactory

logger = logging.getLogger(__name__)


class AmazonMQPublisher:  # pragma: no cover
    """
    Publisher for AmazonMQ using the weni-eda PikaEDAPublisher.
    Uses AmazonMQConnectionFactory to obtain connection parameters
    (with SSL/TLS enabled by default for AmazonMQ).

    The underlying PikaEDAPublisher is created lazily on the first
    send_message call so that broker settings are only required at
    publish time, not at import/construction time.
    """

    def __init__(self) -> None:
        self._publisher = None

    def _get_publisher(self) -> PikaEDAPublisher:
        if self._publisher is None:
            self._publisher = PikaEDAPublisher(
                connection_params_factory=AmazonMQConnectionFactory,
            )
        return self._publisher

    def send_message(self, body: Dict, exchange: str, routing_key: str = "") -> None:
        self._get_publisher().send_message(body=body, exchange=exchange, routing_key=routing_key)
