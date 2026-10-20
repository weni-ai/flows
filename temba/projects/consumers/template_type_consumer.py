from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.projects.usecases.template_type_creation import create_template_type


class TemplateTypeConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            body = message.json()
            create_template_type(uuid=body.get("uuid"), name=body.get("name"), project_uuid=body.get("project_uuid"))

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
