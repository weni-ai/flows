import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from ..usecases.classifier_creation import create_classifier


class ClassifierConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
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

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
