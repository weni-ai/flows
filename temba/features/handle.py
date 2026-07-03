from weni.eda.channels import Channel  # pragma: no cover

from .consumers import IntegrateFeatureTemplateConsumer  # pragma: no cover


def handle_consumers(channel: Channel):  # pragma: no cover
    channel.basic_consume("flows.integrate-feature-template", callback=IntegrateFeatureTemplateConsumer().handle)
