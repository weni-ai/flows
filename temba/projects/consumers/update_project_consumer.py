import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.projects.usecases.project_update import update_project_config


class UpdateProjectConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[UpdateProjectConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            update_project_config(project_uuid=body.get("project_uuid"), description=body.get("description"))

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[UpdateProjectConsumer] - Message rejected by: {exception}")
