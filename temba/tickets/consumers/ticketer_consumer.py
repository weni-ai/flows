import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser

from ..usecases.ticketer_creation import create_ticketer


class TicketConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[TicketerConsumer] - Consuming a message. Body: {message.body}")
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

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[TicketerConsumer] - Message rejected by: {exception}")
