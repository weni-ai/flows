from weni.eda.channels import Channel  # pragma: no cover

from .consumers.channel_migrated_consumer import ChannelMigratedConsumer  # pragma: no cover


def handle_amq_consumers(channel: Channel) -> None:  # pragma: no cover
    channel.basic_consume(
        "flows.channels.migrated",
        callback=ChannelMigratedConsumer().handle,
    )
