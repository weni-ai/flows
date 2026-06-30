import logging

import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from ..usecases.classifier_creation import create_classifier

logger = logging.getLogger(__name__)


class ClassifierConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            logger.info("[ClassifierConsumer] Received message")
            body = JSONParser.parse(message.body)
            logger.info(
                "[ClassifierConsumer] Processing uuid=%s project_uuid=%s user_email=%s",
                body.get("uuid"),
                body.get("project_uuid"),
                body.get("user_email"),
            )
            create_classifier(
                uuid=body.get("uuid"),
                repository=body.get("repository"),
                access_token=body.get("access_token"),
                name=body.get("name"),
                project_uuid=body.get("project_uuid"),
                user_email=body.get("user_email"),
            )

            self.ack()
            logger.info("[ClassifierConsumer] Message processed successfully uuid=%s", body.get("uuid"))
        except Exception as exception:
            logger.exception("[ClassifierConsumer] Failed to process message")
            capture_exception(exception)
            raise
