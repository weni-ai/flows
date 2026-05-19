import amqp

from .consumers import MsgConsumer


def handle_consumers(channel: amqp.Channel):
    channel.basic_consume("flows.msgs", callback=MsgConsumer().handle)
