import amqp
from .consumers import TemplateTypeConsumer

def handle_consumers(channel: amqp.Channel):
    channel.basic_consume("flows.template-types", callback=TemplateTypeConsumer.consume)
