import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.features.usecases.delete_feature_integration import delete_feature_template


class DeleteFeatureTemplateIntegrationConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print("[DeleteFeatureTemplateIntegrationConsumer] - Consuming a message.")  # Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            delete_feature_template(
                features_flow=body.get("features_flow"),
                user_email=body.get("user_email"),
            )

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[DeleteFeatureTemplateIntegrationConsumer] - Message rejected by: {exception}")
