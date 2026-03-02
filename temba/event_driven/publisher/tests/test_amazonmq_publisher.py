from unittest import TestCase
from unittest.mock import MagicMock, patch

import pika.exceptions

from temba.event_driven.publisher.amazonmq_publisher import _RECOVERABLE_ERRORS, AmazonMQPublisher


class AmazonMQPublisherTestCase(TestCase):
    """Unit tests for AmazonMQPublisher – no broker needed."""

    @patch("temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory")
    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher")
    def test_send_message_delegates_to_pika_publisher(self, MockPikaPublisher, _MockFactory):
        publisher = AmazonMQPublisher()
        publisher.send_message(body={"key": "value"}, exchange="test.topic", routing_key="rk")

        inner = MockPikaPublisher.return_value
        inner.send_message.assert_called_once_with(
            body={"key": "value"},
            exchange="test.topic",
            routing_key="rk",
        )

    @patch("temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory")
    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher")
    def test_lazy_init_creates_publisher_on_first_call(self, MockPikaPublisher, _MockFactory):
        publisher = AmazonMQPublisher()

        self.assertIsNone(publisher._publisher)
        MockPikaPublisher.assert_not_called()

        publisher.send_message(body={}, exchange="x", routing_key="r")

        MockPikaPublisher.assert_called_once()
        self.assertIsNotNone(publisher._publisher)

    @patch("temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory")
    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher")
    def test_lazy_init_reuses_publisher_on_subsequent_calls(self, MockPikaPublisher, _MockFactory):
        publisher = AmazonMQPublisher()

        publisher.send_message(body={}, exchange="x", routing_key="r")
        publisher.send_message(body={}, exchange="x", routing_key="r")

        MockPikaPublisher.assert_called_once()

    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaConnection")
    @patch("temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory")
    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher")
    def test_retry_on_stale_connection(self, MockPikaPublisher, _MockFactory, MockPikaConnection):
        inner = MockPikaPublisher.return_value
        inner.send_message.side_effect = [
            pika.exceptions.StreamLostError(),
            None,
        ]

        publisher = AmazonMQPublisher()
        publisher.send_message(body={"msg": "hi"}, exchange="x", routing_key="r")

        self.assertEqual(inner.send_message.call_count, 2)

    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaConnection")
    @patch("temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory")
    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher")
    def test_reset_connection_called_on_error(self, MockPikaPublisher, _MockFactory, MockPikaConnection):
        inner = MockPikaPublisher.return_value
        inner.send_message.side_effect = [
            pika.exceptions.AMQPConnectionError(),
            None,
        ]
        MockPikaConnection.connection = MagicMock(is_closed=False)

        publisher = AmazonMQPublisher()
        publisher.send_message(body={}, exchange="x", routing_key="r")

        self.assertIsNone(MockPikaConnection.connection)

    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaConnection")
    @patch("temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory")
    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher")
    def test_raises_after_all_retries_exhausted(self, MockPikaPublisher, _MockFactory, MockPikaConnection):
        inner = MockPikaPublisher.return_value
        inner.send_message.side_effect = pika.exceptions.StreamLostError()

        publisher = AmazonMQPublisher()

        with self.assertRaises(pika.exceptions.StreamLostError):
            publisher.send_message(body={}, exchange="x", routing_key="r")

        self.assertEqual(inner.send_message.call_count, 1 + AmazonMQPublisher.MAX_RETRIES)

    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaConnection")
    @patch("temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory")
    @patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher")
    def test_non_recoverable_error_raises_immediately(self, MockPikaPublisher, _MockFactory, MockPikaConnection):
        inner = MockPikaPublisher.return_value
        inner.send_message.side_effect = ValueError("unexpected")

        publisher = AmazonMQPublisher()

        with self.assertRaises(ValueError):
            publisher.send_message(body={}, exchange="x", routing_key="r")

        inner.send_message.assert_called_once()

    def test_all_recoverable_errors_are_caught(self):
        for exc_class in _RECOVERABLE_ERRORS:
            with self.subTest(exc=exc_class.__name__):
                with patch("temba.event_driven.publisher.amazonmq_publisher.PikaEDAPublisher") as MockPub, patch(
                    "temba.event_driven.publisher.amazonmq_publisher.AmazonMQConnectionFactory"
                ), patch("temba.event_driven.publisher.amazonmq_publisher.PikaConnection"):
                    inner = MockPub.return_value
                    inner.send_message.side_effect = [exc_class(), None]

                    publisher = AmazonMQPublisher()
                    publisher.send_message(body={}, exchange="x", routing_key="r")

                    self.assertEqual(inner.send_message.call_count, 2)
