from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from ..usecases.classifier_creation import create_classifier


class ClassifierConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            body = message.json()
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
