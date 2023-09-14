from amqp.channel import Channel

from temba.tickets.consumers.ticketer_consumer import TicketConsumer


def handle_consumers(channel: Channel) -> None:
    channel.basic_consume("flows.ticketers", callback=TicketConsumer().handle)
