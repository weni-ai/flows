import json
import uuid
from unittest.mock import MagicMock, Mock, patch

import pytz
from weni.internal.models import Project

from django.conf import settings

from temba.projects.consumers.project_event_consumer import ProjectEventConsumer
from temba.tests.base import TembaTest


class TestProjectEventConsumer(TembaTest):
    def setUp(self):
        super().setUp()
        self.consumer = ProjectEventConsumer()
        self.project = Project.objects.create(
            project_uuid=str(uuid.uuid4()),
            name="Test Project",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
            config={"description": "Test description"},
            language="en-us",
            is_active=True,
        )

    def _create_mock_message(self, body_dict):
        """Helper to create a mock AMQP message"""
        message = Mock()
        message.body = json.dumps(body_dict)
        message.channel = Mock()
        message.delivery_tag = "test-delivery-tag"
        return message

    def test_consume_update_action_successfully(self):
        """Test consuming an update action message"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "Updated Project Name",
            "description": "Updated description",
            "language": "pt-br",
        }
        message = self._create_mock_message(body)

        self.consumer.consume(message)

        # Verify message was acknowledged
        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)

        # Verify project was updated
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertEqual(reloaded_project.name, "Updated Project Name")
        self.assertEqual(reloaded_project.config["description"], "Updated description")
        self.assertEqual(reloaded_project.language, "pt-br")

    def test_consume_delete_action_successfully(self):
        """Test consuming a delete action message"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "deleted",
        }
        message = self._create_mock_message(body)

        self.assertTrue(self.project.is_active)

        self.consumer.consume(message)

        # Verify message was acknowledged
        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)

        # Verify project was deleted (soft delete)
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertFalse(reloaded_project.is_active)
        self.assertIsNotNone(reloaded_project.released_on)

    def test_consume_status_updated_action_successfully(self):
        """Test consuming a status_updated action message"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "INACTIVE",
        }
        message = self._create_mock_message(body)

        self.assertTrue(self.project.is_active)

        self.consumer.consume(message)

        # Verify message was acknowledged
        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)

        # Verify project status was updated
        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertFalse(reloaded_project.is_active)

    def test_consume_status_updated_to_active(self):
        """Test consuming a status_updated action to ACTIVE"""
        self.project.is_active = False
        self.project.save()

        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "ACTIVE",
        }
        message = self._create_mock_message(body)

        self.consumer.consume(message)

        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertTrue(reloaded_project.is_active)

    def test_consume_status_updated_to_in_test(self):
        """Test consuming a status_updated action to IN_TEST"""
        self.project.is_active = False
        self.project.save()

        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "IN_TEST",
        }
        message = self._create_mock_message(body)

        self.consumer.consume(message)

        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertTrue(reloaded_project.is_active)

    def test_consume_missing_project_uuid_rejects_message(self):
        """Test that missing project_uuid causes message rejection"""
        body = {
            "user_email": self.user.email,
            "action": "updated",
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            # Verify message was rejected
            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            message.channel.basic_ack.assert_not_called()
            
            # Verify exception was captured
            mock_capture.assert_called_once()

    def test_consume_missing_action_rejects_message(self):
        """Test that missing action causes message rejection"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            message.channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_missing_user_email_rejects_message(self):
        """Test that missing user_email causes message rejection"""
        body = {
            "project_uuid": self.project.project_uuid,
            "action": "updated",
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            message.channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_invalid_action_rejects_message(self):
        """Test that invalid action causes message rejection"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "invalid_action",
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            message.channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_status_updated_missing_status_rejects_message(self):
        """Test that status_updated action without status field rejects message"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            # Missing "status" field
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            message.channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_status_updated_invalid_status_rejects_message(self):
        """Test that status_updated action with invalid status rejects message"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "INVALID_STATUS",
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            message.channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_consume_nonexistent_project_for_update_acknowledges(self):
        """Test that updating a non-existent project still acknowledges the message"""
        fake_uuid = str(uuid.uuid4())
        body = {
            "project_uuid": fake_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "New Name",
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            # Should reject because Org.DoesNotExist is raised
            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            mock_capture.assert_called_once()

    def test_consume_nonexistent_project_for_delete_acknowledges(self):
        """Test that deleting a non-existent project still acknowledges the message"""
        fake_uuid = str(uuid.uuid4())
        body = {
            "project_uuid": fake_uuid,
            "user_email": self.user.email,
            "action": "deleted",
        }
        message = self._create_mock_message(body)

        self.consumer.consume(message)

        # Should acknowledge even though project doesn't exist
        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)
        message.channel.basic_reject.assert_not_called()

    def test_consume_nonexistent_project_for_status_update_acknowledges(self):
        """Test that status updating a non-existent project still acknowledges the message"""
        fake_uuid = str(uuid.uuid4())
        body = {
            "project_uuid": fake_uuid,
            "user_email": self.user.email,
            "action": "status_updated",
            "status": "ACTIVE",
        }
        message = self._create_mock_message(body)

        self.consumer.consume(message)

        # Should acknowledge even though project doesn't exist
        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)
        message.channel.basic_reject.assert_not_called()

    def test_consume_update_partial_fields(self):
        """Test updating only some fields"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "Only Name Updated",
            # description and language not provided
        }
        message = self._create_mock_message(body)

        original_description = self.project.config["description"]
        original_language = self.project.language

        self.consumer.consume(message)

        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)

        reloaded_project = Project.objects.get(project_uuid=self.project.project_uuid)
        self.assertEqual(reloaded_project.name, "Only Name Updated")
        self.assertEqual(reloaded_project.config["description"], original_description)
        self.assertEqual(reloaded_project.language, original_language)

    def test_consume_invalid_json_rejects_message(self):
        """Test that invalid JSON in message body causes rejection"""
        message = Mock()
        message.body = "invalid json {{"
        message.channel = Mock()
        message.delivery_tag = "test-delivery-tag"

        with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
            self.consumer.consume(message)

            message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
            message.channel.basic_ack.assert_not_called()
            mock_capture.assert_called_once()

    def test_validate_message_with_all_valid_actions(self):
        """Test _validate_message with all valid actions"""
        valid_actions = ["deleted", "updated", "status_updated"]

        for action in valid_actions:
            body = {
                "project_uuid": self.project.project_uuid,
                "user_email": self.user.email,
                "action": action,
            }
            
            if action == "status_updated":
                body["status"] = "ACTIVE"

            # Should not raise any exception
            try:
                self.consumer._validate_message(body)
            except ValueError:
                self.fail(f"_validate_message raised ValueError for valid action: {action}")

    def test_validate_message_with_all_valid_statuses(self):
        """Test _validate_message with all valid statuses for status_updated"""
        valid_statuses = ["ACTIVE", "IN_TEST", "INACTIVE"]

        for status in valid_statuses:
            body = {
                "project_uuid": self.project.project_uuid,
                "user_email": self.user.email,
                "action": "status_updated",
                "status": status,
            }

            # Should not raise any exception
            try:
                self.consumer._validate_message(body)
            except ValueError:
                self.fail(f"_validate_message raised ValueError for valid status: {status}")

    def test_process_event_with_exception_in_usecase_rejects_message(self):
        """Test that exceptions in usecases are properly handled"""
        body = {
            "project_uuid": self.project.project_uuid,
            "user_email": self.user.email,
            "action": "updated",
            "name": "New Name",
        }
        message = self._create_mock_message(body)

        with patch("temba.projects.consumers.project_event_consumer.update_project_config") as mock_update:
            mock_update.side_effect = Exception("Database error")
            
            with patch("temba.projects.consumers.project_event_consumer.capture_exception") as mock_capture:
                self.consumer.consume(message)

                message.channel.basic_reject.assert_called_once_with(message.delivery_tag, requeue=False)
                message.channel.basic_ack.assert_not_called()
                mock_capture.assert_called_once()
