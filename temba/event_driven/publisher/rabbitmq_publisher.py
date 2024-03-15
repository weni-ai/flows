import json
from time import sleep
from typing import Dict

from pika import BasicProperties
from pika.exceptions import StreamLostError

from django.conf import settings

from temba.event_driven.connection.rabbitmq_connection import RabbitMQConnection


class RabbitmqPublisher:  # pragma: no cover
    def __init__(self) -> None:
        self.rabbitmq_connection = RabbitMQConnection()

    def send_message(self, body: Dict, exchange: str, routing_key: str):
        sended = False
        while not sended:
            try:
                self.rabbitmq_connection.channel.basic_publish(
                    exchange=exchange,
                    routing_key=routing_key,
                    body=json.dumps(body),
                    properties=BasicProperties(delivery_mode=2),
                )
                sended = True
            except StreamLostError:
                self.rabbitmq_connection.make_connection()
            except Exception:
                self.rabbitmq_connection.make_connection()
            if not sended:
                sleep(settings.EDA_WAIT_TIME_RETRY)
