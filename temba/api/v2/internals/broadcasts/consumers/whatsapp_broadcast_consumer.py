"""
WhatsApp Broadcast Consumer.

Processes WhatsApp broadcast messages from SQS queue sent by agents-toolkit.
"""

import logging
from typing import Any

from sentry_sdk import capture_exception

from django.contrib.auth import get_user_model
from django.db import transaction

from temba.api.v2.serializers import WhatsappBroadcastWriteSerializer
from temba.orgs.models import Org
from temba.sqs.consumers import SQSConsumer
from temba.sqs.exceptions import SQSProcessingError

logger = logging.getLogger(__name__)

User = get_user_model()


class WhatsappBroadcastConsumer(SQSConsumer):
    """
    Consumer for processing WhatsApp broadcast messages from SQS.

    Receives messages from agents-toolkit via SQS and creates broadcasts
    using the existing WhatsappBroadcastWriteSerializer.

    Expected message format:
        {
            "msg": {
                "text": "Hello!",
                // or other message content
            },
            "flows_url": "https://flows.weni.ai",
            "urns": ["whatsapp:5511999999999"],
            "jwt_token": "eyJ...",  // optional
            "project_uuid": "abc-123-def"
        }
    """

    def consume(self, message: dict[str, Any]) -> None:
        """
        Process a WhatsApp broadcast message.

        Args:
            message: The SQS message payload.

        Raises:
            SQSProcessingError: If the message is invalid or processing fails.
        """
        logger.info(f"[WhatsappBroadcastConsumer] Processing message")
        logger.debug(f"[WhatsappBroadcastConsumer] Message content: {message}")

        # Extract required fields
        msg_payload = message.get("msg")
        project_uuid = message.get("project_uuid")
        urns = message.get("urns", [])
        jwt_token = message.get("jwt_token")

        # Validate required fields
        if not msg_payload:
            raise SQSProcessingError("Missing required field: msg")

        if not project_uuid:
            raise SQSProcessingError("Missing required field: project_uuid")

        if not urns:
            raise SQSProcessingError("Missing required field: urns")

        # Get the organization
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            raise SQSProcessingError(f"Organization not found for project_uuid: {project_uuid}")

        # Get or create user from JWT email
        user = self._get_user(message, jwt_token)

        # Build request data for the serializer
        request_data = {
            "urns": urns,
            "msg": msg_payload,
        }

        # Add optional fields
        if message.get("contacts"):
            request_data["contacts"] = message["contacts"]
        if message.get("groups"):
            request_data["groups"] = message["groups"]
        if message.get("channel"):
            request_data["channel"] = message["channel"]
        if message.get("queue"):
            request_data["queue"] = message["queue"]
        if message.get("name"):
            request_data["name"] = message["name"]

        # Process with serializer
        self._create_broadcast(request_data, org, user)

        logger.info(f"[WhatsappBroadcastConsumer] Broadcast created successfully for org={org.id}, " f"urns={urns}")

    def _get_user(self, message: dict[str, Any], jwt_token: str | None) -> User:
        """
        Get or create a user for the broadcast.

        Tries to extract email from JWT payload in the message,
        falls back to a system user if not available.

        Args:
            message: The full message payload.
            jwt_token: The JWT token (if present).

        Returns:
            The user to associate with the broadcast.
        """
        # Try to get email from message
        email = message.get("user_email")

        # If no email and we have a JWT, try to decode it
        if not email and jwt_token:
            email = self._extract_email_from_jwt(jwt_token)

        if not email:
            # Use a system user for automated broadcasts
            email = "agent-toolkit@weni.ai"
            logger.debug(f"[WhatsappBroadcastConsumer] Using system user: {email}")

        user, created = User.objects.get_or_create(
            email=email,
            defaults={"username": email},
        )

        if created:
            logger.info(f"[WhatsappBroadcastConsumer] Created user: {email}")

        return user

    def _extract_email_from_jwt(self, jwt_token: str) -> str | None:
        """
        Extract email from JWT token payload.

        Note: This does a simple decode without verification since
        the token was already validated by the Lambda/agents-toolkit.

        Args:
            jwt_token: The JWT token string.

        Returns:
            The email from the token or None.
        """
        try:
            import base64
            import json

            # Split the JWT and decode the payload (middle part)
            parts = jwt_token.split(".")
            if len(parts) != 3:
                return None

            # Add padding if needed
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding

            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return payload.get("email") or payload.get("user_email")

        except Exception as e:
            logger.warning(f"[WhatsappBroadcastConsumer] Failed to decode JWT: {e}")
            return None

    @transaction.atomic
    def _create_broadcast(self, request_data: dict[str, Any], org: Org, user: User) -> None:
        """
        Create the broadcast using the serializer.

        Args:
            request_data: The data for the serializer.
            org: The organization.
            user: The user creating the broadcast.

        Raises:
            SQSProcessingError: If validation fails.
        """
        serializer = WhatsappBroadcastWriteSerializer(
            data=request_data,
            context={"org": org, "user": user},
        )

        if not serializer.is_valid():
            errors = serializer.errors
            logger.error(
                f"[WhatsappBroadcastConsumer] Validation failed: {errors}",
                extra={"request_data": request_data, "errors": errors},
            )
            raise SQSProcessingError(f"Broadcast validation failed: {errors}")

        # Save the broadcast (this also triggers send_async)
        broadcast = serializer.save()
        logger.info(f"[WhatsappBroadcastConsumer] Broadcast {broadcast.id} created and queued")

    def on_error(self, message: dict[str, Any], error: Exception) -> None:
        """
        Handle errors during message processing.

        Args:
            message: The message that failed.
            error: The exception raised.
        """
        logger.error(
            f"[WhatsappBroadcastConsumer] Error processing message: {error}",
            exc_info=True,
            extra={
                "project_uuid": message.get("project_uuid"),
                "urns": message.get("urns"),
            },
        )
        capture_exception(error)
