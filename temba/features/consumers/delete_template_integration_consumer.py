import logging

import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.features.usecases.delete_feature_integration import delete_feature_template

logger = logging.getLogger(__name__)


class DeleteFeatureTemplateIntegrationConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            logger.info("[DeleteFeatureTemplateIntegrationConsumer] Received message")
            body = JSONParser.parse(message.body)
            logger.info(
                "[DeleteFeatureTemplateIntegrationConsumer] Processing user_email=%s features_flow_count=%s",
                body.get("user_email"),
                len(body.get("features_flow") or []),
            )
            delete_feature_template(
                features_flow=body.get("features_flow"),
                user_email=body.get("user_email"),
            )

            self.ack()
            logger.info(
                "[DeleteFeatureTemplateIntegrationConsumer] Message processed successfully user_email=%s",
                body.get("user_email"),
            )
        except Exception as exception:
            logger.exception("[DeleteFeatureTemplateIntegrationConsumer] Failed to process message")
            capture_exception(exception)
            raise
