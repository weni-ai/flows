import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers.json_parser import JSONParser
from temba.projects.usecases.template_type_creation import create_template_type


class TemplateTypeConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[TemplateTypeConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            create_template_type(uuid=body.get("uuid"), name=body.get("name"), project_uuid=body.get("project_uuid"))

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[TemplateTypeConsumer] - Message rejected by: {exception}")
