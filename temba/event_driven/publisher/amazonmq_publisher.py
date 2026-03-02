import logging
from typing import Dict

import pika.exceptions
from weni.pika_eda.connection import PikaConnection
from weni.pika_eda.pika_publisher import PikaEDAPublisher

from temba.event_driven.connection.amazonmq_connection import AmazonMQConnectionFactory

logger = logging.getLogger(__name__)

_RECOVERABLE_ERRORS = (
    pika.exceptions.AMQPConnectionError,
    pika.exceptions.AMQPChannelError,
    pika.exceptions.StreamLostError,
    ConnectionError,
    OSError,
)


class AmazonMQPublisher:  # pragma: no cover
    """
    Publisher for AmazonMQ using the weni-eda PikaEDAPublisher.
    Uses AmazonMQConnectionFactory to obtain connection parameters
    (with SSL/TLS enabled by default for AmazonMQ).

    The underlying PikaEDAPublisher is created lazily on the first
    send_message call so that broker settings are only required at
    publish time, not at import/construction time.

    Includes retry-on-stale-connection logic: AmazonMQ may silently
    close idle TCP/TLS sessions, causing RxEndOfFile on the next
    publish.  When that happens the singleton connection is reset and
    one retry is attempted with a fresh connection.
    """

    MAX_RETRIES = 1

    def __init__(self) -> None:
        self._publisher = None

    def _get_publisher(self) -> PikaEDAPublisher:
        if self._publisher is None:
            self._publisher = PikaEDAPublisher(
                connection_params_factory=AmazonMQConnectionFactory,
            )
        return self._publisher

    @staticmethod
    def _reset_connection() -> None:
        """Force PikaConnection to drop the stale singleton so the
        next get_connection() call creates a fresh one."""
        try:
            if PikaConnection.connection and not PikaConnection.connection.is_closed:
                PikaConnection.connection.close()
        except Exception:
            pass
        PikaConnection.connection = None

    def send_message(self, body: Dict, exchange: str, routing_key: str = "") -> None:
        last_exc = None
        for attempt in range(1 + self.MAX_RETRIES):
            try:
                self._get_publisher().send_message(body=body, exchange=exchange, routing_key=routing_key)
                return
            except _RECOVERABLE_ERRORS as exc:
                last_exc = exc
                logger.warning(
                    "AmazonMQ publish failed (attempt %d/%d): %s",
                    attempt + 1,
                    1 + self.MAX_RETRIES,
                    exc,
                )
                self._reset_connection()

        raise last_exc
