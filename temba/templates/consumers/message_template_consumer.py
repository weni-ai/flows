from dataclasses import asdict, dataclass

import amqp
from sentry_sdk import capture_exception
from weni_datalake_sdk.clients.client import send_message_template_data_async
from weni_datalake_sdk.paths.message_template_path import MessageTemplatePath
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser


@dataclass
class MessageTemplateDTO:  # pragma: no cover
    contact_urn: str
    channel: str
    template_language: str
    template_name: str
    template_uuid: str
    message_id: str
    message_date: str
    direction: str
    template_variables: list
    text: str
    data: dict


class MessageTemplateConsumer(EDAConsumer):  # pragma: no cover
    def consume(self, message: amqp.Message):
        try:
            body = JSONParser.parse(message.body)
            message_template_dto = MessageTemplateDTO(
                contact_urn=body.get("contact_urn"),
                channel=body.get("channel_uuid"),
                template_language=body.get("template_language"),
                template_name=body.get("template_name"),
                template_uuid=body.get("template_uuid"),
                message_id=body.get("message_id"),
                message_date=body.get("message_date"),
                direction=body.get("direction"),
                template_variables=body.get("template_variables"),
                text=body.get("text"),
                data=body,
            )

            send_message_template_data_async(MessageTemplatePath, asdict(message_template_dto))

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
