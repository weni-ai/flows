import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.features.usecases.feature_template_integration import integrate_feature_template_consumer


class IntegrateFeatureTemplateConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)
            integrate_feature_template_consumer(
                project_uuid=body.get("project_uuid"),
                feature_uuid=body.get("feature_uuid"),
                feature_version_uuid=body.get("feature_version"),
                definition=body.get("definition"),
                parameters=body.get("parameters"),
                user_email=body.get("user_email"),
            )

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
