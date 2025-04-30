from dataclasses import dataclass, asdict
import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers import JSONParser

from weni_datalake_sdk.clients.client import send_message_template_data
from weni_datalake_sdk.paths.message_template_path import MessageTemplatePath


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
                contact_urn=body.get("contact_urn"),
                channel=body.get("channel_uuid"),
                language=body.get("language"),
                template_id=body.get("template_id"),
                template_type=body.get("template_type"),
                template_name=body.get("template_name"),
                message_id=body.get("message_id"),
                direction=body.get("direction"),
                template_variables=body.get("template_variables"),
                text=body.get("text"),
                data=body,
            )

            # Add data to lake
            send_message_template_data(MessageTemplatePath, asdict(message_template_dto))

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[MessageTemplateConsumer] - Message rejected by: {exception}")

    