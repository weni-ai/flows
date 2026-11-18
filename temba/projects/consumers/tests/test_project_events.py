import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import override_settings

from temba.projects.consumers.project_events import (
    InvalidProjectEvent,
    ProjectEventContext,
    ProjectEventRejected,
    canonical_uuid,
    find_org_id,
    find_user_id,
    is_legacy_action,
    report_exception,
    scrub_sentry_event,
)
from temba.tests.base import TembaTest

User = get_user_model()


class ProjectEventsTest(TembaTest):
    @override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=["deleted"])
    def test_is_legacy_action(self):
        self.assertTrue(is_legacy_action("deleted"))
        self.assertFalse(is_legacy_action("updated"))

    @override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])
    def test_is_legacy_action_with_empty_list(self):
        self.assertFalse(is_legacy_action("deleted"))

    def test_canonical_uuid(self):
        value = uuid.uuid4()

        self.assertEqual(canonical_uuid(str(value).upper()), str(value))
        self.assertIsNone(canonical_uuid("not-a-uuid"))
        self.assertIsNone(canonical_uuid("abc project_uuid=forged"))
        self.assertIsNone(canonical_uuid(123))
        self.assertIsNone(canonical_uuid(None))

    def test_find_org_id(self):
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=["proj_uuid"])

        self.assertEqual(find_org_id(str(self.org.proj_uuid)), self.org.id)
        self.assertIsNone(find_org_id(str(uuid.uuid4())))
        self.assertIsNone(find_org_id(None))

    def test_find_user_id_never_creates_a_user(self):
        users_before = User.objects.count()

        self.assertEqual(find_user_id(self.admin.email), self.admin.id)
        self.assertIsNone(find_user_id("nobody@example.com"))
        self.assertIsNone(find_user_id(""))
        self.assertIsNone(find_user_id(None))
        self.assertIsNone(find_user_id(["admin@nyaruka.com"]))
        self.assertEqual(User.objects.count(), users_before)

    def test_context_log_fields_and_tags_skip_unknown_values(self):
        context = ProjectEventContext(event_id="e1", event_type="project.deleted", project_uuid="p1", org_id=7)

        self.assertEqual(context.log_fields(), "event_id=e1 event_type=project.deleted project_uuid=p1")
        self.assertEqual(
            context.sentry_tags(),
            {"project_uuid": "p1", "event_id": "e1", "event_type": "project.deleted", "org_id": 7},
        )
        self.assertEqual(ProjectEventContext(action="deleted").log_fields(), "action=deleted")

    def test_rejected_message(self):
        context = ProjectEventContext(event_id="e1", event_type="project.status.updated", project_uuid="p1")

        invalid = ProjectEventRejected(context, InvalidProjectEvent("data.status must be one of: ACTIVE"))
        other = ProjectEventRejected(context, ValueError("admin@example.com is wrong for Test Org"))
        empty = ProjectEventRejected(ProjectEventContext(), TypeError("bad envelope"))

        self.assertEqual(
            str(invalid),
            "project event rejected: event_id=e1 event_type=project.status.updated project_uuid=p1 "
            "reason=data.status must be one of: ACTIVE",
        )
        self.assertEqual(
            str(other),
            "project event rejected: event_id=e1 event_type=project.status.updated project_uuid=p1 reason=ValueError",
        )
        self.assertEqual(str(empty), "project event rejected: reason=TypeError")

    def test_scrub_sentry_event(self):
        event = {
            "exception": {
                "values": [
                    {
                        "type": "IntegrityError",
                        "value": 'Key (username)=(first.last+tag@example.co.uk) and "other@mail.com" exist',
                        "stacktrace": {"frames": [{"function": "f", "vars": {"user_email": "x@y.com"}}, {}]},
                    },
                    {"type": "ValueError", "value": None},
                ]
            },
            "threads": {"values": [{"stacktrace": {"frames": [{"vars": {"a": 1}}]}}]},
        }

        scrubbed = scrub_sentry_event(event, {})

        first = scrubbed["exception"]["values"][0]
        self.assertEqual(first["value"], 'Key (username)=([email]) and "[email]" exist')
        self.assertNotIn("vars", first["stacktrace"]["frames"][0])
        self.assertNotIn("vars", scrubbed["threads"]["values"][0]["stacktrace"]["frames"][0])
        self.assertEqual(scrub_sentry_event({"message": "hi"}, {}), {"message": "hi"})

    def test_scrub_sentry_event_redacts_whole_names_only(self):
        event = {"exception": {"values": [{"value": "Loja Centro failed, Loja Centrooo kept"}]}}

        scrub_sentry_event(event, {}, redacted_names=("Loja Centro", ""))

        self.assertEqual(event["exception"]["values"][0]["value"], "[name] failed, Loja Centrooo kept")

    def _report(self, exception, context):
        scope = MagicMock()
        push_scope = MagicMock()
        push_scope.return_value.__enter__.return_value = scope

        with patch("temba.projects.consumers.project_events.push_scope", push_scope), patch(
            "temba.projects.consumers.project_events.capture_exception"
        ) as capture:
            report_exception(exception, context)

        capture.assert_called_once_with(exception)
        return scope

    def test_report_exception_sets_known_tags(self):
        context = ProjectEventContext(
            event_id="e1", event_type="project.deleted", project_uuid="p1", org_id=self.org.id, user_id=9
        )

        scope = self._report(ValueError("boom"), context)

        tags = {call.args[0]: call.args[1] for call in scope.set_tag.call_args_list}
        self.assertEqual(
            tags,
            {
                "project_uuid": "p1",
                "event_id": "e1",
                "event_type": "project.deleted",
                "org_id": self.org.id,
                "user_id": 9,
            },
        )
        processor = scope.add_event_processor.call_args.args[0]
        event = processor({"exception": {"values": [{"value": f"{self.org.name} broke"}]}}, {})
        self.assertEqual(event["exception"]["values"][0]["value"], "[name] broke")

    def test_report_exception_without_org(self):
        scope = self._report(ValueError("boom"), ProjectEventContext(action="deleted"))

        scope.set_tag.assert_called_once_with("action", "deleted")
        processor = scope.add_event_processor.call_args.args[0]
        self.assertEqual(processor.keywords, {"redacted_names": ()})

    def test_report_exception_when_the_org_lookup_fails(self):
        with patch("temba.projects.consumers.project_events.Org.objects.filter", side_effect=DatabaseError("down")):
            scope = self._report(ValueError("boom"), ProjectEventContext(org_id=self.org.id))

        processor = scope.add_event_processor.call_args.args[0]
        self.assertEqual(processor.keywords, {"redacted_names": ()})
