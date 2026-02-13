"""
SQS Consumer Signals.

Similar to EDA signals, these can be used for monitoring, logging,
or other cross-cutting concerns.
"""

from django.dispatch import Signal

# Sent when a message starts being processed
message_started = Signal()

# Sent when a message finishes processing (success or failure)
message_finished = Signal()
