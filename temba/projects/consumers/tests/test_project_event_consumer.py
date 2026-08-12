import json
import uuid
from unittest.mock import Mock, patch

import pytz
from weni.eda.messages import Message

from django.conf import settings

from temba.orgs.models import Org
from temba.projects.consumers.project_event_consumer import ProjectEventConsumer
from temba.tests.base import TembaTest


class TestProjectEventConsumer(TembaTest):
    def setUp(self):
        super().setUp()
        self.consumer = ProjectEventConsumer()
        self.test_org = Org.objects.create(
            name="Test Org",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            proj_uuid=uuid.uuid4(),
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Test description"},
            language="en-us",
            is_active=True,
        )
        self.project_uuid = str(self.test_org.proj_uuid)

    def _create_message(self, body_dict):
        """Build a weni.eda Message without going through handle() (avoids close_old_connections)."""
        channel = Mock()
        message = Message(
            body=json.dumps(body_dict, default=str).encode(),
            delivery_tag="test-delivery-tag",
            channel=channel,
        )
        # Required so consumer.ack() can delegate to the channel
        self.consumer._message = message
        return message, channel

    def test_consume_update_action_successfully(self):
        """Test consuming an update action message"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "Updated Org Name",
            "description": "Updated description",
            "language": "pt-br",
            "timezone": "America/Sao_Paulo",
        }
        message, channel = self._create_message(body)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertEqual(reloaded_org.name, "Updated Org Name")
        self.assertEqual(reloaded_org.config["description"], "Updated description")
        self.assertEqual(reloaded_org.language, "pt-br")
        self.assertEqual(reloaded_org.timezone, pytz.timezone("America/Sao_Paulo"))

    def test_consume_update_action_when_usecase_returns_none_acknowledges(self):
        """update_project_config may return None; consumer still acks."""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "Any Name",
        }
        message, channel = self._create_message(body)

        with patch(
            "temba.projects.consumers.project_event_consumer.update_project_config",
            return_value=None,
        ):
            self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)
        channel.basic_reject.assert_not_called()

    def test_consume_delete_action_successfully(self):
        """Test consuming a delete action message"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "deleted",
        }
        message, channel = self._create_message(body)

        self.assertTrue(self.test_org.is_active)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_active)
        self.assertIsNotNone(reloaded_org.released_on)

    def test_consume_status_updated_action_successfully(self):
        """Test consuming a status_updated action message"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "INACTIVE",
        }
        message, channel = self._create_message(body)

        self.assertTrue(self.test_org.is_active)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertTrue(reloaded_org.is_suspended)
        self.assertTrue(reloaded_org.is_active)

    def test_consume_status_updated_to_active(self):
        """Test consuming a status_updated action to ACTIVE"""
        self.test_org.is_suspended = True
        self.test_org.save()

        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "ACTIVE",
        }
        message, channel = self._create_message(body)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_suspended)
        self.assertTrue(reloaded_org.is_active)

    def test_consume_project_type_update_action_successfully(self):
        """Test consuming a project_type_update action message"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "project_type_update",
            "is_multi_agents": True,
        }
        message, channel = self._create_message(body)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertTrue(reloaded_org.config.get("is_multi_agents"))

    def test_consume_project_type_update_when_usecase_returns_none_acknowledges(self):
        """update_project_type may return None; consumer still acks."""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "project_type_update",
            "is_multi_agents": True,
        }
        message, channel = self._create_message(body)

        with patch(
            "temba.projects.consumers.project_event_consumer.update_project_type",
            return_value=None,
        ):
            self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)
        channel.basic_reject.assert_not_called()

    def test_consume_status_updated_to_in_test(self):
        """Test consuming a status_updated action to IN_TEST"""
        self.test_org.is_suspended = True
        self.test_org.save()

        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "IN_TEST",
        }
        message, channel = self._create_message(body)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_suspended)
        self.assertTrue(reloaded_org.is_active)

    def test_consume_missing_project_uuid_raises(self):
        """Test that missing project_uuid raises and is captured"""
        body = {
            "user_email": self.user.email,
            "action": "updated",
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(ValueError):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_missing_action_raises(self):
        """Test that missing action raises and is captured"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(ValueError):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_missing_user_email_raises(self):
        """Test that missing user_email raises and is captured"""
        body = {
            "project_uuid": self.project_uuid,
            "action": "updated",
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(ValueError):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_invalid_action_raises(self):
        """Test that invalid action raises and is captured"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "invalid_action",
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(ValueError):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_status_updated_missing_status_raises(self):
        """Test that status_updated action without status field raises"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(ValueError):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_status_updated_invalid_status_raises(self):
        """Test that status_updated action with invalid status raises"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "INVALID_STATUS",
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(ValueError):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_nonexistent_project_for_update_raises(self):
        """Test that updating a non-existent project raises Org.DoesNotExist"""
        fake_uuid = str(uuid.uuid4())
        body = {
            "project_uuid": fake_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "New Name",
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(Org.DoesNotExist):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_nonexistent_project_for_delete_acknowledges(self):
        """Test that deleting a non-existent project still acknowledges the message"""
        fake_uuid = str(uuid.uuid4())
        body = {
            "project_uuid": fake_uuid,
            "user_email": self.user.email,
            "action": "deleted",
        }
        message, channel = self._create_message(body)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)
        channel.basic_reject.assert_not_called()

    def test_consume_nonexistent_project_for_status_update_acknowledges(self):
        """Test that status updating a non-existent project still acknowledges the message"""
        fake_uuid = str(uuid.uuid4())
        body = {
            "project_uuid": fake_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "ACTIVE",
        }
        message, channel = self._create_message(body)

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)
        channel.basic_reject.assert_not_called()

    def test_consume_update_partial_fields(self):
        """Test updating only some fields"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "Only Name Updated",
        }
        message, channel = self._create_message(body)

        original_description = self.test_org.config["description"]
        original_language = self.test_org.language

        self.consumer.consume(message)

        channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertEqual(reloaded_org.name, "Only Name Updated")
        self.assertEqual(reloaded_org.config["description"], original_description)
        self.assertEqual(reloaded_org.language, original_language)

    def test_consume_invalid_json_raises(self):
        """Test that invalid JSON in message body raises and is captured"""
        channel = Mock()
        message = Message(body=b"invalid json {{", delivery_tag="test-delivery-tag", channel=channel)
        self.consumer._message = message

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            with self.assertRaises(Exception):
                self.consumer.consume(message)

            channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_validate_message_with_all_valid_actions(self):
        """Test _validate_message with all valid actions"""
        valid_actions = ["deleted", "updated", "status_updated", "project_type_update"]

        for action in valid_actions:
            body = {
                "project_uuid": self.project_uuid,
                "user_email": self.user.email,
                "action": action,
            }

            if action == "status_updated":
                body["status"] = "ACTIVE"

            try:
                self.consumer._validate_message(body)
            except ValueError:
                self.fail(f"_validate_message raised ValueError for valid action: {action}")

    def test_validate_message_with_all_valid_statuses(self):
        """Test _validate_message with all valid statuses for status_updated"""
        valid_statuses = ["ACTIVE", "IN_TEST", "INACTIVE"]

        for status in valid_statuses:
            body = {
                "project_uuid": self.project_uuid,
                "user_email": self.user.email,
                "action": "status_updated",
                "status": status,
            }

            try:
                self.consumer._validate_message(body)
            except ValueError:
                self.fail(f"_validate_message raised ValueError for valid status: {status}")

    def test_process_event_unknown_action_raises_value_error(self):
        """Unhandled action string hits the final else (not reachable via consume + _validate_message)."""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
        }
        with self.assertRaisesRegex(ValueError, "Unknown action: future_action"):
            self.consumer._process_event(
                self.project_uuid,
                self.user.email,
                "future_action",
                body,
            )

    def test_process_event_with_exception_in_usecase_raises(self):
        """Test that exceptions in usecases are captured and re-raised"""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "New Name",
        }
        message, channel = self._create_message(body)

        with patch("temba.projects.consumers.project_event_consumer.update_project_config") as mock_update:
            mock_update.side_effect = Exception("Database error")

            with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
                with self.assertRaises(Exception):
                    self.consumer.consume(message)

                channel.basic_ack.assert_not_called()
                mock_capture.assert_called_once()
