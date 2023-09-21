from amqp.channel import Channel  # pragma: no cover

from temba.tickets.consumers.ticketer_consumer import TicketConsumer  # pragma: no cover


def handle_consumers(channel: Channel) -> None:  # pragma: no cover
    channel.basic_consume("flows.ticketers", callback=TicketConsumer().handle)
