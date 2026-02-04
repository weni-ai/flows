import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from unittest.mock import patch

import pytz
from rest_framework.authentication import BasicAuthentication

from django.test import SimpleTestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from temba.api.v2.internals.views import JWTAuthMockMixin
from temba.api.v2.projects.views import (
    GetProjectView,
    InternalProjectMessageCountView,
    ProjectLanguageView,
    ProjectMessageCountView,
)
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

    def test_internal_project_message_count_url_resolves_to_internal_view(self):
        url = reverse("internal_project_message_count")
        self.assertEqual(url, "/projects/internal/message_count")
        match = resolve(url)
        self.assertEqual(getattr(match.func, "view_class", None), InternalProjectMessageCountView)


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

    def test_request_without_project_uuid_and_channel_uuid_returns_400(self):
        # Normally prevented by RequiredJWTAuthentication, but possible in patched tests/callers
        self._set_jwt_payload(project_uuid=None, channel_uuid=None)
        resp = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "project_uuid or channel_uuid is required"})

    def test_request_with_project_uuid_notfound_returns_404(self):
        missing_uuid = "2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        self._set_jwt_payload(project_uuid=missing_uuid, channel_uuid=None)
        resp = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    def test_request_with_channel_uuid_notfound_returns_404(self):
        missing_uuid = "2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        self._set_jwt_payload(channel_uuid=missing_uuid, project_uuid=None)
        resp = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Channel not found"})

    def test_request_with_channel_uuid(self):
        # create one channel in our org and set counts
        ch = self.create_channel("TG", "Test Channel", "test", org=self.org)
        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=4
        )
        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.OUTGOING_MSG_TYPE, day=date(2026, 1, 1), count=6
        )

        # call endpoint using channel_uuid (no project_uuid in token)
        self._set_jwt_payload(channel_uuid=str(ch.uuid), project_uuid=None)
        resp = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"incoming_amount": 4, "outgoing_amount": 6, "total_amount": 10})


INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH = "temba.api.v2.projects.views.InternalProjectMessageCountView"


class InternalProjectMessageCountViewTest(TembaTest):
    def setUp(self):
        super().setUp()

        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))

        self.org2.proj_uuid = uuid.uuid4()
        self.org2.save(update_fields=("proj_uuid",))

        self.url = reverse("api.v2.internal_project_message_count")

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_defaults_to_today_when_no_date_filters(self):
        """When no date filters provided, defaults to today's data only."""
        ch = self.create_channel("TG", "Channel", "ch", org=self.org)
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        # Create counts for today and yesterday
        ChannelCount.objects.create(channel=ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=today, count=100)
        ChannelCount.objects.create(channel=ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=yesterday, count=50)

        # Without date filters, should only return today's data
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data["incoming_amount"], 100)  # Only today's count

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_returns_all_projects_when_no_project_uuid(self):
        """When no project_uuid is provided, returns counts for ALL projects."""
        ch1 = self.create_channel("TG", "Channel 1", "ch1", org=self.org)
        ch2 = self.create_channel("TG", "Channel 2", "ch2", org=self.org2)

        # Create counts for both orgs
        ChannelCount.objects.create(
            channel=ch1, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=10
        )
        ChannelCount.objects.create(
            channel=ch1, count_type=ChannelCount.OUTGOING_MSG_TYPE, day=date(2026, 1, 1), count=5
        )
        ChannelCount.objects.create(
            channel=ch2, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=20
        )
        ChannelCount.objects.create(
            channel=ch2, count_type=ChannelCount.OUTGOING_MSG_TYPE, day=date(2026, 1, 1), count=15
        )

        # Explicitly pass date filters to test aggregation across projects
        resp = self.client.get(f"{self.url}?after=2026-01-01&before=2026-01-01")
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data["incoming_amount"], 30)  # 10 + 20
        self.assertEqual(data["outgoing_amount"], 20)  # 5 + 15
        self.assertEqual(data["total_amount"], 50)  # 30 + 20

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_filters_by_project_uuid(self):
        """When project_uuid is provided, returns counts only for that project."""
        ch1 = self.create_channel("TG", "Channel 1", "ch1", org=self.org)
        ch2 = self.create_channel("TG", "Channel 2", "ch2", org=self.org2)

        ChannelCount.objects.create(
            channel=ch1, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=10
        )
        ChannelCount.objects.create(
            channel=ch2, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=999
        )

        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}&after=2026-01-01&before=2026-01-01")
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data["incoming_amount"], 10)  # Only org1's count
        self.assertEqual(data["outgoing_amount"], 0)
        self.assertEqual(data["total_amount"], 10)

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_nonexistent_project_uuid_returns_404(self):
        random_uuid = uuid.uuid4()
        resp = self.client.get(f"{self.url}?project_uuid={random_uuid}")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_date_filters(self):
        ch = self.create_channel("TG", "Channel", "ch", org=self.org)

        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 1), count=10
        )
        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 2), count=20
        )
        ChannelCount.objects.create(
            channel=ch, count_type=ChannelCount.INCOMING_MSG_TYPE, day=date(2026, 1, 3), count=30
        )

        # Filter by date range
        resp = self.client.get(f"{self.url}?after=2026-01-02&before=2026-01-02")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["incoming_amount"], 20)  # Only Jan 2

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_invalid_date_returns_400(self):
        resp = self.client.get(f"{self.url}?after=invalid-date")
        self.assertEqual(resp.status_code, 400)

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_unique_contacts_counts_distinct_contacts_in_period(self):
        """
        Unique contacts should count distinct contacts across the entire period,
        not sum of daily unique contacts.
        """
        contact1 = self.create_contact("Contact 1", phone="+5511999990001")
        contact2 = self.create_contact("Contact 2", phone="+5511999990002")
        contact3 = self.create_contact("Contact 3", phone="+5511999990003")

        # Contact 1 sends message on day 1
        self.create_incoming_msg(contact1, "Hello", created_on=datetime(2026, 1, 1, 12, 0, tzinfo=pytz.UTC))

        # Contact 1 and 2 send messages on day 2
        self.create_incoming_msg(contact1, "Hello again", created_on=datetime(2026, 1, 2, 12, 0, tzinfo=pytz.UTC))
        self.create_incoming_msg(contact2, "Hi", created_on=datetime(2026, 1, 2, 12, 0, tzinfo=pytz.UTC))

        # Contact 3 sends message on day 3
        self.create_incoming_msg(contact3, "Hey", created_on=datetime(2026, 1, 3, 12, 0, tzinfo=pytz.UTC))

        # For the full period (day 1-3): unique contacts = 3 (not 1+2+1=4)
        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}&after=2026-01-01&before=2026-01-03")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unique_contacts"], 3)

        # For day 1 only: unique contacts = 1
        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}&after=2026-01-01&before=2026-01-01")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unique_contacts"], 1)

        # For day 2 only: unique contacts = 2
        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}&after=2026-01-02&before=2026-01-02")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unique_contacts"], 2)

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_unique_contacts_only_counts_incoming_messages(self):
        """Unique contacts should only count contacts that SENT messages (direction=I)."""
        contact1 = self.create_contact("Contact 1", phone="+5511999990001")
        contact2 = self.create_contact("Contact 2", phone="+5511999990002")

        # Contact 1 sends a message (incoming)
        self.create_incoming_msg(contact1, "Hello", created_on=datetime(2026, 1, 1, 12, 0, tzinfo=pytz.UTC))

        # Contact 2 receives a message (outgoing) - should NOT be counted
        self.create_outgoing_msg(contact2, "Hi there", created_on=datetime(2026, 1, 1, 12, 0, tzinfo=pytz.UTC))

        resp = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}&after=2026-01-01&before=2026-01-01")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unique_contacts"], 1)  # Only contact1

    @skip_auth_and_permissions(INTERNAL_PROJECT_MESSAGE_COUNT_VIEW_PATH)
    def test_unique_contacts_across_all_projects(self):
        """When no project_uuid, counts unique contacts across all projects."""
        contact1 = self.create_contact("Contact 1", phone="+5511999990001", org=self.org)
        contact2 = self.create_contact("Contact 2", phone="+5511999990002", org=self.org2)

        self.create_incoming_msg(contact1, "Hello", created_on=datetime(2026, 1, 1, 12, 0, tzinfo=pytz.UTC))
        self.create_incoming_msg(contact2, "Hi", created_on=datetime(2026, 1, 1, 12, 0, tzinfo=pytz.UTC))

        resp = self.client.get(f"{self.url}?after=2026-01-01&before=2026-01-01")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unique_contacts"], 2)  # Both contacts from different orgs
