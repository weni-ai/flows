from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from temba.msgs.models import Msg
from temba.tests.base import TembaTest

User = get_user_model()


def _patch_auth(func):
    @patch(
        "temba.api.v2.internals.first_contacts.views.InternalFirstContactsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.first_contacts.views.InternalFirstContactsView.permission_classes",
        [],
    )
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


class TestInternalFirstContacts(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save()

        self.mock_user = MagicMock(spec=User)
        self.mock_user.is_authenticated = True
        self.mock_user.email = "mockuser@example.com"

    def _url(self, **params):
        base = reverse("internal_first_contacts")
        defaults = {
            "project_uuid": self.org.proj_uuid,
            "channel_uuid": self.channel.uuid,
            "after": "2026-01-01T00:00:00Z",
            "before": "2026-12-31T23:59:59Z",
        }
        defaults.update(params)
        qs = "&".join(f"{k}={v}" for k, v in defaults.items())
        return f"{base}?{qs}"

    @_patch_auth
    def test_first_contacts_success(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            self.create_incoming_msg(contact=contact, text="Hello", status="H", channel=self.channel)

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertIn("contact_urn", results[0])
            self.assertIn("first_created_on", results[0])

    @_patch_auth
    def test_first_contacts_distinct_per_urn(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            now = timezone.now()
            earlier = now - timezone.timedelta(hours=2)

            self.create_incoming_msg(
                contact=contact, text="First", status="H", channel=self.channel, created_on=earlier
            )
            self.create_incoming_msg(
                contact=contact, text="Second", status="H", channel=self.channel, created_on=now
            )

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)

    @_patch_auth
    def test_first_contacts_excludes_outgoing(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            self.create_outgoing_msg(contact=contact, text="Outgoing", status="S", channel=self.channel)

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)

    @_patch_auth
    def test_first_contacts_excludes_failed_errored(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            msg_f = self.create_incoming_msg(
                contact=contact, text="Failed", status=Msg.STATUS_FAILED, channel=self.channel
            )
            msg_e = self.create_incoming_msg(
                contact=contact, text="Errored", status=Msg.STATUS_ERRORED, channel=self.channel
            )

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)

    @_patch_auth
    def test_first_contacts_filters_by_channel(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            other_channel = self.create_channel("TG", "Telegram", "+250785551212")
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])

            self.create_incoming_msg(contact=contact, text="On other channel", status="H", channel=other_channel)

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)

    @_patch_auth
    def test_first_contacts_filters_by_date_range(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            old_date = timezone.now() - timezone.timedelta(days=365)

            self.create_incoming_msg(
                contact=contact, text="Old msg", status="H", channel=self.channel, created_on=old_date
            )

            after = (timezone.now() - timezone.timedelta(days=1)).isoformat()
            before = (timezone.now() + timezone.timedelta(days=1)).isoformat()

            response = self.client.get(self._url(after=after, before=before))

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)

    @_patch_auth
    def test_first_contacts_missing_project_uuid(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            url = (
                f"{reverse('internal_first_contacts')}"
                f"?channel_uuid={self.channel.uuid}&after=2026-01-01T00:00:00Z&before=2026-12-31T23:59:59Z"
            )
            response = self.client.get(url)

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "project_uuid is required"})

    @_patch_auth
    def test_first_contacts_invalid_project_uuid(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            response = self.client.get(self._url(project_uuid=uuid4()))

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"error": "Project not found"})

    @_patch_auth
    def test_first_contacts_missing_required_params(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            base = reverse("internal_first_contacts")
            proj = f"project_uuid={self.org.proj_uuid}"

            response = self.client.get(f"{base}?{proj}&after=2026-01-01&before=2026-12-31")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "channel_uuid is required"})

            response = self.client.get(f"{base}?{proj}&channel_uuid={self.channel.uuid}&before=2026-12-31")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "after is required"})

            response = self.client.get(f"{base}?{proj}&channel_uuid={self.channel.uuid}&after=2026-01-01")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "before is required"})

    @_patch_auth
    def test_first_contacts_pagination(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            for i in range(5):
                contact = self.create_contact(f"Contact{i}", urns=[f"tel:+25078800000{i}"])
                self.create_incoming_msg(contact=contact, text=f"Msg {i}", status="H", channel=self.channel)

            response = self.client.get(self._url() + "&limit=2")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data["results"]), 2)
            self.assertIsNotNone(data["next"])

            response2 = self.client.get(data["next"])
            self.assertEqual(response2.status_code, 200)
            self.assertEqual(len(response2.json()["results"]), 2)

    @_patch_auth
    def test_first_contacts_multiple_contacts(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact_a = self.create_contact("Alice", urns=["tel:+250788000001"])
            contact_b = self.create_contact("Bob", urns=["tel:+250788000002"])

            now = timezone.now()
            self.create_incoming_msg(
                contact=contact_a, text="Alice first", status="H", channel=self.channel,
                created_on=now - timezone.timedelta(hours=3),
            )
            self.create_incoming_msg(
                contact=contact_a, text="Alice second", status="H", channel=self.channel,
                created_on=now - timezone.timedelta(hours=1),
            )
            self.create_incoming_msg(
                contact=contact_b, text="Bob msg", status="H", channel=self.channel,
                created_on=now - timezone.timedelta(hours=2),
            )

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 2)
