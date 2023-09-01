from amqp.channel import Channel

from temba.classifiers.consumers.classifier_consumer import ClassifierConsumer


def handle_consumers(channel: Channel) -> None:
    channel.basic_consume("flows.classifiers", callback=ClassifierConsumer().handle)
