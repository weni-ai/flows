from amqp.channel import Channel  # pragma: no cover

from .consumers.classifier_consumer import ClassifierConsumer  # pragma: no cover


def handle_consumers(channel: Channel) -> None:  # pragma: no cover
    channel.basic_consume("flows.classifiers", callback=ClassifierConsumer().handle)
