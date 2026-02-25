"""
SQS Message Handlers.

Maps queue messages to their respective consumers.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def handle_broadcast_messages(message: dict[str, Any]) -> bool:
    """
    Handle messages from the broadcasts queue.

    Dispatches messages to the WhatsappBroadcastConsumer.

    Args:
        message: The parsed SQS message body.

    Returns:
        True if message was processed successfully, False otherwise.
    """
    from temba.api.v2.internals.broadcasts.consumers import WhatsappBroadcastConsumer

    consumer = WhatsappBroadcastConsumer()
    return consumer.handle(message)
