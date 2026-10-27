from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.projects.usecases.update_brain_on import update_project_brain_on


class UpdateBrainOnConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            body = message.json()
            update_project_brain_on(
                project_uuid=body.get("project_uuid"),
                brain_on=body.get("brain_on"),
                user_email=body.get("user"),
            )

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
