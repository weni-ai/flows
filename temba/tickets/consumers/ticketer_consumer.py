import amqp
from sentry_sdk import capture_exception
from temba.event_driven.consumers import EDAConsumer

from temba.event_driven.parsers.json_parser import JSONParser
from temba.tickets.usecases.ticketer_creation import create_ticketer

class TicketConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)
            print(f"[TicketerConsumer] - Consuming a message. Body: {body}")
            create_ticketer(
                ticketer_type=body.get("ticketer_type"),
                name=body.get("name"),
                project_uuid=body.get("project_uuid"),
                user_email=body.get("user_email"),
                uuid=body.get("uuid"),
            )

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[TicketerConsumer] - Message rejected by: {exception}")
            return None

        message.channel.basic_ack(message.delivery_tag)
