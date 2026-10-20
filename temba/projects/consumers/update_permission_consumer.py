from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.projects.usecases.permission_update import update_permission


class UpdatePermissionConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            body = message.json()

            update_permission(
                project_uuid=body.get("project"),  # project_uuid
                action=body.get("action"),
                user_email=body.get("user"),  # user_email
                role=body.get("role"),
            )

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
