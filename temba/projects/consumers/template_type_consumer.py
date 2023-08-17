import amqp
from django.conf import settings

from temba.projects.models import TemplateType



class TemplateTypeConsumer:
    def __init__(self) -> None:
        self.__host = settings.EDA_BROKER_HOST
        self.__port = 5672
        self.__username = "guest"
        self.__password = "guest"
        self.__exchange = "template_type"
        self.__routing_key = "template_type"
        self.__channel = self.__create_channel()

    @staticmethod
    def consume(message: amqp.Message):
        notification = message.body

        print(f"[TemplateTypeConsumer] - Consuming a message. Body: {notification}")
        uuid = notification.get("uuid")
        name = notification.get("name")
        setup = notification.get("setup")
        
        TemplateType.objects.create(
            uuid=uuid,
            name=name,
            setup=setup
        )

        message.channel.basic_ack(message.delivery_tag)
