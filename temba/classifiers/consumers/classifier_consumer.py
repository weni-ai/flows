import amqp
from sentry_sdk import capture_exception

from temba.classifiers.usecases.classifier_creation import create_classifier
from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser


class ClassifierConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):
        print(f"[ClassifierConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            create_classifier(
                uuid=body.get("uuid"),
                repository=body.get("repository"),
                access_token=body.get("access_token"),
                name=body.get("name"),
                project_uuid=body.get("project_uuid"),
                user_email=body.get("user_email"),
            )

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[ClassifierConsumer] - Message rejected by: {exception}")
