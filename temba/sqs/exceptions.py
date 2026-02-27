"""
SQS Consumer Exceptions.
"""


class SQSConsumerError(Exception):
    """Base exception for SQS consumer errors."""

    pass


class SQSConfigurationError(SQSConsumerError):
    """Raised when SQS configuration is invalid or missing."""

    pass


class SQSProcessingError(SQSConsumerError):
    """Raised when message processing fails."""

    pass
