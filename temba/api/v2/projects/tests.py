import uuid
from datetime import date
from functools import wraps
from unittest.mock import patch

from rest_framework.authentication import BasicAuthentication

from django.test import SimpleTestCase, override_settings
from django.urls import resolve, reverse

from temba.api.v2.internals.views import JWTAuthMockMixin
from temba.api.v2.projects.views import GetProjectView, ProjectLanguageView, ProjectMessageCountView
from temba.channels.models import ChannelCount
from temba.tests import TembaTest

GET_PROJECT_VIEW_PATH = "temba.api.v2.projects.views.GetProjectView"


def skip_auth_and_permissions(view_path: str):
    """
    Decorator to disable authentication and permission checks for a specific endpoint class.
    Use when testing view logic (status codes and payload) without auth side-effects.
    """

    def decorator(func):
        @patch(f"{view_path}.authentication_classes", [])
        @patch(f"{view_path}.permission_classes", [])
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


class GetProjectViewTest(TembaTest):
    def setUp(self):
        super().setUp()

        # Ensure org has a project UUID for lookups
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

        self.url = reverse("api.v2.projects")

    @patch(f"{GET_PROJECT_VIEW_PATH}.authentication_classes", [BasicAuthentication])
    def test_requires_authentication(self):
        # Without authentication headers, endpoint should deny access
        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}")
        self.assertEqual(resp.status_code, 401)

    @skip_auth_and_permissions(GET_PROJECT_VIEW_PATH)
    def test_missing_project_uuid_returns_400(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "project_uuid is required"})

    @skip_auth_and_permissions(GET_PROJECT_VIEW_PATH)
    def test_nonexistent_project_returns_404(self):
        random_proj = uuid.uuid4()
        resp = self.client.get(f"{self.url}?project_uuid={random_proj}")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    @skip_auth_and_permissions(GET_PROJECT_VIEW_PATH)
    def test_success_returns_project_data(self):
        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["project_uuid"], str(self.org.proj_uuid))
        self.assertEqual(data["name"], self.org.name)
        self.assertEqual(data["is_active"], self.org.is_active)
        self.assertEqual(data["brain_on"], self.org.brain_on)


@override_settings(ROOT_URLCONF="temba.api.v2.projects.urls")
class ProjectsUrlsTest(JWTAuthMockMixin, SimpleTestCase):
    def test_projects_url_resolves_to_get_project_view(self):
        url = reverse("projects")
        self.assertEqual(url, "/projects")
        match = resolve(url)
        self.assertEqual(getattr(match.func, "view_class", None), GetProjectView)

    def test_project_language_url_resolves_to_project_language_view(self):
        url = reverse("project_language")
        self.assertEqual(url, "/projects/project_language")
        match = resolve(url)
        self.assertEqual(getattr(match.func, "view_class", None), ProjectLanguageView)

    def test_project_message_count_url_resolves_to_project_message_count_view(self):
        url = reverse("project_message_count")
        self.assertEqual(url, "/projects/message_count")
        match = resolve(url)
        self.assertEqual(getattr(match.func, "view_class", None), ProjectMessageCountView)


class PatchedJWTAuthMixin(JWTAuthMockMixin):
    def setUp(self):
        super().setUp()
        self.jwt_payload_patch = {}
        self._set_jwt_payload()

    def _set_jwt_payload(self, **kwargs):
        self.jwt_payload_patch = kwargs

    def _mock_jwt_authenticate(self, request, *args, **kwargs):
        result = super()._mock_jwt_authenticate(request, *args, **kwargs)
        if getattr(self, "jwt_payload_patch", None):
            request.jwt_payload.update(self.jwt_payload_patch)
            request.project_uuid = request.jwt_payload.get("project_uuid")
            request.channel_uuid = request.jwt_payload.get("channel_uuid")
        return result


class ProjectLanguageViewTest(PatchedJWTAuthMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

        self.url = reverse("api.v2.project_language")
        self._set_jwt_payload(project_uuid=str(self.org.proj_uuid))

    def test_request_without_project_uuid_and_channel_uuid(self):
        self._set_jwt_payload(project_uuid=None, channel_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(response.status_code, 400)

    def test_request_with_channel_uuid(self):
        channel = self.create_channel("TG", "Test Channel", "test", org=self.org)
        self._set_jwt_payload(channel_uuid=str(channel.uuid), project_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"language": self.org.language})

    def test_request_with_channel_uuid_notfound(self):
        missing_uuid = "2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        self._set_jwt_payload(channel_uuid=missing_uuid, project_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(response.status_code, 404)

    def test_request_with_project_uuid(self):
        self._set_jwt_payload(project_uuid=str(self.org.proj_uuid), channel_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"language": self.org.language})

    def test_request_with_project_uuid_notfound(self):
        missing_uuid = "2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        self._set_jwt_payload(project_uuid=missing_uuid, channel_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(response.status_code, 404)


class ProjectMessageCountViewTest(PatchedJWTAuthMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

        self.url = reverse("api.v2.project_message_count")
        self._set_jwt_payload(project_uuid=str(self.org.proj_uuid), channel_uuid=None)

    def test_returns_incoming_outgoing_total_amounts(self):
        ch1 = self.create_channel("TG", "Test Channel 1", "test1", org=self.org)
        ch2 = self.create_channel("TG", "Test Channel 2", "test2", org=self.org)

        # another org should not affect totals
        other_org = self.org2
        other_org.proj_uuid = uuid.uuid4()
        other_org.save(update_fields=("proj_uuid",))
        other_ch = self.create_channel("TG", "Other Channel", "other", org=other_org)

        ChannelCount.objects.create(
            channel=ch1, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=5
        )
        ChannelCount.objects.create(
            channel=ch1, count_type=ChannelCount.OUTGOING_MSG_TYPE, day=date(2026, 1, 1), count=2
        )
        ChannelCount.objects.create(
            channel=ch2, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 2), count=3
        )
        ChannelCount.objects.create(
            channel=ch2, count_type=ChannelCount.OUTGOING_MSG_TYPE, day=date(2026, 1, 3), count=7
        )
        ChannelCount.objects.create(
            channel=other_ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=999
        )

        resp = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"incoming_amount": 8, "outgoing_amount": 9, "total_amount": 17})

    def test_date_filter_after_before_inclusive(self):
        ch = self.create_channel("TG", "Test Channel", "test", org=self.org)

        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=10
        )
        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.OUTGOING_MSG_TYPE, day=date(2026, 1, 2), count=20
        )
        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.OUTGOING_MSG_TYPE, day=date(2026, 1, 3), count=30
        )

        resp = self.client.get(f"{self.url}?after=2026-01-02&before=2026-01-03", **self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"incoming_amount": 0, "outgoing_amount": 50, "total_amount": 50})

    def test_invalid_date_returns_400(self):
        resp = self.client.get(f"{self.url}?after=not-a-date", **self.auth_headers)
        self.assertEqual(resp.status_code, 400)
