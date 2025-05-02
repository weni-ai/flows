from dataclasses import asdict, dataclass

import amqp
from sentry_sdk import capture_exception
from weni_datalake_sdk.clients.client import send_message_template_status_data
from weni_datalake_sdk.paths.message_template_status_path import MessageTemplateStatusPath

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers import JSONParser


@dataclass
class MessageTemplateWebhookDTO:
    status: str
    language: str
    template_id: str
    message_id: str
    data: dict


class MessageTemplateWebhookConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[MessageTemplateWebhookConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            message_template_webhook_dto = MessageTemplateWebhookDTO(
                status=body.get("status"),
                language=body.get("language"),
                template_id=body.get("template_id"),
                message_id=body.get("message_id"),
                data=body,
            )

            # Add data to lake
            send_message_template_status_data(MessageTemplateStatusPath, asdict(message_template_webhook_dto))

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[MessageTemplateWebhookConsumer] - Message rejected by: {exception}")
