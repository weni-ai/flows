import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.features.usecases.feature_template_integration import integrate_feature_template_consumer


class IntegrateFeatureTemplateConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print("[IntegrateFeatureTemplateConsumer] - Consuming a message.")
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

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[IntegrateFeatureTemplateConsumer] - Message rejected by: {exception}")
