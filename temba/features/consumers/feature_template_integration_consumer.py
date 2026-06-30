import logging

import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.features.usecases.feature_template_integration import integrate_feature_template_consumer

logger = logging.getLogger(__name__)


class IntegrateFeatureTemplateConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            logger.info("[IntegrateFeatureTemplateConsumer] Received message")
            body = JSONParser.parse(message.body)
            logger.info(
                "[IntegrateFeatureTemplateConsumer] Processing project_uuid=%s feature_uuid=%s user_email=%s",
                body.get("project_uuid"),
                body.get("feature_uuid"),
                body.get("user_email"),
            )
            integrate_feature_template_consumer(
                project_uuid=body.get("project_uuid"),
                feature_uuid=body.get("feature_uuid"),
                feature_version_uuid=body.get("feature_version"),
                definition=body.get("definition"),
                parameters=body.get("parameters"),
                user_email=body.get("user_email"),
            )

            self.ack()
            logger.info(
                "[IntegrateFeatureTemplateConsumer] Message processed successfully project_uuid=%s feature_uuid=%s",
                body.get("project_uuid"),
                body.get("feature_uuid"),
            )
        except Exception as exception:
            logger.exception("[IntegrateFeatureTemplateConsumer] Failed to process message")
            capture_exception(exception)
            raise
