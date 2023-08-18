import amqp

from temba.event_driven.parsers.json_parser import JSONParser
from temba.projects.usecases.template_type_creation import create_template_type

class TemplateTypeConsumer:
    @staticmethod
    def consume(message: amqp.Message):
        body = JSONParser.parse(message.body)
        print(f"[TemplateTypeConsumer] - Consuming a message. Body: {body}")
        create_template_type(uuid=body.get("uuid"), name=body.get("name"), project_uuid=body.get("project_uuid"))

        message.channel.basic_ack(message.delivery_tag)
