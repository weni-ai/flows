"""
Tests for SQS Connection Backend.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from temba.sqs.backends import MessageTask, SQSConnectionBackend
from temba.sqs.exceptions import SQSConfigurationError


class SQSConnectionBackendTests(TestCase):
    """Tests for SQSConnectionBackend."""

    def setUp(self):
        self.handler = MagicMock(return_value=True)
        self.backend = SQSConnectionBackend(
            consumer_handler=self.handler,
            region_name="us-east-1",
            thread_count=2,  # Use fewer threads for tests
        )

    def test_init(self):
        """Test backend initialization."""
        self.assertEqual(self.backend.consumer_handler, self.handler)
        self.assertEqual(self.backend.region_name, "us-east-1")
        self.assertEqual(self.backend.thread_count, 2)
        self.assertFalse(self.backend._running)

    def test_init_default_thread_count(self):
        """Test default thread count from settings."""
        with override_settings(SQS_CONSUMER_THREADS=5):
            backend = SQSConnectionBackend(
                consumer_handler=self.handler,
                region_name="us-east-1",
            )
            self.assertEqual(backend.thread_count, 5)

    @patch("temba.sqs.backends.boto3")
    def test_lazy_client_creation(self, mock_boto3):
        """Test that SQS client is created lazily."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        # Client should not be created yet
        mock_boto3.client.assert_not_called()

        # Access the client
        client = self.backend.client

        mock_boto3.client.assert_called_once_with("sqs", region_name="us-east-1")
        self.assertEqual(client, mock_client)

    def test_start_consuming_empty_url_raises(self):
        """Test that empty queue URL raises error."""
        with self.assertRaises(SQSConfigurationError):
            self.backend.start_consuming(queue_url="")

    @patch("temba.sqs.backends.boto3")
    def test_process_message_task_success(self, mock_boto3):
        """Test successful message task processing."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        self.backend._client = mock_client

        queue_url = "https://sqs.us-east-1.amazonaws.com/123/queue"
        task = MessageTask(
            message_id="msg-123",
            receipt_handle="receipt-123",
            body={"data": "test"},
        )

        result = self.backend._process_message_task(queue_url, task)

        self.assertTrue(result)
        self.handler.assert_called_once_with({"data": "test"})
        mock_client.delete_message.assert_called_once_with(
            QueueUrl=queue_url,
            ReceiptHandle="receipt-123",
        )

    @patch("temba.sqs.backends.boto3")
    def test_process_message_task_failure_no_delete(self, mock_boto3):
        """Test that failed message tasks are not deleted."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        self.backend._client = mock_client

        # Handler returns False (failure)
        self.handler.return_value = False

        queue_url = "https://sqs.us-east-1.amazonaws.com/123/queue"
        task = MessageTask(
            message_id="msg-123",
            receipt_handle="receipt-123",
            body={"data": "test"},
        )

        result = self.backend._process_message_task(queue_url, task)

        self.assertFalse(result)
        self.handler.assert_called_once()
        mock_client.delete_message.assert_not_called()

    @patch("temba.sqs.backends.boto3")
    def test_process_message_task_exception_no_delete(self, mock_boto3):
        """Test that exceptions don't delete messages."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        self.backend._client = mock_client

        # Handler raises exception
        self.handler.side_effect = Exception("DB error")

        queue_url = "https://sqs/queue"
        task = MessageTask(
            message_id="msg-123",
            receipt_handle="receipt-123",
            body={"data": "test"},
        )

        result = self.backend._process_message_task(queue_url, task)

        self.assertFalse(result)
        mock_client.delete_message.assert_not_called()

    @patch("temba.sqs.backends.boto3")
    def test_poll_and_process_parallel_empty_queue(self, mock_boto3):
        """Test polling an empty queue."""
        mock_client = MagicMock()
        mock_client.receive_message.return_value = {"Messages": []}
        mock_boto3.client.return_value = mock_client
        self.backend._client = mock_client

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.backend._poll_and_process_parallel(
                queue_url="https://sqs/queue",
                wait_time_seconds=20,
                max_messages=10,
                visibility_timeout=30,
                executor=executor,
            )

        mock_client.receive_message.assert_called_once()
        self.handler.assert_not_called()

    @patch("temba.sqs.backends.boto3")
    def test_poll_and_process_parallel_with_messages(self, mock_boto3):
        """Test parallel processing of messages."""
        mock_client = MagicMock()
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "msg-1",
                    "ReceiptHandle": "receipt-1",
                    "Body": json.dumps({"data": "test1"}),
                },
                {
                    "MessageId": "msg-2",
                    "ReceiptHandle": "receipt-2",
                    "Body": json.dumps({"data": "test2"}),
                },
            ]
        }
        mock_boto3.client.return_value = mock_client
        self.backend._client = mock_client

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.backend._poll_and_process_parallel(
                queue_url="https://sqs/queue",
                wait_time_seconds=20,
                max_messages=10,
                visibility_timeout=30,
                executor=executor,
            )

        # Handler should be called for each message
        self.assertEqual(self.handler.call_count, 2)

        # Both messages should be deleted (handler returned True)
        self.assertEqual(mock_client.delete_message.call_count, 2)

    @patch("temba.sqs.backends.boto3")
    def test_poll_and_process_parallel_invalid_json_deleted(self, mock_boto3):
        """Test that invalid JSON messages are deleted."""
        mock_client = MagicMock()
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "msg-1",
                    "ReceiptHandle": "receipt-1",
                    "Body": "not valid json",
                },
            ]
        }
        mock_boto3.client.return_value = mock_client
        self.backend._client = mock_client

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.backend._poll_and_process_parallel(
                queue_url="https://sqs/queue",
                wait_time_seconds=20,
                max_messages=10,
                visibility_timeout=30,
                executor=executor,
            )

        # Handler should NOT be called (invalid JSON)
        self.handler.assert_not_called()

        # Message should be deleted to avoid infinite retry
        mock_client.delete_message.assert_called_once()

    def test_stop(self):
        """Test graceful stop."""
        self.backend._running = True

        self.backend.stop()

        self.assertFalse(self.backend._running)
        self.assertTrue(self.backend._shutting_down)

    def test_signal_handler(self):
        """Test signal handler stops consumer."""
        self.backend._running = True

        self.backend._signal_handler(2, None)

        self.assertFalse(self.backend._running)
        self.assertTrue(self.backend._shutting_down)

    def test_message_task_dataclass(self):
        """Test MessageTask dataclass."""
        task = MessageTask(
            message_id="msg-123",
            receipt_handle="receipt-123",
            body={"key": "value"},
        )

        self.assertEqual(task.message_id, "msg-123")
        self.assertEqual(task.receipt_handle, "receipt-123")
        self.assertEqual(task.body, {"key": "value"})
        self.assertIsNone(task.future)
