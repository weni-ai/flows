from abc import ABC, abstractmethod  # pragma: no cover

import amqp  # pragma: no cover

from .signals import message_finished, message_started  # pragma: no cover


class EDAConsumer(ABC):  # pragma: no cover
    def handle(self, message: amqp.Message):
        message_started.send(sender=self)
        try:
            self.consume(message)
        finally:
            message_finished.send(sender=self)

    @abstractmethod
    def consume(self, message: amqp.Message):
        pass
