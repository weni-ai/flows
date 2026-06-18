import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from ..usecases.ticketer_creation import create_ticketer


class TicketConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)
            create_ticketer(
                uuid=body.get("uuid"),
                name=body.get("name"),
                user_email=body.get("user_email"),
                project_uuid=body.get("project_uuid"),
                project_auth=body.get("project_auth"),
                queues=body.get("queues"),
            )

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
