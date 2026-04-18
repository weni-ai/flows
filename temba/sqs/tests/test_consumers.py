"""
Tests for SQS Consumer base class.
"""

from unittest.mock import patch

from django.test import TestCase

from temba.sqs.consumers import SQSConsumer


class TestSQSConsumer(SQSConsumer):
    """Concrete implementation for testing."""

    def __init__(self):
        self.consumed_messages = []
        self.should_raise = False
        self.raise_exception = Exception("Test error")

    def consume(self, message):
        if self.should_raise:
            raise self.raise_exception
        self.consumed_messages.append(message)


class SQSConsumerTests(TestCase):
    """Tests for SQSConsumer base class."""

    def test_handle_success(self):
        """Test successful message handling."""
        consumer = TestSQSConsumer()
        message = {"data": "test"}

        result = consumer.handle(message)

        self.assertTrue(result)
        self.assertEqual(consumer.consumed_messages, [message])

    def test_handle_failure(self):
        """Test message handling with error."""
        consumer = TestSQSConsumer()
        consumer.should_raise = True
        message = {"data": "test"}

        with patch.object(consumer, "on_error") as mock_on_error:
            result = consumer.handle(message)

            self.assertFalse(result)
            mock_on_error.assert_called_once()
            args = mock_on_error.call_args[0]
            self.assertEqual(args[0], message)
            self.assertIsInstance(args[1], Exception)

    @patch("temba.sqs.consumers.message_started")
    @patch("temba.sqs.consumers.message_finished")
    def test_signals_emitted(self, mock_finished, mock_started):
        """Test that signals are emitted."""
        consumer = TestSQSConsumer()
        message = {"data": "test"}

        consumer.handle(message)

        mock_started.send.assert_called_once_with(sender=TestSQSConsumer)
        mock_finished.send.assert_called_once_with(sender=TestSQSConsumer)

    @patch("temba.sqs.consumers.message_started")
    @patch("temba.sqs.consumers.message_finished")
    def test_signals_emitted_on_error(self, mock_finished, mock_started):
        """Test that signals are emitted even on error."""
        consumer = TestSQSConsumer()
        consumer.should_raise = True
        message = {"data": "test"}

        with patch.object(consumer, "on_error"):
            consumer.handle(message)

        mock_started.send.assert_called_once()
        mock_finished.send.assert_called_once()

    @patch("temba.sqs.consumers.capture_exception")
    @patch("temba.sqs.consumers.logger")
    def test_on_error_logs_and_captures(self, mock_logger, mock_capture):
        """Test default error handling."""
        consumer = TestSQSConsumer()
        message = {"data": "test"}
        error = Exception("Test error")

        consumer.on_error(message, error)

        mock_logger.error.assert_called_once()
        mock_capture.assert_called_once_with(error)
