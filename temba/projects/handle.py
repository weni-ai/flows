import amqp

from .consumers import (  # pragma: no cover
    ProjectConsumer,
    TemplateTypeConsumer,
    UpdateBrainOnConsumer,
    UpdatePermissionConsumer,
    UpdateProjectConsumer,
)


def handle_consumers(channel: amqp.Channel):
    channel.basic_consume("flows.template-types", callback=TemplateTypeConsumer().handle)
    channel.basic_consume("flows.projects", callback=ProjectConsumer().handle)
    channel.basic_consume("flows.update-project", callback=UpdateProjectConsumer().handle)  # pragma: no cover
    channel.basic_consume("recent-activity.flows", callback=UpdateBrainOnConsumer().handle)  # pragma: no cover
    channel.basic_consume("flows.update-permission", callback=UpdatePermissionConsumer().handle)
