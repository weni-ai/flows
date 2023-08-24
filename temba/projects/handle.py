import amqp

from .consumers import TemplateTypeConsumer, ProjectConsumer

def handle_consumers(channel: amqp.Channel):
    channel.basic_consume("flows.template-types", callback=TemplateTypeConsumer.consume)
    channel.basic_consume("flows.projects", callback=ProjectConsumer.consume)
