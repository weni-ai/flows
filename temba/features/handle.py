import amqp

from .consumers import IntegrateFeatureTemplateConsumer  # pragma: no cover


def handle_consumers(channel: amqp.Channel):
    channel.basic_consume("flows.integrate-feature-template", callback=IntegrateFeatureTemplateConsumer().handle)
