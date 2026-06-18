from dataclasses import asdict, dataclass

import amqp
from sentry_sdk import capture_exception
from weni_datalake_sdk.clients.client import send_message_template_status_data_async
from weni_datalake_sdk.paths.message_template_status_path import MessageTemplateStatusPath
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser


@dataclass
class MessageTemplateWebhookDTO:  # pragma: no cover
    contact_urn: str
    status: str
    message_id: str
    template_type: str
    channel: str
    data: dict


class MessageTemplateWebhookConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)
            message_template_webhook_dto = MessageTemplateWebhookDTO(
                contact_urn=body.get("contact_urn"),
                status=body.get("status"),
                template_type=body.get("template_type"),
                channel=body.get("channel_uuid"),
                message_id=body.get("message_id"),
                data=body,
            )

            send_message_template_status_data_async(MessageTemplateStatusPath, asdict(message_template_webhook_dto))

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise
