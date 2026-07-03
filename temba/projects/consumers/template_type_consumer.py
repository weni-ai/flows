import logging

from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.projects.usecases.template_type_creation import create_template_type

logger = logging.getLogger(__name__)


class TemplateTypeConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            logger.info("[TemplateTypeConsumer] Received message")
            body = message.json()
            logger.info(
                "[TemplateTypeConsumer] Processing uuid=%s name=%s project_uuid=%s",
                body.get("uuid"),
                body.get("name"),
                body.get("project_uuid"),
            )
            create_template_type(uuid=body.get("uuid"), name=body.get("name"), project_uuid=body.get("project_uuid"))

            self.ack()
            logger.info("[TemplateTypeConsumer] Message processed successfully uuid=%s", body.get("uuid"))
        except Exception as exception:
            logger.exception("[TemplateTypeConsumer] Failed to process message")
            capture_exception(exception)
            raise
