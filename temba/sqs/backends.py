"""
SQS Connection Backend.

Provides the infrastructure to connect to SQS and poll for messages.
Supports parallel processing with configurable thread pool.
"""

import json
import logging
import signal
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Callable

import boto3
from botocore.exceptions import ClientError

from django.conf import settings

from temba.sqs.exceptions import SQSConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class MessageTask:
    """Represents a message being processed."""

    message_id: str
    receipt_handle: str
    body: dict[str, Any]
    future: Future | None = None


class SQSConnectionBackend:
    """
    SQS connection backend with long polling and parallel processing.

    Features:
        - Long polling for efficient message retrieval
        - Parallel message processing with ThreadPoolExecutor
        - Configurable thread count via SQS_CONSUMER_THREADS setting
        - Graceful shutdown (waits for in-flight messages)
        - Backpressure (waits for batch completion before fetching more)

    Example:
        ```python
        from temba.sqs.backends import SQSConnectionBackend

        def handler(message: dict) -> bool:
            # Process message
            return True  # Delete on success

        backend = SQSConnectionBackend(handler)
        backend.start_consuming(queue_url, region="us-east-1")
        ```

    Configuration (settings.py):
        SQS_CONSUMER_THREADS = 10  # Number of parallel processing threads
        SQS_CONSUMER_TASK_TIMEOUT = 120  # Max seconds per message
    """

    # Default polling configuration
    DEFAULT_WAIT_TIME_SECONDS = 20  # Long polling (max 20s)
    DEFAULT_MAX_MESSAGES = 10  # Max messages per poll (SQS limit)
    DEFAULT_VISIBILITY_TIMEOUT = 120  # Seconds before message becomes visible again
    DEFAULT_THREAD_COUNT = 10  # Default parallel threads
    DEFAULT_TASK_TIMEOUT = 120  # Max seconds to wait for a single task
    ERROR_BACKOFF_SECONDS = 5  # Backoff on errors
    SHUTDOWN_TIMEOUT_SECONDS = 60  # Max time to wait for graceful shutdown

    def __init__(
        self,
        consumer_handler: Callable[[dict[str, Any]], bool],
        region_name: str = "us-east-1",
        thread_count: int | None = None,
    ):
        """
        Initialize the SQS connection backend.

        Args:
            consumer_handler: A callable that processes messages.
                Should return True on success (delete message) or False on failure.
            region_name: AWS region for the SQS client.
            thread_count: Number of parallel threads. Defaults to SQS_CONSUMER_THREADS
                setting or DEFAULT_THREAD_COUNT.
        """
        self.consumer_handler = consumer_handler
        self.region_name = region_name
        self._client = None
        self._running = False
        self._executor: ThreadPoolExecutor | None = None
        self._shutting_down = False

        # Get thread count from settings or parameter
        self.thread_count = thread_count or getattr(settings, "SQS_CONSUMER_THREADS", self.DEFAULT_THREAD_COUNT)

        # Get task timeout from settings
        self.task_timeout = getattr(settings, "SQS_CONSUMER_TASK_TIMEOUT", self.DEFAULT_TASK_TIMEOUT)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    @property
    def client(self):
        """Lazy-loaded SQS client."""
        if self._client is None:
            self._client = boto3.client("sqs", region_name=self.region_name)
        return self._client

    def _signal_handler(self, signum, frame):
        """
        Handle shutdown signals gracefully.

        Sets flags to stop polling and wait for in-flight messages.
        """
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self._running = False
        self._shutting_down = True

    def start_consuming(
        self,
        queue_url: str,
        wait_time_seconds: int = DEFAULT_WAIT_TIME_SECONDS,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        visibility_timeout: int | None = None,
    ) -> None:
        """
        Start consuming messages from the SQS queue.

        Uses long polling and parallel processing for high throughput.
        Implements backpressure by waiting for batch completion before fetching more.

        Args:
            queue_url: The URL of the SQS queue to consume from.
            wait_time_seconds: Long polling wait time (1-20 seconds).
            max_messages: Maximum messages to receive per poll (1-10).
            visibility_timeout: How long a message is hidden after being received.
                Defaults to task_timeout + buffer.
        """
        if not queue_url:
            raise SQSConfigurationError("Queue URL is required")

        # Set visibility timeout to be longer than task timeout
        if visibility_timeout is None:
            visibility_timeout = self.task_timeout + 30

        self._running = True
        logger.info(f"Starting SQS consumer for queue: {queue_url}")
        logger.info(
            f"Config: threads={self.thread_count}, wait_time={wait_time_seconds}s, "
            f"max_messages={max_messages}, visibility_timeout={visibility_timeout}s, "
            f"task_timeout={self.task_timeout}s"
        )

        # Create thread pool for parallel processing
        with ThreadPoolExecutor(
            max_workers=self.thread_count,
            thread_name_prefix="sqs-worker",
        ) as executor:
            self._executor = executor

            while self._running:
                try:
                    self._poll_and_process_parallel(
                        queue_url=queue_url,
                        wait_time_seconds=wait_time_seconds,
                        max_messages=max_messages,
                        visibility_timeout=visibility_timeout,
                        executor=executor,
                    )
                except ClientError as e:
                    logger.error(f"SQS client error: {e}", exc_info=True)
                    self._backoff()
                except Exception as e:
                    logger.error(f"Unexpected error in consumer loop: {e}", exc_info=True)
                    self._backoff()

            # Graceful shutdown: wait for in-flight tasks
            if self._shutting_down:
                logger.info("Waiting for in-flight messages to complete...")
                executor.shutdown(wait=True)
                logger.info("All in-flight messages processed")

        self._executor = None
        logger.info("SQS consumer stopped")

    def _poll_and_process_parallel(
        self,
        queue_url: str,
        wait_time_seconds: int,
        max_messages: int,
        visibility_timeout: int,
        executor: ThreadPoolExecutor,
    ) -> None:
        """
        Poll the queue and process messages in parallel.

        Implements backpressure by waiting for all messages in a batch
        to complete before fetching more.

        Args:
            queue_url: The SQS queue URL.
            wait_time_seconds: Long polling wait time.
            max_messages: Maximum messages per poll.
            visibility_timeout: Message visibility timeout.
            executor: The thread pool executor.
        """
        response = self.client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time_seconds,
            VisibilityTimeout=visibility_timeout,
            MessageAttributeNames=["All"],
            AttributeNames=["All"],
        )

        messages = response.get("Messages", [])

        if not messages:
            logger.debug("No messages received")
            return

        logger.info(f"Received {len(messages)} message(s), processing in parallel...")

        # Prepare message tasks
        tasks: list[MessageTask] = []
        for message in messages:
            try:
                body = json.loads(message.get("Body", "{}"))
                task = MessageTask(
                    message_id=message.get("MessageId", "unknown"),
                    receipt_handle=message.get("ReceiptHandle", ""),
                    body=body,
                )
                tasks.append(task)
            except json.JSONDecodeError as e:
                message_id = message.get("MessageId", "unknown")
                logger.error(f"Failed to parse message {message_id}: {e}")
                # Delete invalid JSON messages
                self._delete_message(
                    queue_url,
                    message.get("ReceiptHandle", ""),
                    message_id,
                )

        if not tasks:
            return

        # Submit all tasks to the thread pool
        for task in tasks:
            task.future = executor.submit(
                self._process_message_task,
                queue_url,
                task,
            )

        # BACKPRESSURE: Wait for all tasks to complete before fetching more
        # This prevents memory buildup when DB is slow
        completed = 0
        failed = 0
        for task in tasks:
            if task.future is None:
                continue
            try:
                task.future.result(timeout=self.task_timeout)
                completed += 1
            except FuturesTimeoutError:
                logger.error(f"Message {task.message_id} timed out after {self.task_timeout}s")
                failed += 1
            except Exception as e:
                logger.error(f"Message {task.message_id} failed: {e}")
                failed += 1

        logger.info(f"Batch complete: {completed} succeeded, {failed} failed")

    def _process_message_task(self, queue_url: str, task: MessageTask) -> bool:
        """
        Process a single message task (runs in thread pool).

        Args:
            queue_url: The SQS queue URL.
            task: The message task to process.

        Returns:
            True if processed successfully, False otherwise.
        """
        try:
            logger.debug(f"Processing message {task.message_id}")

            # Call the consumer handler
            success = self.consumer_handler(task.body)

            if success:
                # Delete the message on success
                self._delete_message(queue_url, task.receipt_handle, task.message_id)
                return True
            else:
                logger.warning(f"Message {task.message_id} processing returned failure")
                # Message will become visible again after visibility timeout
                return False

        except Exception as e:
            logger.error(
                f"Error processing message {task.message_id}: {e}",
                exc_info=True,
            )
            # Message will become visible again after visibility timeout
            return False

    def _delete_message(self, queue_url: str, receipt_handle: str, message_id: str) -> None:
        """
        Delete a message from the queue.

        Args:
            queue_url: The SQS queue URL.
            receipt_handle: The receipt handle for the message.
            message_id: The message ID (for logging).
        """
        try:
            self.client.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.debug(f"Message {message_id} deleted successfully")
        except ClientError as e:
            logger.error(f"Failed to delete message {message_id}: {e}")

    def _backoff(self) -> None:
        """Sleep before retrying after an error."""
        if self._running:
            logger.info(f"Backing off for {self.ERROR_BACKOFF_SECONDS}s...")
            time.sleep(self.ERROR_BACKOFF_SECONDS)

    def stop(self) -> None:
        """Stop the consumer gracefully."""
        logger.info("Stopping SQS consumer...")
        self._running = False
        self._shutting_down = True
