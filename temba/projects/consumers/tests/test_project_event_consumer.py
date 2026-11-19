import uuid
from unittest.mock import patch

import pytz

from django.conf import settings
from django.db import DatabaseError
from django.test import override_settings

from temba.orgs.models import Org
from temba.projects.consumers.project_event_consumer import ProjectEventConsumer
from temba.tests.base import TembaTest

from .helpers import assert_acked, assert_rejected, handle

CAPTURE_EXCEPTION = "temba.projects.consumers.project_events.capture_exception"
WENI_EDA_LOGGER = "weni.eda.django.consumers.consumer"

# action, extra body fields, use case name in the consumer module
LEGACY_ACTIONS = [
    ("updated", {"name": "New Name"}, "update_project_config"),
    ("status_updated", {"status": "INACTIVE"}, "update_project_status"),
    ("project_type_update", {"is_multi_agents": True}, "update_project_type"),
    ("deleted", {}, "delete_project"),
]


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

    def _body(self, action, **fields) -> dict:
        return {"project_uuid": self.project_uuid, "user_email": self.user.email, "action": action, **fields}

    def _assert_rejected_and_reported(self, body):
        with patch(CAPTURE_EXCEPTION) as mock_capture:
            channel = handle(self.consumer, body)

        assert_rejected(channel)
        mock_capture.assert_called_once()

    def test_consume_update_action_successfully(self):
        """Test consuming an update action message"""
        body = self._body(
            "updated",
            name="Updated Org Name",
            description="Updated description",
            language="pt-br",
            timezone="America/Sao_Paulo",
        )

        with self.assertLogs("temba.projects", level="INFO") as logs:
            channel = handle(self.consumer, body)

        assert_acked(channel)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertEqual(reloaded_org.name, "Updated Org Name")
        self.assertEqual(reloaded_org.config["description"], "Updated description")
        self.assertEqual(reloaded_org.language, "pt-br")
        self.assertEqual(reloaded_org.timezone, pytz.timezone("America/Sao_Paulo"))
        self.assertEqual(
            logs.output[0],
            "INFO:temba.projects.consumers.project_event_consumer:project_event_consumed "
            f"action=updated project_uuid={self.project_uuid}",
        )

    def test_consume_update_action_when_usecase_returns_none_acknowledges(self):
        """update_project_config may return None; consumer still acks."""
        with patch(
            "temba.projects.consumers.project_event_consumer.update_project_config",
            return_value=None,
        ):
            channel = handle(self.consumer, self._body("updated", name="Any Name"))

        assert_acked(channel)

    def test_consume_delete_action_successfully(self):
        """Test consuming a delete action message"""
        self.assertTrue(self.test_org.is_active)

        channel = handle(self.consumer, self._body("deleted"))

        assert_acked(channel)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_active)
        self.assertIsNotNone(reloaded_org.released_on)

    def test_consume_delete_action_twice_keeps_released_on(self):
        assert_acked(handle(self.consumer, self._body("deleted")))
        released_on = Org.objects.get(id=self.test_org.id).released_on

        channel = handle(self.consumer, self._body("deleted", user_email="another@example.com"))

        assert_acked(channel)
        self.assertEqual(Org.objects.get(id=self.test_org.id).released_on, released_on)

    def test_consume_status_updated_action_successfully(self):
        """Test consuming a status_updated action message"""
        channel = handle(self.consumer, self._body("status_updated", status="INACTIVE"))

        assert_acked(channel)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertTrue(reloaded_org.is_suspended)
        self.assertTrue(reloaded_org.is_active)

    def test_consume_status_updated_to_active(self):
        """Test consuming a status_updated action to ACTIVE"""
        self.test_org.is_suspended = True
        self.test_org.save()

        channel = handle(self.consumer, self._body("status_updated", status="ACTIVE"))

        assert_acked(channel)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_suspended)
        self.assertTrue(reloaded_org.is_active)

    def test_consume_project_type_update_action_successfully(self):
        """Test consuming a project_type_update action message"""
        channel = handle(self.consumer, self._body("project_type_update", is_multi_agents=True))

        assert_acked(channel)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertTrue(reloaded_org.config.get("is_multi_agents"))

    def test_consume_project_type_update_when_usecase_returns_none_acknowledges(self):
        """update_project_type may return None; consumer still acks."""
        with patch(
            "temba.projects.consumers.project_event_consumer.update_project_type",
            return_value=None,
        ):
            channel = handle(self.consumer, self._body("project_type_update", is_multi_agents=True))

        assert_acked(channel)

    def test_consume_status_updated_to_in_test(self):
        """Test consuming a status_updated action to IN_TEST"""
        self.test_org.is_suspended = True
        self.test_org.save()

        channel = handle(self.consumer, self._body("status_updated", status="IN_TEST"))

        assert_acked(channel)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertFalse(reloaded_org.is_suspended)
        self.assertTrue(reloaded_org.is_active)

    def test_consume_missing_project_uuid_raises(self):
        """Test that missing project_uuid is rejected and captured"""
        self._assert_rejected_and_reported({"user_email": self.user.email, "action": "updated"})

    def test_consume_missing_action_raises(self):
        """Test that missing action is rejected and captured"""
        self._assert_rejected_and_reported({"project_uuid": self.project_uuid, "user_email": self.user.email})

    def test_consume_missing_user_email_raises(self):
        """Test that missing user_email is rejected and captured"""
        self._assert_rejected_and_reported({"project_uuid": self.project_uuid, "action": "updated"})

    def test_consume_invalid_action_raises(self):
        """Test that invalid action is rejected and captured"""
        self._assert_rejected_and_reported(self._body("invalid_action"))

    def test_consume_status_updated_missing_status_raises(self):
        """Test that status_updated action without status field is rejected"""
        self._assert_rejected_and_reported(self._body("status_updated"))

    def test_consume_status_updated_invalid_status_raises(self):
        """Test that status_updated action with invalid status is rejected"""
        self._assert_rejected_and_reported(self._body("status_updated", status="INVALID_STATUS"))

    def test_consume_nonexistent_project_for_update_raises(self):
        """Test that updating a non-existent project is rejected"""
        fake_uuid = str(uuid.uuid4())

        with patch("temba.projects.consumers.project_event_consumer.report_exception") as mock_report:
            with self.assertLogs(WENI_EDA_LOGGER, level="ERROR") as eda_logs:
                channel = handle(self.consumer, self._body("updated", project_uuid=fake_uuid, name="New Name"))

        assert_rejected(channel)
        exception, context = mock_report.call_args.args
        self.assertIsInstance(exception, Org.DoesNotExist)
        self.assertEqual(context.project_uuid, fake_uuid)
        self.assertIsNone(context.org_id)
        self.assertIn(
            f"project event rejected: action=updated project_uuid={fake_uuid} reason=DoesNotExist",
            eda_logs.output[0],
        )

    def test_consume_nonexistent_project_for_delete_acknowledges(self):
        """Test that deleting a non-existent project still acknowledges the message"""
        channel = handle(self.consumer, self._body("deleted", project_uuid=str(uuid.uuid4())))

        assert_acked(channel)

    def test_consume_nonexistent_project_for_status_update_acknowledges(self):
        """Test that status updating a non-existent project still acknowledges the message"""
        channel = handle(self.consumer, self._body("status_updated", project_uuid=str(uuid.uuid4()), status="ACTIVE"))

        assert_acked(channel)

    def test_consume_update_partial_fields(self):
        """Test updating only some fields"""
        original_description = self.test_org.config["description"]
        original_language = self.test_org.language

        channel = handle(self.consumer, self._body("updated", name="Only Name Updated"))

        assert_acked(channel)
        reloaded_org = Org.objects.get(proj_uuid=self.project_uuid)
        self.assertEqual(reloaded_org.name, "Only Name Updated")
        self.assertEqual(reloaded_org.config["description"], original_description)
        self.assertEqual(reloaded_org.language, original_language)

    def test_consume_invalid_json_raises(self):
        """Test that invalid JSON in message body is rejected and captured"""
        self._assert_rejected_and_reported(b"invalid json {{")

    def test_non_uuid_project_uuid_is_never_logged_nor_tagged(self):
        unsafe = "abc project_uuid=forged"

        for action, extra, use_case in LEGACY_ACTIONS:
            with self.subTest(action=action):
                with patch("temba.projects.consumers.project_event_consumer.report_exception") as mock_report:
                    with self.assertLogs("temba.projects", level="INFO") as logs, self.assertLogs(
                        WENI_EDA_LOGGER, level="ERROR"
                    ) as eda_logs:
                        channel = handle(self.consumer, self._body(action, project_uuid=unsafe, **extra))

                assert_rejected(channel)
                context = mock_report.call_args.args[1]
                self.assertIsNone(context.project_uuid)
                self.assertNotIn("project_uuid", context.sentry_tags())
                self.assertEqual(
                    logs.output,
                    [f"INFO:temba.projects.consumers.project_event_consumer:project_event_consumed action={action}"],
                )
                self.assertNotIn("forged", "\n".join(eda_logs.output))

    def test_org_lookup_failure_does_not_replace_the_reported_failure(self):
        with patch(
            "temba.projects.consumers.project_event_consumer.update_project_config", side_effect=RuntimeError("boom")
        ), patch(
            "temba.projects.consumers.project_event_consumer.find_org_id", side_effect=DatabaseError("down")
        ), patch(
            "temba.projects.consumers.project_event_consumer.report_exception"
        ) as mock_report:
            channel = handle(self.consumer, self._body("updated", name="New Name"))

        assert_rejected(channel)
        exception, context = mock_report.call_args.args
        self.assertIsInstance(exception, RuntimeError)
        self.assertIsNone(context.org_id)

    def test_failure_is_tagged_with_org_and_user(self):
        with patch(
            "temba.projects.consumers.project_event_consumer.update_project_status", side_effect=RuntimeError("boom")
        ), patch("temba.projects.consumers.project_event_consumer.report_exception") as mock_report:
            channel = handle(self.consumer, self._body("status_updated", status="INACTIVE"))

        assert_rejected(channel)
        context = mock_report.call_args.args[1]
        self.assertEqual(
            context.sentry_tags(),
            {
                "project_uuid": self.project_uuid,
                "action": "status_updated",
                "org_id": self.test_org.id,
                "user_id": self.user.id,
            },
        )

    def test_each_action_is_skipped_unless_listed(self):
        for action, extra, use_case in LEGACY_ACTIONS:
            for legacy_actions, applied in (([], False), ([action], True), (["other"], False)):
                with self.subTest(action=action, legacy_actions=legacy_actions):
                    with override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=legacy_actions), patch(
                        f"temba.projects.consumers.project_event_consumer.{use_case}"
                    ) as mock_use_case, self.assertLogs("temba.projects", level="INFO") as logs:
                        channel = handle(self.consumer, self._body(action, **extra))

                    assert_acked(channel)
                    self.assertEqual(mock_use_case.called, applied)
                    skipped = (
                        "INFO:temba.projects.consumers.project_event_consumer:project_event_skipped "
                        f"action={action} project_uuid={self.project_uuid} reason=amazonmq_consumer_applies"
                    )
                    self.assertEqual(skipped in logs.output, not applied)

    @override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])
    def test_skipped_message_leaves_the_org_unchanged(self):
        channel = handle(self.consumer, self._body("deleted"))

        assert_acked(channel)
        self.assertTrue(Org.objects.get(id=self.test_org.id).is_active)

    def test_validate_message_with_all_valid_actions(self):
        """Test _validate_message with all valid actions"""
        valid_actions = ["deleted", "updated", "status_updated", "project_type_update"]

        for action in valid_actions:
            body = self._body(action)

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
            try:
                self.consumer._validate_message(self._body("status_updated", status=status))
            except ValueError:
                self.fail(f"_validate_message raised ValueError for valid status: {status}")

    def test_apply_event_unknown_action_raises_value_error(self):
        """Unhandled action string hits the final else (not reachable via consume + _validate_message)."""
        body = {
            "project_uuid": self.project_uuid,
            "user_email": self.user.email,
        }
        with self.assertRaisesRegex(ValueError, "Unknown action: future_action"):
            self.consumer._apply_event(
                self.project_uuid,
                self.user.email,
                "future_action",
                body,
            )

    def test_process_event_with_exception_in_usecase_raises(self):
        """Test that exceptions in usecases are captured and the message rejected"""
        with patch("temba.projects.consumers.project_event_consumer.update_project_config") as mock_update:
            mock_update.side_effect = Exception("Database error")

            self._assert_rejected_and_reported(self._body("updated", name="New Name"))
