from dataclasses import asdict, dataclass
import logging

import amqp
from sentry_sdk import capture_exception
from weni_datalake_sdk.clients.client import send_message_template_data_async
from weni_datalake_sdk.paths.message_template_path import MessageTemplatePath
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

logger = logging.getLogger(__name__)


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
            logger.info("[MessageTemplateConsumer] Received message")
            body = JSONParser.parse(message.body)
            logger.info(
                "[MessageTemplateConsumer] Processing message_id=%s template_uuid=%s channel=%s",
                body.get("message_id"),
                body.get("template_uuid"),
                body.get("channel_uuid"),
            )
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
            logger.info(
                "[MessageTemplateConsumer] Message processed successfully message_id=%s",
                body.get("message_id"),
            )
        except Exception as exception:
            logger.exception("[MessageTemplateConsumer] Failed to process message")
            capture_exception(exception)
            raise
