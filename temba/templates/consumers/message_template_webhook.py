import logging
from dataclasses import asdict, dataclass

from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message
from weni_datalake_sdk.clients.client import send_message_template_status_data_async
from weni_datalake_sdk.paths.message_template_status_path import MessageTemplateStatusPath

logger = logging.getLogger(__name__)


@dataclass
class MessageTemplateWebhookDTO:  # pragma: no cover
    contact_urn: str
    status: str
    message_id: str
    template_type: str
    channel: str
    data: dict


class MessageTemplateWebhookConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            logger.info("[MessageTemplateWebhookConsumer] Received message")
            body = message.json()
            logger.info(
                "[MessageTemplateWebhookConsumer] Processing message_id=%s status=%s channel=%s",
                body.get("message_id"),
                body.get("status"),
                body.get("channel_uuid"),
            )
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
            logger.info(
                "[MessageTemplateWebhookConsumer] Message processed successfully message_id=%s",
                body.get("message_id"),
            )
        except Exception as exception:
            logger.exception("[MessageTemplateWebhookConsumer] Failed to process message")
            capture_exception(exception)
            raise
