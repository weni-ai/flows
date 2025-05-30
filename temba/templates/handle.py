import amqp

from temba.templates.consumers.message_template_consumer import MessageTemplateConsumer
from temba.templates.consumers.message_template_webhook import MessageTemplateWebhookConsumer


def handle_consumers(channel: amqp.Channel):
    channel.basic_consume("flows.message-template", callback=MessageTemplateConsumer().handle)  # pragma: no cover
    channel.basic_consume(
        "flows.message-template-webhook", callback=MessageTemplateWebhookConsumer().handle
    )  # pragma: no cover
