"""
SQS Consumer Management Command.

Starts an SQS consumer to process messages from a specified queue.

Usage:
    python manage.py sqsconsume --queue broadcasts
    python manage.py sqsconsume --queue broadcasts --region us-east-1
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Start an SQS consumer for processing messages from a queue"

    # Available queue configurations
    # Maps queue names to their settings keys and consumer handlers
    QUEUE_CONFIG = {
        "broadcasts": {
            "url_setting": "SQS_BROADCAST_QUEUE_URL",
            "handler": "temba.sqs.handle.handle_broadcast_messages",
        },
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--queue",
            dest="queue_name",
            required=True,
            choices=self.QUEUE_CONFIG.keys(),
            help="Name of the queue to consume from (e.g., broadcasts)",
        )
        parser.add_argument(
            "--region",
            dest="region",
            default=None,
            help="AWS region (defaults to SQS_AWS_REGION setting or us-east-1)",
        )
        parser.add_argument(
            "--wait-time",
            dest="wait_time",
            type=int,
            default=20,
            help="Long polling wait time in seconds (1-20, default: 20)",
        )
        parser.add_argument(
            "--max-messages",
            dest="max_messages",
            type=int,
            default=10,
            help="Maximum messages to receive per poll (1-10, default: 10)",
        )
        parser.add_argument(
            "--visibility-timeout",
            dest="visibility_timeout",
            type=int,
            default=30,
            help="Message visibility timeout in seconds (default: 30)",
        )

    def handle(self, *args, **options):
        queue_name = options["queue_name"]
        region = options["region"] or getattr(settings, "SQS_AWS_REGION", "us-east-1")
        wait_time = options["wait_time"]
        max_messages = options["max_messages"]
        visibility_timeout = options["visibility_timeout"]

        # Validate options
        if not 1 <= wait_time <= 20:
            raise CommandError("wait-time must be between 1 and 20")
        if not 1 <= max_messages <= 10:
            raise CommandError("max-messages must be between 1 and 10")

        # Get queue configuration
        config = self.QUEUE_CONFIG.get(queue_name)
        if not config:
            raise CommandError(f"Unknown queue: {queue_name}")

        # Get queue URL from settings
        queue_url = getattr(settings, config["url_setting"], None)
        if not queue_url:
            raise CommandError(f"Queue URL not configured. Set {config['url_setting']} in settings.")

        # Import the handler
        try:
            handler_function = import_string(config["handler"])
        except ImportError as e:
            raise CommandError(f"Failed to import handler: {e}")

        # Import and create backend
        from temba.sqs.backends import SQSConnectionBackend

        backend = SQSConnectionBackend(
            consumer_handler=handler_function,
            region_name=region,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting SQS consumer for '{queue_name}' queue\n"
                f"  Queue URL: {queue_url}\n"
                f"  Region: {region}\n"
                f"  Wait time: {wait_time}s\n"
                f"  Max messages: {max_messages}\n"
                f"  Visibility timeout: {visibility_timeout}s"
            )
        )

        try:
            backend.start_consuming(
                queue_url=queue_url,
                wait_time_seconds=wait_time,
                max_messages=max_messages,
                visibility_timeout=visibility_timeout,
            )
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nShutting down..."))
        except Exception as e:
            raise CommandError(f"Consumer failed: {e}")

        self.stdout.write(self.style.SUCCESS("SQS consumer stopped"))
