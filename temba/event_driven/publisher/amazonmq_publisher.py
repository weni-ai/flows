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
    """

    def __init__(self) -> None:
        self._publisher = PikaEDAPublisher(
            connection_params_factory=AmazonMQConnectionFactory,
        )

    def send_message(self, body: Dict, exchange: str, routing_key: str = "") -> None:
        """
        Publishes *body* (JSON-serialisable dict) to the given exchange/routing_key.
        Delegates entirely to weni-eda's PikaEDAPublisher which handles
        connection management, serialisation and channel lifecycle.
        """
        self._publisher.send_message(body=body, exchange=exchange, routing_key=routing_key)
