"""
Base SQS Consumer class.

Provides an abstract base class for implementing SQS message consumers,
similar to the EDAConsumer pattern used for RabbitMQ.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from sentry_sdk import capture_exception

from temba.sqs.signals import message_finished, message_started

logger = logging.getLogger(__name__)


class SQSConsumer(ABC):
    """
    Abstract base class for SQS message consumers.

    Similar to EDAConsumer but designed for SQS message format.
    Subclasses must implement the `consume` method.

    Example:
        ```python
        class MyConsumer(SQSConsumer):
            def consume(self, message: dict) -> None:
                data = message.get("data")
                # Process the message...
        ```
    """

    def handle(self, message: dict[str, Any]) -> bool:
        """
        Process an SQS message.

        Wraps the consume method with signal emission and error handling.

        Args:
            message: The parsed JSON body of the SQS message.

        Returns:
            True if the message was processed successfully (should be deleted).
            False if processing failed (should be retried or sent to DLQ).
        """
        message_started.send(sender=self.__class__)
        try:
            self.consume(message)
            return True
        except Exception as e:
            self.on_error(message, e)
            return False
        finally:
            message_finished.send(sender=self.__class__)

    @abstractmethod
    def consume(self, message: dict[str, Any]) -> None:
        """
        Process the message payload.

        Subclasses must implement this method to handle the actual
        message processing logic.

        Args:
            message: The parsed JSON body of the SQS message.

        Raises:
            Exception: Any exception will cause the message to be retried.
        """
        pass

    def on_error(self, message: dict[str, Any], error: Exception) -> None:
        """
        Handle errors during message processing.

        Default implementation logs the error and reports to Sentry.
        Subclasses can override for custom error handling.

        Args:
            message: The message that failed to process.
            error: The exception that was raised.
        """
        logger.error(
            f"[{self.__class__.__name__}] Error processing message: {error}",
            exc_info=True,
            extra={"message": message},
        )
        capture_exception(error)
