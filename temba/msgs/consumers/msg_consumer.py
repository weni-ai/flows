import amqp
from sentry_sdk import capture_exception
from weni_datalake_sdk.clients.client import send_data
from weni_datalake_sdk.paths import MsgPath

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers import JSONParser


class MsgConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        print(f"[MsgConsumer] - Consuming a message. Body: {message.body}")
        try:
            body = JSONParser.parse(message.body)
            data = dict(body)
            send_data(MsgPath, data)

            message.channel.basic_ack(message.delivery_tag)

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[MsgConsumer] - Message rejected by: {exception}")
