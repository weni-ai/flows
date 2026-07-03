import logging

from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.projects.usecases.update_brain_on import update_project_brain_on

logger = logging.getLogger(__name__)


class UpdateBrainOnConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            logger.info("[UpdateBrainOnConsumer] Received message")
            body = message.json()
            logger.info(
                "[UpdateBrainOnConsumer] Processing project_uuid=%s brain_on=%s user_email=%s",
                body.get("project_uuid"),
                body.get("brain_on"),
                body.get("user"),
            )
            update_project_brain_on(
                project_uuid=body.get("project_uuid"),
                brain_on=body.get("brain_on"),
                user_email=body.get("user"),
            )

            self.ack()
            logger.info(
                "[UpdateBrainOnConsumer] Message processed successfully project_uuid=%s",
                body.get("project_uuid"),
            )
        except Exception as exception:
            logger.exception("[UpdateBrainOnConsumer] Failed to process message")
            capture_exception(exception)
            raise
