import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.features.usecases.delete_feature_integration import delete_feature_template


class DeleteFeatureTemplateIntegrationConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)
            delete_feature_template(
                features_flow=body.get("features_flow"),
                user_email=body.get("user_email"),
            )

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
