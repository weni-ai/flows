import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.projects.usecases.update_brain_on import update_project_brain_on


class UpdateBrainOnConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[UpdateBrainOnConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            update_project_brain_on(
                project_uuid=body.get("project_uuid"),
                brain_on=body.get("brain_on"),
                user_email=body.get("user"),
            )

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[UpdateBrainOnConsumer] - Message rejected by: {exception}")
