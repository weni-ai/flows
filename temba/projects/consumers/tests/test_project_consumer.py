import json
import logging
import uuid
from unittest.mock import Mock, patch

import pytz
import sentry_sdk

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings

from temba.orgs.models import Org
from temba.projects.consumers.project_consumer import ProjectConsumer
from temba.projects.consumers.project_event_consumer import ProjectEventConsumer
from temba.tests.base import TembaTest

from .helpers import assert_acked, assert_rejected, build_envelope, handle

User = get_user_model()

ALL_LEGACY_ACTIONS = ["updated", "status_updated", "project_type_update", "deleted"]
WENI_EDA_LOGGER = "weni.eda.django.consumers.consumer"
CAPTURE_EXCEPTION = "temba.projects.consumers.project_events.capture_exception"

# event_type, legacy action, extra data fields, use case name in the consumer modules
PROJECT_CHANGES = [
    ("project.updated", "updated", {"name": "New Name"}, "update_project_config"),
    ("project.status.updated", "status_updated", {"status": "INACTIVE"}, "update_project_status"),
    ("project.type.updated", "project_type_update", {"is_multi_agents": True}, "update_project_type"),
    ("project.deleted", "deleted", {}, "delete_project"),
]


def format_records(records) -> str:
    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    return "\n".join(formatter.format(record) for record in records)


class ProjectConsumerTestCase(TembaTest):
    def setUp(self):
        super().setUp()
        self.consumer = ProjectConsumer()
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

    def _data(self, **fields) -> dict:
        return {"uuid": self.project_uuid, "user_email": self.editor.email, **fields}

    def _deliver(self, event_type: str, data, **overrides) -> Mock:
        return handle(self.consumer, build_envelope(event_type, data, **overrides))


class ProjectCreatedTest(ProjectConsumerTestCase):
    def _creation_body(self, **fields) -> dict:
        body = {
            "uuid": str(uuid.uuid4()),
            "name": "Test Project",
            "is_template": False,
            "date_format": "D",
            "template_type_uuid": "",
            "timezone": "Africa/Kigali",
            "description": "desc",
            "user_email": "admin@example.com",
            "extra_fields": {},
            "authorizations": [],
        }
        body.update(fields)
        return body

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    @patch("temba.projects.consumers.project_consumer.TemplateTypeIntegrationUseCase")
    @patch("temba.projects.consumers.project_consumer.FlowSetupHandlerUseCase")
    def test_consume_passes_inline_agent_switch_and_language_to_use_case(
        self, mock_flow_uc, mock_template_uc, mock_project_creation_uc
    ):
        mock_use_case = Mock()
        mock_project_creation_uc.return_value = mock_use_case

        body = self._creation_body(brain_on=False, language="pt-br", inline_agent_switch=True)
        channel = self._deliver("project.created", body)

        mock_use_case.create_project.assert_called_once()
        (
            project_dto,
            user_email,
            extra_fields,
            authorizations,
        ) = mock_use_case.create_project.call_args[0]
        self.assertEqual(user_email, "admin@example.com")
        self.assertEqual(extra_fields, {})
        self.assertEqual(authorizations, [])
        self.assertEqual(project_dto.language, "pt-br")
        self.assertTrue(project_dto.inline_agent_switch)
        self.assertFalse(project_dto.is_live_desk_copilot)
        assert_acked(channel)

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    @patch("temba.projects.consumers.project_consumer.TemplateTypeIntegrationUseCase")
    @patch("temba.projects.consumers.project_consumer.FlowSetupHandlerUseCase")
    def test_consume_passes_is_live_desk_copilot_to_use_case(
        self, mock_flow_uc, mock_template_uc, mock_project_creation_uc
    ):
        mock_use_case = Mock()
        mock_project_creation_uc.return_value = mock_use_case

        channel = self._deliver("project.created", self._creation_body(brain_on=False, is_live_desk_copilot=True))

        project_dto = mock_use_case.create_project.call_args[0][0]
        self.assertTrue(project_dto.is_live_desk_copilot)
        assert_acked(channel)

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    @patch("temba.projects.consumers.project_consumer.TemplateTypeIntegrationUseCase")
    @patch("temba.projects.consumers.project_consumer.FlowSetupHandlerUseCase")
    def test_consume_defaults_inline_agent_switch_when_absent(
        self, mock_flow_uc, mock_template_uc, mock_project_creation_uc
    ):
        mock_use_case = Mock()
        mock_project_creation_uc.return_value = mock_use_case

        channel = self._deliver("project.created", self._creation_body(extra_fields=None, authorizations=None))

        project_dto = mock_use_case.create_project.call_args[0][0]
        self.assertTrue(project_dto.inline_agent_switch)
        self.assertFalse(project_dto.brain_on)
        assert_acked(channel)

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    @patch("temba.projects.consumers.project_consumer.TemplateTypeIntegrationUseCase")
    @patch("temba.projects.consumers.project_consumer.FlowSetupHandlerUseCase")
    def test_consume_logs_created_event_without_payload(self, mock_flow_uc, mock_template_uc, mock_creation_uc):
        envelope = build_envelope("project.created", self._creation_body())

        with self.assertLogs("temba.projects", level="INFO") as logs:
            channel = handle(self.consumer, envelope)

        assert_acked(channel)
        self.assertEqual(
            logs.output,
            [
                f"INFO:temba.projects.consumers.project_consumer:project_event_consumed "
                f"event_id={envelope['event_id']} event_type=project.created producer=weni-engine"
            ],
        )

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    def test_creation_failure_is_reported_and_rejected(self, mock_project_creation_uc):
        mock_project_creation_uc.return_value.create_project.side_effect = RuntimeError("boom")

        with patch(CAPTURE_EXCEPTION) as capture:
            channel = self._deliver("project.created", self._creation_body())

        assert_rejected(channel)
        capture.assert_called_once()

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    def test_consume_ignores_unsupported_event_type(self, mock_project_creation_uc):
        with self.assertLogs("temba.projects", level="INFO") as logs:
            channel = self._deliver("project.archived", {"uuid": self.project_uuid})

        mock_project_creation_uc.assert_not_called()
        assert_acked(channel)
        self.assertIn("project_event_consumed", logs.output[0])
        self.assertIn("event_type=project.archived", logs.output[0])


@override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])
class ProjectChangeAppliedTest(ProjectConsumerTestCase):
    def test_project_updated(self):
        data = self._data(name="Loja", description="Nova descrição", language="pt-br", timezone="America/Sao_Paulo")

        with self.assertLogs("temba.projects", level="INFO") as logs:
            channel = self._deliver("project.updated", data)

        assert_acked(channel)
        self.test_org.refresh_from_db()
        self.assertEqual(self.test_org.name, "Loja")
        self.assertEqual(self.test_org.config["description"], "Nova descrição")
        self.assertEqual(self.test_org.language, "pt-br")
        self.assertEqual(self.test_org.timezone, pytz.timezone("America/Sao_Paulo"))
        self.assertEqual(self.test_org.modified_by, self.editor)
        self.assertIn(f"project_uuid={self.project_uuid} producer=weni-engine", logs.output[0])

    def test_project_updated_with_null_fields_leaves_them_unchanged(self):
        data = self._data(name=None, description=None, language=None, timezone=None, config={"x": 1})

        channel = self._deliver("project.updated", data)

        assert_acked(channel)
        self.test_org.refresh_from_db()
        self.assertEqual(self.test_org.name, "Test Org")
        self.assertEqual(self.test_org.config["description"], "Test description")
        self.assertEqual(self.test_org.language, "en-us")
        self.assertEqual(self.test_org.timezone, pytz.timezone("Africa/Kigali"))
        self.assertEqual(self.test_org.modified_by, self.editor)

    def test_project_status_updated(self):
        channel = self._deliver("project.status.updated", self._data(status="INACTIVE"))

        assert_acked(channel)
        self.test_org.refresh_from_db()
        self.assertTrue(self.test_org.is_suspended)
        self.assertTrue(self.test_org.is_active)
        self.assertEqual(self.test_org.modified_by, self.editor)

        for status in ("ACTIVE", "IN_TEST"):
            with self.subTest(status=status):
                Org.objects.filter(id=self.test_org.id).update(is_suspended=True)

                channel = self._deliver("project.status.updated", self._data(status=status))

                assert_acked(channel)
                self.test_org.refresh_from_db()
                self.assertFalse(self.test_org.is_suspended)
                self.assertTrue(self.test_org.is_active)

    def test_project_type_updated(self):
        channel = self._deliver("project.type.updated", self._data(is_multi_agents=True))

        assert_acked(channel)
        self.test_org.refresh_from_db()
        self.assertTrue(self.test_org.config["is_multi_agents"])
        self.assertEqual(self.test_org.modified_by, self.editor)

    def test_project_deleted(self):
        channel = self._deliver("project.deleted", self._data())

        assert_acked(channel)
        self.test_org.refresh_from_db()
        self.assertFalse(self.test_org.is_active)
        self.assertIsNotNone(self.test_org.released_on)
        self.assertEqual(self.test_org.modified_by, self.editor)

    def test_project_deleted_twice_keeps_released_on(self):
        assert_acked(self._deliver("project.deleted", self._data()))
        self.test_org.refresh_from_db()
        released_on = self.test_org.released_on

        channel = self._deliver("project.deleted", self._data(user_email=self.admin.email))

        assert_acked(channel)
        self.test_org.refresh_from_db()
        self.assertEqual(self.test_org.released_on, released_on)
        self.assertEqual(self.test_org.modified_by, self.editor)

    def test_unknown_project_is_acked_and_logged(self):
        for event_type, action, extra, use_case in PROJECT_CHANGES:
            with self.subTest(event_type=event_type):
                unknown_uuid = str(uuid.uuid4())
                envelope = build_envelope(event_type, self._data(uuid=unknown_uuid, **extra))

                with patch(f"temba.projects.consumers.project_consumer.{use_case}") as mock_use_case:
                    with self.assertLogs("temba.projects", level="WARNING") as logs:
                        channel = handle(self.consumer, envelope)

                assert_acked(channel)
                mock_use_case.assert_not_called()
                self.assertEqual(
                    logs.output,
                    [
                        f"WARNING:temba.projects.consumers.project_consumer:project_event_org_not_found "
                        f"event_id={envelope['event_id']} event_type={event_type} project_uuid={unknown_uuid}"
                    ],
                )


class ProjectChangeSkippedTest(ProjectConsumerTestCase):
    def test_each_action_is_skipped_only_while_listed(self):
        for event_type, action, extra, use_case in PROJECT_CHANGES:
            for legacy_actions, applied in ((ALL_LEGACY_ACTIONS, False), ([], True), ([action], False)):
                with self.subTest(event_type=event_type, legacy_actions=legacy_actions):
                    envelope = build_envelope(event_type, self._data(**extra))

                    with override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=legacy_actions), patch(
                        f"temba.projects.consumers.project_consumer.{use_case}"
                    ) as mock_use_case, self.assertLogs("temba.projects", level="INFO") as logs:
                        channel = handle(self.consumer, envelope)

                    assert_acked(channel)
                    self.assertEqual(mock_use_case.called, applied)
                    skipped = (
                        f"INFO:temba.projects.consumers.project_consumer:project_event_skipped "
                        f"event_id={envelope['event_id']} event_type={event_type} project_uuid={self.project_uuid} "
                        f"reason=legacy_consumer_applies"
                    )
                    self.assertEqual(skipped in logs.output, not applied)

    def test_default_list_skips_without_touching_the_org(self):
        modified_on = self.test_org.modified_on

        channel = self._deliver("project.status.updated", self._data(status="INACTIVE"))

        assert_acked(channel)
        self.test_org.refresh_from_db()
        self.assertFalse(self.test_org.is_suspended)
        self.assertEqual(self.test_org.modified_on, modified_on)


class DualDeliveryTest(ProjectConsumerTestCase):
    """Each change arrives on both queues; exactly one consumer applies it for any value of the setting."""

    def _legacy_body(self, action: str, extra: dict) -> dict:
        return {"project_uuid": self.project_uuid, "user_email": self.editor.email, "action": action, **extra}

    def test_exactly_one_consumer_applies_each_action(self):
        for legacy_actions in (ALL_LEGACY_ACTIONS, [], ["project_type_update"]):
            for event_type, action, extra, use_case in PROJECT_CHANGES:
                with self.subTest(legacy_actions=legacy_actions, event_type=event_type):
                    with override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=legacy_actions), patch(
                        f"temba.projects.consumers.project_consumer.{use_case}"
                    ) as amazonmq_use_case, patch(
                        f"temba.projects.consumers.project_event_consumer.{use_case}"
                    ) as legacy_use_case:
                        amazonmq_channel = self._deliver(event_type, self._data(**extra))
                        legacy_channel = handle(ProjectEventConsumer(), self._legacy_body(action, extra))

                    assert_acked(amazonmq_channel)
                    assert_acked(legacy_channel)
                    legacy_applies = action in legacy_actions
                    self.assertEqual(legacy_use_case.call_count, 1 if legacy_applies else 0)
                    self.assertEqual(amazonmq_use_case.call_count, 0 if legacy_applies else 1)

    @override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=["project_type_update"])
    def test_mixed_list_against_the_database(self):
        handle(ProjectEventConsumer(), self._legacy_body("project_type_update", {"is_multi_agents": True}))
        self._deliver("project.type.updated", self._data(is_multi_agents=False))
        self.test_org.refresh_from_db()
        self.assertTrue(self.test_org.config["is_multi_agents"])

        handle(ProjectEventConsumer(), self._legacy_body("deleted", {}))
        self.test_org.refresh_from_db()
        self.assertTrue(self.test_org.is_active)

        self._deliver("project.deleted", self._data())
        self.test_org.refresh_from_db()
        self.assertFalse(self.test_org.is_active)


class InvalidEventTest(ProjectConsumerTestCase):
    def _assert_rejected_without_changes(self, envelope, *, unsafe_value=None):
        """Rejected before anything is written to temba.projects, with the org unchanged."""
        org_before = Org.objects.values().get(id=self.test_org.id)

        with patch(CAPTURE_EXCEPTION) as capture, self.assertLogs(
            WENI_EDA_LOGGER, level="ERROR"
        ) as eda_logs, self.assertNoLogs("temba.projects", level="INFO"):
            channel = handle(self.consumer, envelope)
        output = format_records(eda_logs.records)

        assert_rejected(channel)
        capture.assert_called_once()
        self.assertEqual(Org.objects.values().get(id=self.test_org.id), org_before)
        self.assertNotIn(self.editor.email, output)
        if unsafe_value is not None:
            self.assertNotIn(unsafe_value, output)
        return output

    @override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])
    def test_invalid_payloads_are_rejected(self):
        cases = [
            ("project.deleted", self._data(uuid="not-a-uuid"), "data.uuid"),
            ("project.deleted", {"uuid": self.project_uuid}, "data.user_email"),
            ("project.status.updated", self._data(), "data.status"),
            ("project.status.updated", self._data(status="PAUSED"), "data.status"),
            ("project.type.updated", self._data(is_multi_agents=1), "data.is_multi_agents"),
            ("project.type.updated", self._data(is_multi_agents="true"), "data.is_multi_agents"),
            ("project.updated", self._data(name="Other", timezone="Mars/Olympus"), "data.timezone"),
        ]
        for event_type, data, field in cases:
            with self.subTest(event_type=event_type, field=field):
                envelope = build_envelope(event_type, data)

                output = self._assert_rejected_without_changes(envelope)

                self.assertIn(f"Message rejected: project event rejected: event_id={envelope['event_id']}", output)
                self.assertIn(f"reason={field}", output)

    def test_validation_runs_while_the_action_is_listed(self):
        envelope = build_envelope("project.status.updated", self._data(status="PAUSED"))

        output = self._assert_rejected_without_changes(envelope)

        self.assertIn("reason=data.status must be one of", output)

    def test_unsafe_envelopes_are_rejected_before_logging(self):
        cases = [
            ("project.deleted", {"event_id": "abc project_uuid=forged"}, "project_uuid=forged"),
            ("project.deleted", {"event_id": "abc\nproject_uuid=forged"}, "project_uuid=forged"),
            ("project.deleted", {"event_id": 987654321}, "987654321"),
            ("project.deleted", {"producer": {"name": "forged-producer"}}, "forged-producer"),
            ("project.created", {"producer": {"name": "forged-producer"}}, "forged-producer"),
            ("project.created", {"event_id": "abc def-forged"}, "def-forged"),
        ]
        for event_type, overrides, unsafe_value in cases:
            with self.subTest(event_type=event_type, overrides=overrides):
                envelope = build_envelope(event_type, self._data(), **overrides)

                output = self._assert_rejected_without_changes(envelope, unsafe_value=unsafe_value)

                self.assertIn("project event rejected: reason=", output)

    def test_envelope_with_a_missing_key_is_rejected(self):
        envelope = build_envelope("project.deleted", self._data())
        del envelope["timestamp"]

        output = self._assert_rejected_without_changes(envelope)

        self.assertIn("project event rejected: reason=TypeError", output)

    def test_invalid_json_is_rejected(self):
        with patch(CAPTURE_EXCEPTION) as capture:
            channel = handle(self.consumer, b"invalid json {{")

        assert_rejected(channel)
        capture.assert_called_once()


@override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])
class SentryReportTest(ProjectConsumerTestCase):
    """The Sentry event and the weni-eda rejection log never carry the e-mail, the org name or frame variables."""

    def _deliver_capturing(self, data):
        events = []
        client = sentry_sdk.Client(
            dsn="https://public@sentry.example.com/1",
            transport=events.append,
            default_integrations=False,
            include_local_variables=True,
            send_default_pii=False,
        )
        envelope = build_envelope("project.status.updated", data)
        failure = RuntimeError(f"{data['user_email']} cannot change {self.test_org.name}")

        with sentry_sdk.Hub(client), patch(
            "temba.projects.consumers.project_consumer.update_project_status", side_effect=failure
        ), self.assertLogs(WENI_EDA_LOGGER, level="ERROR") as eda_logs:
            channel = handle(self.consumer, envelope)
        client.flush()

        assert_rejected(channel)
        self.assertEqual(len(events), 1)
        return envelope, events[0], format_records(eda_logs.records)

    def _assert_no_personal_data(self, event, eda_output, email):
        serialized = json.dumps(event, default=str)
        self.assertNotIn(email, serialized)
        self.assertNotIn(self.test_org.name, serialized)
        self.assertEqual(event["exception"]["values"][-1]["value"], "[email] cannot change [name]")
        for value in event["exception"]["values"]:
            for frame in value["stacktrace"]["frames"]:
                self.assertNotIn("vars", frame)

        self.assertNotIn(email, eda_output)
        self.assertNotIn(self.test_org.name, eda_output)
        self.assertIn("reason=RuntimeError", eda_output)

    def test_existing_user_is_tagged(self):
        envelope, event, eda_output = self._deliver_capturing(self._data(status="INACTIVE"))

        self._assert_no_personal_data(event, eda_output, self.editor.email)
        self.assertEqual(
            event["tags"],
            {
                "project_uuid": self.project_uuid,
                "event_id": envelope["event_id"],
                "event_type": "project.status.updated",
                "org_id": self.test_org.id,
                "user_id": self.editor.id,
            },
        )

    def test_unknown_user_is_not_tagged_nor_created(self):
        users_before = User.objects.count()

        envelope, event, eda_output = self._deliver_capturing(
            self._data(status="INACTIVE", user_email="ghost@example.com")
        )

        self._assert_no_personal_data(event, eda_output, "ghost@example.com")
        self.assertNotIn("user_id", event["tags"])
        self.assertEqual(event["tags"]["org_id"], self.test_org.id)
        self.assertEqual(User.objects.count(), users_before)
