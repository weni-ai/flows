"""
SQS Consumer Infrastructure.

This module provides the base infrastructure for consuming messages from AWS SQS queues.
It follows a similar pattern to the existing EDA (Event Driven Architecture) consumers
but is designed specifically for SQS.
"""

from temba.sqs.consumers import SQSConsumer
from temba.sqs.exceptions import SQSConfigurationError, SQSConsumerError

__all__ = [
    "SQSConsumer",
    "SQSConsumerError",
    "SQSConfigurationError",
]
