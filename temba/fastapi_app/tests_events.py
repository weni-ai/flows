import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from temba.fastapi_app.events import EventsFilters, app, get_events
from temba.fastapi_app.events_context import resolve_org_and_user_for_events
from temba.tests.base import TembaTest


def _parse(resp) -> tuple[int, dict]:
    return resp.status_code, json.loads(resp.body or b"{}")


class TestEventsHealthEndpoint(TembaTest):
    def setUp(self):
        super().setUp()
        self.client_fastapi = TestClient(app)

    def test_health_root(self):
        resp = self.client_fastapi.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_at_health(self):
        resp = self.client_fastapi.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_under_fastapi_prefix(self):
        resp = self.client_fastapi.get("/fastapi/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_under_fastapi_prefix_health(self):
        resp = self.client_fastapi.get("/fastapi/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class TestResolveOrgAndUserForEvents(TembaTest):
    def setUp(self):
        super().setUp()
        if not self.org.proj_uuid:
            self.org.proj_uuid = uuid.uuid4()
            self.org.save(update_fields=("proj_uuid",))

    def test_missing_project_uuid_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_org_and_user_for_events(project_uuid=None)
        self.assertEqual(str(ctx.exception), "Project not provided")

    def test_invalid_project_uuid_raises_not_found(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_org_and_user_for_events(project_uuid=str(uuid.uuid4()))
        self.assertEqual(str(ctx.exception), "Project not found")

    def test_malformed_project_uuid_raises_not_found(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_org_and_user_for_events(project_uuid="not-a-uuid")
        self.assertEqual(str(ctx.exception), "Project not found")

    def test_resolves_with_created_by_fallback(self):
        org, user = resolve_org_and_user_for_events(project_uuid=str(self.org.proj_uuid))
        self.assertEqual(org.pk, self.org.pk)
        self.assertIsNotNone(user)
        self.assertEqual(user.get_org().pk, self.org.pk)

    def test_resolves_with_internal_user_email_when_set(self):
        with self.settings(INTERNAL_USER_EMAIL=self.editor.email):
            _, user = resolve_org_and_user_for_events(project_uuid=str(self.org.proj_uuid))
        self.assertEqual(user.email, self.editor.email)

    def test_falls_back_when_internal_user_email_does_not_exist(self):
        with self.settings(INTERNAL_USER_EMAIL="ghost-user@example.com"):
            _, user = resolve_org_and_user_for_events(project_uuid=str(self.org.proj_uuid))
        self.assertEqual(user.pk, self.org.created_by.pk)

    @patch("temba.fastapi_app.events_context._resolve_internal_user", return_value=None)
    def test_raises_when_no_user_can_be_resolved(self, _mock_resolve):
        with self.assertRaises(ValueError) as ctx:
            resolve_org_and_user_for_events(project_uuid=str(self.org.proj_uuid))
        self.assertEqual(str(ctx.exception), "Internal user not found")


class TestEventsFiltersModel(TembaTest):
    def test_silver_without_table_raises(self):
        with self.assertRaises(ValidationError):
            EventsFilters(
                date_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                date_end=datetime(2025, 1, 2, tzinfo=timezone.utc),
                silver=True,
            )

    def test_silver_with_table_is_valid(self):
        f = EventsFilters(
            date_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            date_end=datetime(2025, 1, 2, tzinfo=timezone.utc),
            silver=True,
            table="silver_table",
        )
        self.assertTrue(f.silver)
        self.assertEqual(f.table, "silver_table")


class TestGetEventsHandler(TembaTest):
    """Call the FastAPI handler directly to avoid the TestClient threadpool."""

    def setUp(self):
        super().setUp()
        if not self.org.proj_uuid:
            self.org.proj_uuid = uuid.uuid4()
            self.org.save(update_fields=("proj_uuid",))
        self.filters = EventsFilters(
            date_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            date_end=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )

    def test_project_not_provided_returns_401(self):
        with self.assertRaises(HTTPException) as ctx:
            get_events(filters=self.filters, project_uuid=None, jwt_payload={})

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, {"error": "Project not provided"})

    def test_project_not_found_returns_404(self):
        with self.assertRaises(HTTPException) as ctx:
            get_events(filters=self.filters, project_uuid=str(uuid.uuid4()), jwt_payload={})

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, {"error": "Project not found"})

    @patch("temba.api.v2.services.events.fetch_events_for_org")
    def test_success_returns_200_with_events(self, mock_fetch):
        mock_fetch.return_value = [{"id": "abc", "event_name": "hello"}]
        resp = get_events(
            filters=self.filters,
            project_uuid=str(self.org.proj_uuid),
            jwt_payload={},
        )

        status_code, data = _parse(resp)
        self.assertEqual(status_code, 200)
        self.assertEqual(data, [{"id": "abc", "event_name": "hello"}])
        mock_fetch.assert_called_once()
        _, kwargs = mock_fetch.call_args
        self.assertEqual(kwargs["limit"], 10)
        self.assertEqual(kwargs["offset"], 0)
        self.assertFalse(kwargs["silver"])

    @patch("temba.api.v2.services.events.fetch_events_for_org")
    def test_jwt_payload_project_uuid_is_used(self, mock_fetch):
        mock_fetch.return_value = []
        resp = get_events(
            filters=self.filters,
            project_uuid=None,
            jwt_payload={"project_uuid": str(self.org.proj_uuid)},
        )

        status_code, _ = _parse(resp)
        self.assertEqual(status_code, 200)
        mock_fetch.assert_called_once()

    @patch("temba.api.v2.services.events.fetch_events_for_org")
    def test_limit_is_capped_at_max(self, mock_fetch):
        mock_fetch.return_value = []
        filters = EventsFilters(
            date_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            date_end=datetime(2025, 1, 2, tzinfo=timezone.utc),
            limit=5000,
        )
        get_events(filters=filters, project_uuid=str(self.org.proj_uuid), jwt_payload={})

        _, kwargs = mock_fetch.call_args
        self.assertEqual(kwargs["limit"], 100)

    @patch("temba.api.v2.services.events.fetch_events_for_org", side_effect=RuntimeError("boom"))
    def test_service_error_returns_500(self, _mock_fetch):
        resp = get_events(filters=self.filters, project_uuid=str(self.org.proj_uuid), jwt_payload={})

        status_code, data = _parse(resp)
        self.assertEqual(status_code, 500)
        self.assertEqual(data, {"error": "boom"})
