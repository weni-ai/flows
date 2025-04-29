from dataclasses import dataclass
import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers import JSONParser


@dataclass
class MessageTemplateDTO:
    contact_urn: str
    channel: str
    language: str
    template_id: str
    template_type: str
    template_name: str
    message_id: str
    direction: str
    template_variables: list
    text: str
    data: dict


class MessageTemplateConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[MessageTemplateConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            message_template_dto = MessageTemplateDTO(
                contact_urn=body.get("uuid"),
                channel=body.get("name"),
                language=body.get("is_template"),
                template_id=body.get("date_format"),
                template_type=body.get("template_type_uuid"),
                template_name=body.get("timezone"),
                message_id=body.get("description"),
                direction=body.get("brain_on", False),
                template_variables=body.get("brain_on", False),
                text=body.get("brain_on", False),
                data=body,
            )

            # Add data to lake
            # send_message_template_data(MessageTemplatePath, message_template_dto)

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[MessageTemplateConsumer] - Message rejected by: {exception}")
