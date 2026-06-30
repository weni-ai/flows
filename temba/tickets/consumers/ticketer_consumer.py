import logging

import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from ..usecases.ticketer_creation import create_ticketer

logger = logging.getLogger(__name__)


class TicketConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            logger.info("[TicketConsumer] Received message")
            body = JSONParser.parse(message.body)
            logger.info(
                "[TicketConsumer] Processing uuid=%s project_uuid=%s user_email=%s",
                body.get("uuid"),
                body.get("project_uuid"),
                body.get("user_email"),
            )
            create_ticketer(
                uuid=body.get("uuid"),
                name=body.get("name"),
                user_email=body.get("user_email"),
                project_uuid=body.get("project_uuid"),
                project_auth=body.get("project_auth"),
                queues=body.get("queues"),
            )

            self.ack()
            logger.info("[TicketConsumer] Message processed successfully uuid=%s", body.get("uuid"))
        except Exception as exception:
            logger.exception("[TicketConsumer] Failed to process message")
            capture_exception(exception)
            raise
