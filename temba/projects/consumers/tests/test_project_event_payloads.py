import uuid

from weni.eda.events import Event

from django.test import SimpleTestCase

from temba.projects.consumers.project_event_payloads import (
    InvalidProjectEvent,
    ProjectDeletedData,
    ProjectEventEnvelope,
    ProjectStatusUpdatedData,
    ProjectTypeUpdatedData,
    ProjectUpdatedData,
)
from temba.projects.consumers.project_events import ProjectStatus

EMAIL = "admin@example.com"


def _event(**overrides) -> Event:
    fields = {
        "event_id": str(uuid.uuid4()),
        "event_type": "project.updated",
        "producer": "weni-engine",
        "timestamp": "2026-11-17T21:40:00Z",
        "data": {},
    }
    fields.update(overrides)
    return Event(**fields)


class ProjectEventEnvelopeTest(SimpleTestCase):
    def test_accepts_uuid_event_id_and_weni_engine_producer(self):
        event = _event()

        envelope = ProjectEventEnvelope.from_event(event)

        self.assertEqual(envelope.event_id, event.event_id)
        self.assertEqual(envelope.event_type, "project.updated")
        self.assertEqual(envelope.producer, "weni-engine")

    def test_accepts_null_producer(self):
        self.assertIsNone(ProjectEventEnvelope.from_event(_event(producer=None)).producer)

    def test_accepts_64_characters(self):
        self.assertEqual(ProjectEventEnvelope.from_event(_event(event_id="a" * 64)).event_id, "a" * 64)

    def test_rejects_unsafe_tokens_without_echoing_them(self):
        cases = [
            ("event_id", "abc project_uuid=forged"),
            ("event_id", "abc\nproject_uuid=forged"),
            ("event_id", "abc\n"),
            ("event_id", ""),
            ("event_id", 12345),
            ("event_id", None),
            ("event_id", "a" * 65),
            ("event_type", "project updated"),
            ("event_type", "a" * 65),
            ("event_type", None),
            ("producer", {"name": "connect"}),
            ("producer", "connect app"),
            ("producer", 1),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(InvalidProjectEvent) as raised:
                    ProjectEventEnvelope.from_event(_event(**{field: value}))

                message = str(raised.exception)
                self.assertTrue(message.startswith(f"{field} must be"))
                if isinstance(value, str) and value:
                    self.assertNotIn(value, message)


class ProjectPayloadsTest(SimpleTestCase):
    def setUp(self):
        self.project_uuid = str(uuid.uuid4())

    def _base(self, **fields) -> dict:
        return {"uuid": self.project_uuid, "user_email": EMAIL, **fields}

    def _assert_invalid(self, payload_class, data, field):
        with self.assertRaises(InvalidProjectEvent) as raised:
            payload_class.from_data(data)
        message = str(raised.exception)
        self.assertTrue(message.startswith(field), message)
        self.assertNotIn(EMAIL, message)
        return message

    def test_project_updated_with_all_fields(self):
        data = self._base(
            name="Loja", description="desc", language="pt-br", timezone="America/Sao_Paulo", config={"x": 1}
        )

        payload = ProjectUpdatedData.from_data(data)

        self.assertEqual(
            payload,
            ProjectUpdatedData(
                project_uuid=self.project_uuid,
                user_email=EMAIL,
                name="Loja",
                description="desc",
                language="pt-br",
                timezone="America/Sao_Paulo",
            ),
        )

    def test_project_updated_optional_fields_absent_null_or_empty(self):
        payload = ProjectUpdatedData.from_data(self._base(name=None, description=""))

        self.assertIsNone(payload.name)
        self.assertEqual(payload.description, "")
        self.assertIsNone(payload.language)
        self.assertIsNone(payload.timezone)

    def test_project_uuid_is_canonical(self):
        payload = ProjectDeletedData.from_data(self._base(uuid=self.project_uuid.upper()))

        self.assertEqual(payload.project_uuid, self.project_uuid)

    def test_common_rules(self):
        for payload_class in (ProjectUpdatedData, ProjectDeletedData):
            with self.subTest(payload_class=payload_class.__name__):
                self._assert_invalid(payload_class, ["not", "a", "dict"], "data must be an object")
                self._assert_invalid(payload_class, {"user_email": EMAIL}, "data.uuid")
                self._assert_invalid(payload_class, self._base(uuid="not-a-uuid"), "data.uuid")
                self._assert_invalid(payload_class, self._base(uuid=123), "data.uuid")
                self._assert_invalid(payload_class, {"uuid": self.project_uuid}, "data.user_email")
                self._assert_invalid(payload_class, self._base(user_email="  "), "data.user_email")
                self._assert_invalid(payload_class, self._base(user_email=["a@b.c"]), "data.user_email")

    def test_project_updated_rejects_non_string_fields(self):
        for field in ("name", "description", "language"):
            with self.subTest(field=field):
                self._assert_invalid(ProjectUpdatedData, self._base(**{field: 1}), f"data.{field}")

    def test_project_updated_rejects_unknown_timezone(self):
        message = self._assert_invalid(ProjectUpdatedData, self._base(timezone="Mars/Olympus"), "data.timezone")
        self.assertNotIn("Mars/Olympus", message)
        self._assert_invalid(ProjectUpdatedData, self._base(timezone=""), "data.timezone")
        self._assert_invalid(ProjectUpdatedData, self._base(timezone=3), "data.timezone")

    def test_project_status_updated(self):
        for status in ProjectStatus:
            with self.subTest(status=status):
                payload = ProjectStatusUpdatedData.from_data(self._base(status=status.value))
                self.assertEqual(payload.status, status)

        self._assert_invalid(ProjectStatusUpdatedData, self._base(), "data.status")
        message = self._assert_invalid(ProjectStatusUpdatedData, self._base(status="PAUSED"), "data.status")
        self.assertNotIn("PAUSED", message)
        self._assert_invalid(ProjectStatusUpdatedData, self._base(status="active"), "data.status")

    def test_project_type_updated(self):
        self.assertTrue(ProjectTypeUpdatedData.from_data(self._base(is_multi_agents=True)).is_multi_agents)
        self.assertFalse(ProjectTypeUpdatedData.from_data(self._base(is_multi_agents=False)).is_multi_agents)

        for value in (1, 0, "true", None):
            with self.subTest(value=value):
                self._assert_invalid(ProjectTypeUpdatedData, self._base(is_multi_agents=value), "data.is_multi_agents")
        self._assert_invalid(ProjectTypeUpdatedData, self._base(), "data.is_multi_agents")
