"""
Tests for WhatsApp Broadcast Consumer.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from temba.api.v2.internals.broadcasts.consumers import WhatsappBroadcastConsumer
from temba.sqs.exceptions import SQSProcessingError
from temba.tests import TembaTest

User = get_user_model()


class WhatsappBroadcastConsumerUnitTests(TestCase):
    """Unit tests for WhatsappBroadcastConsumer (no DB)."""

    def setUp(self):
        self.consumer = WhatsappBroadcastConsumer()

    def test_extract_email_from_jwt_valid(self):
        """Test extracting email from valid JWT."""
        # This is a fake JWT with email in payload
        # Header: {"alg": "HS256", "typ": "JWT"}
        # Payload: {"email": "test@example.com", "sub": "123"}
        jwt_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJzdWIiOiIxMjMifQ.signature"
        )

        email = self.consumer._extract_email_from_jwt(jwt_token)

        self.assertEqual(email, "test@example.com")

    def test_extract_email_from_jwt_user_email_field(self):
        """Test extracting user_email from JWT."""
        # Payload: {"user_email": "user@example.com", "sub": "123"}
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2VtYWlsIjoidXNlckBleGFtcGxlLmNvbSIsInN1YiI6IjEyMyJ9.signature"

        email = self.consumer._extract_email_from_jwt(jwt_token)

        self.assertEqual(email, "user@example.com")

    def test_extract_email_from_jwt_invalid(self):
        """Test handling invalid JWT."""
        email = self.consumer._extract_email_from_jwt("invalid-token")

        self.assertIsNone(email)

    def test_extract_email_from_jwt_no_email(self):
        """Test JWT without email field."""
        # Payload: {"sub": "123"}
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.signature"

        email = self.consumer._extract_email_from_jwt(jwt_token)

        self.assertIsNone(email)

    def test_consume_missing_msg_raises(self):
        """Test that missing msg field raises error."""
        message = {
            "project_uuid": "proj-123",
            "urns": ["whatsapp:5511999999999"],
        }

        with self.assertRaises(SQSProcessingError) as ctx:
            self.consumer.consume(message)

        self.assertIn("msg", str(ctx.exception))

    def test_consume_missing_project_uuid_raises(self):
        """Test that missing project_uuid raises error."""
        message = {
            "msg": {"text": "Hello"},
            "urns": ["whatsapp:5511999999999"],
        }

        with self.assertRaises(SQSProcessingError) as ctx:
            self.consumer.consume(message)

        self.assertIn("project_uuid", str(ctx.exception))

    def test_consume_missing_urns_raises(self):
        """Test that missing urns raises error."""
        message = {
            "msg": {"text": "Hello"},
            "project_uuid": "proj-123",
        }

        with self.assertRaises(SQSProcessingError) as ctx:
            self.consumer.consume(message)

        self.assertIn("urns", str(ctx.exception))


class WhatsappBroadcastConsumerIntegrationTests(TembaTest):
    """Integration tests for WhatsappBroadcastConsumer (with DB)."""

    def setUp(self):
        super().setUp()
        self.consumer = WhatsappBroadcastConsumer()

    def test_consume_org_not_found(self):
        """Test that non-existent org raises error."""
        message = {
            "msg": {"text": "Hello"},
            "project_uuid": "non-existent-uuid",
            "urns": ["whatsapp:5511999999999"],
        }

        with self.assertRaises(SQSProcessingError) as ctx:
            self.consumer.consume(message)

        self.assertIn("Organization not found", str(ctx.exception))

    @patch("temba.api.v2.internals.broadcasts.consumers.whatsapp_broadcast_consumer.WhatsappBroadcastWriteSerializer")
    def test_consume_success(self, mock_serializer_class):
        """Test successful message consumption."""
        # Setup mock serializer
        mock_serializer = MagicMock()
        mock_serializer.is_valid.return_value = True
        mock_serializer.save.return_value = MagicMock(id=123)
        mock_serializer_class.return_value = mock_serializer

        message = {
            "msg": {"text": "Hello World!"},
            "project_uuid": str(self.org.proj_uuid),
            "urns": ["whatsapp:5511999999999"],
            "jwt_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20ifQ.sig",
        }

        # Should not raise
        self.consumer.consume(message)

        # Serializer should be called with correct data
        mock_serializer_class.assert_called_once()
        call_kwargs = mock_serializer_class.call_args
        self.assertEqual(call_kwargs.kwargs["data"]["urns"], ["whatsapp:5511999999999"])
        self.assertEqual(call_kwargs.kwargs["data"]["msg"], {"text": "Hello World!"})
        self.assertEqual(call_kwargs.kwargs["context"]["org"], self.org)

        # Save should be called
        mock_serializer.save.assert_called_once()

    @patch("temba.api.v2.internals.broadcasts.consumers.whatsapp_broadcast_consumer.WhatsappBroadcastWriteSerializer")
    def test_consume_validation_error(self, mock_serializer_class):
        """Test handling of validation errors."""
        mock_serializer = MagicMock()
        mock_serializer.is_valid.return_value = False
        mock_serializer.errors = {"msg": ["Invalid message format"]}
        mock_serializer_class.return_value = mock_serializer

        message = {
            "msg": {"invalid": "data"},
            "project_uuid": str(self.org.proj_uuid),
            "urns": ["whatsapp:5511999999999"],
        }

        with self.assertRaises(SQSProcessingError) as ctx:
            self.consumer.consume(message)

        self.assertIn("validation failed", str(ctx.exception).lower())

    def test_get_user_creates_system_user(self):
        """Test that system user is created when no email available."""
        message = {}

        user = self.consumer._get_user(message, None)

        self.assertEqual(user.email, "agent-toolkit@weni.ai")

    def test_get_user_from_message_email(self):
        """Test user creation from message email field."""
        message = {"user_email": "from-message@example.com"}

        user = self.consumer._get_user(message, None)

        self.assertEqual(user.email, "from-message@example.com")

    def test_get_user_from_jwt(self):
        """Test user extraction from JWT."""
        message = {}
        # JWT with email: "jwt-user@example.com"
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Imp3dC11c2VyQGV4YW1wbGUuY29tIn0.signature"

        user = self.consumer._get_user(message, jwt_token)

        self.assertEqual(user.email, "jwt-user@example.com")
