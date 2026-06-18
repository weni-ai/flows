import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.projects.usecases.permission_update import update_permission


class UpdatePermissionConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)

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
