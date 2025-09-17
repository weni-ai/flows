import datetime as dt
from functools import wraps
from unittest.mock import MagicMock, patch
import uuid

from django.conf import settings
import pytz
from rest_framework import status
from rest_framework.response import Response

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import ContactField
from temba.msgs.models import Msg
from temba.tests import TembaTest
from temba.tests.mailroom import mock_mailroom
from temba.tickets.models import Ticketer
from temba.tickets.types.wenichats.type import WeniChatsType

User = get_user_model()


CONTACT_FIELDS_ENDPOINT_PATH = "temba.api.v2.internals.contacts.views.InternalContactFieldsEndpoint"
CONTACTS_IMPORT_UPLOAD_PATH = "temba.api.v2.internals.contacts.views.ContactsImportUploadView"
CONTACTS_IMPORT_CONFIRM_PATH = "temba.api.v2.internals.contacts.views.ContactsImportConfirmView"
GROUPS_CONTACT_FIELDS_PATH = "temba.api.v2.internals.contacts.views.GroupsContactFieldsView"


def skip_authentication(endpoint_path: str):
    """
    Decorator to disable authentication and permission checks for a specific endpoint.
    :param endpoint_path: The path to the API endpoint where authentication and permissions should be skipped.
    """

    def decorator(func):
        @patch(f"{endpoint_path}.authentication_classes", [])
        @patch(f"{endpoint_path}.permission_classes", [])
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


class InternalContactViewTest(TembaTest):
    def test_request_without_token(self):
        url = "/api/v2/internals/contacts"
        response = self.client.post(url)

        self.assertEqual(response.status_code, 403)

    def test_request_with_invalid_token(self):
        url = "/api/v2/internals/contacts?token=invalidtoken"
        response = self.client.post(url)

        self.assertEqual(response.status_code, 403)

    def test_request_without_body(self):
        with override_settings(BILLING_FIXED_ACCESS_TOKEN="12345"):
            url = "/api/v2/internals/contacts?token=12345"
            response = self.client.post(url)

            self.assertEqual(response.status_code, 400)

    def test_get_contacts(self):
        with override_settings(BILLING_FIXED_ACCESS_TOKEN="12345"):
            contact1 = self.create_contact("Magnus", urns=["twitterid:123456"])
            contact2 = self.create_contact("Nakamura", urns=["whatsapp:5561123456789"])

            url = "/api/v2/internals/contacts?token=12345"
            response = self.client.post(
                url, data={"contacts": [str(contact1.uuid), str(contact2.uuid)]}, content_type="application/json"
            )
            data = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue("results" in data)
            self.assertEqual(len(data.get("results")), 2)

            self.assertContains(response, str(contact1.uuid))


class ListContactFieldsEndpointTest(TembaTest):
    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_get_contact_fields_without_project_returns_400(self):
        url = "/api/v2/internals/contacts_fields"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_get_contact_fields_with_non_existent_project_returns_404(self):
        url = "/api/v2/internals/contacts_fields?project=332035c8-0a85-44e7-bd1f-568a5afdb378"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_get_contact_fields_with_invalid_project_uuid_returns_404(self):
        url = "/api/v2/internals/contacts_fields?project=123"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_get_contact_fields_with_no_fields_returns_empty_list(self):
        url = f"/api/v2/internals/contacts_fields?project={self.org.proj_uuid}"
        response = self.client.get(url)

        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("results"), [])

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_get_contact_fields_with_field_returns_expected_list(self):
        ContactField.get_or_create(self.org, self.admin, "test1", value_type="T")

        url = f"/api/v2/internals/contacts_fields?project={self.org.proj_uuid}"
        response = self.client.get(url)

        data = response.json()
        expected_result = [{"key": "test1", "label": "Test1", "pinned": False, "value_type": "text"}]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("results"), expected_result)

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_get_contact_fields_with_multiple_fields(self):
        ContactField.get_or_create(self.org, self.admin, "test1", value_type="T")
        ContactField.get_or_create(self.org, self.admin, "test2", value_type="T")

        url = f"/api/v2/internals/contacts_fields?project={self.org.proj_uuid}"
        response = self.client.get(url)

        data = response.json()
        expected_result = [
            {"key": "test1", "label": "Test1", "pinned": False, "value_type": "text"},
            {"key": "test2", "label": "Test2", "pinned": False, "value_type": "text"},
        ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("results"), expected_result)

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_get_contact_fields_with_key_filter(self):
        ContactField.get_or_create(self.org, self.admin, "test1", value_type="T")

        url = f"/api/v2/internals/contacts_fields?project={self.org.proj_uuid}&key=test1"
        response = self.client.get(url)

        data = response.json()
        expected_result = [{"key": "test1", "label": "Test1", "pinned": False, "value_type": "text"}]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.get("results"), expected_result)


class UpdateContactFieldsViewTest(TembaTest):
    @patch.object(LambdaURLValidator, "protected_resource")
    def test_request_without_body(self, mock_protected_resource):
        url = "/api/v2/internals/update_contacts_fields"

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)
        response = self.client.patch(url)

        self.assertEqual(response.status_code, 400)

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_request_no_project(self, mock_protected_resource):

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"

        body = {
            "contact_urn": "Nick Name",
            "contact_fields": {"cpf": "12345678912"},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"project": ["This field is required."]})

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_request_incorrect_project(self, mock_protected_resource):

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"

        body = {
            "project": self.org.uuid,
            "contact_urn": "Nick Name",
            "contact_fields": {"cpf": "12345678912"},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"project": ["Project not found"]})

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_request_invalid_contact_urn(self, mock_protected_resource):

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"

        body = {
            "project": self.org.proj_uuid,
            "contact_urn": "ext:hello@hello.ign",
            "contact_fields": {"cpf": "12345678912"},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"contact_urn": ["Contact URN not found"]})

    @patch.object(LambdaURLValidator, "protected_resource")
    def test_request_no_contact_fields(self, mock_protected_resource):

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"

        body = {
            "project": self.org.proj_uuid,
            "contact_urn": "ext:hello@hello.ign",
            "contact_fields": {},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"contact_fields": ["contact_fields must not be an empty dictionary"]})

    @mock_mailroom
    @override_settings(INTERNAL_USER_EMAIL="super@user.com")
    @patch.object(LambdaURLValidator, "protected_resource")
    def test_success(self, mr_mocks, mock_protected_resource):
        self.create_contact("Rigbt", urns=["twitterid:0000000"])
        self.create_field("last_name", "Last name")

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"

        body = {
            "project": self.org.proj_uuid,
            "contact_urn": "twitterid:0000000",
            "contact_fields": {"last_name": "Cube"},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Contact fields updated successfully"})


class InternalContactFieldsEndpointTest(TembaTest):
    def setUp(self):
        super().setUp()
        User.objects.create(username="Mordecai", email="mordecai@msn.com")

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_request_without_body(self):
        url = "/api/v2/internals/contacts_fields"
        response = self.client.post(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Project not provided"})

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_project_not_found(self):
        url = "/api/v2/internals/contacts_fields"
        body = {
            "project": self.org.uuid,
            "label": "Nick Name",
            "value_type": "text",
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Project not found"})

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_user_not_found(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = False
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):

            url = "/api/v2/internals/contacts_fields"
            body = {
                "project": self.org.proj_uuid,
                "label": "Nick Name",
                "value_type": "text",
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"error": "User not found"})

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_serializer_error(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mordecai@msn.com"

        with patch("rest_framework.request.Request.user", mock_user):

            url = "/api/v2/internals/contacts_fields"
            body = {
                "project": self.org.proj_uuid,
                "label": "Nick Name",
                "value_type": "T",
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 400)

    @skip_authentication(endpoint_path=CONTACT_FIELDS_ENDPOINT_PATH)
    def test_success(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mordecai@msn.com"

        with patch("rest_framework.request.Request.user", mock_user):

            url = "/api/v2/internals/contacts_fields"
            body = {
                "project": self.org.proj_uuid,
                "label": "Nick Name",
                "value_type": "text",
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"label": "Nick Name", "value_type": "T"})


class InternalContactGroupsViewTest(TembaTest):
    @patch("temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes", [])
    @patch("temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes", [])
    def test_get_groups_success(self):
        # Cria grupos
        contact1 = self.create_contact("Alice")
        contact2 = self.create_contact("Bob")
        group1 = self.create_group("Group 1", contacts=[contact1, contact2])
        group2 = self.create_group("Group 2")
        group3 = self.create_group("Group 3", contacts=[contact1])

        url = f"/api/v2/internals/contact_groups?project={self.org.proj_uuid}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        results = data["results"]
        # Should return all created groups
        group_uuids = {str(group1.uuid), str(group2.uuid), str(group3.uuid)}
        self.assertEqual(set(r["uuid"] for r in results), group_uuids)
        # Check main fields
        for r in results:
            self.assertIn("id", r)
            self.assertIn("uuid", r)
            self.assertIn("name", r)
            self.assertIn("status", r)
            self.assertIn("group_type", r)
            self.assertIn("query", r)
            self.assertIn("member_count", r)
        # Check member_count
        for r in results:
            if r["uuid"] == str(group1.uuid):
                self.assertEqual(r["member_count"], 2)
            elif r["uuid"] == str(group2.uuid):
                self.assertEqual(r["member_count"], 0)
            elif r["uuid"] == str(group3.uuid):
                self.assertEqual(r["member_count"], 1)

    @patch("temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes", [])
    @patch("temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes", [])
    def test_get_groups_no_project(self):
        url = "/api/v2/internals/contact_groups"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Project not provided"})

    @patch("temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes", [])
    @patch("temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes", [])
    def test_get_groups_project_not_found(self):
        url = "/api/v2/internals/contact_groups?project=00000000-0000-0000-0000-000000000000"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Project not found"})


class HasOpenTicketViewTest(TembaTest):
    def test_missing_contact_urn_param(self):
        """Test that the endpoint returns 400 when contact_urn parameter is missing"""
        url = "/api/v2/internals/contact_has_open_ticket"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    def test_contact_not_found(self):
        """Test that the endpoint returns 404 when contact is not found"""
        url = "/api/v2/internals/contact_has_open_ticket?contact_urn=tel:1234567890"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_contact_without_open_ticket(self):
        """Test that the endpoint returns false when contact has no open tickets"""
        self.create_contact("Bob", urns=["tel:+1234567890"])

        url = f"/api/v2/internals/contact_has_open_ticket?contact_urn=tel:1234567890"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"has_open_ticket": False})

    def test_contact_with_open_ticket(self):
        """Test that the endpoint returns true when contact has an open ticket"""
        contact = self.create_contact("Bob", urns=["tel:+1234567890"])
        ticketer = Ticketer.create(self.org, self.admin, WeniChatsType.slug, "bob@acme.com", {})
        self.create_ticket(ticketer, contact, "Test ticket")

        url = f"/api/v2/internals/contact_has_open_ticket?contact_urn=tel:1234567890"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"has_open_ticket": True})

    def test_contact_with_closed_ticket(self):
        """Test that the endpoint returns false when contact has only closed tickets"""
        contact = self.create_contact("Bob", urns=["tel:+1234567890"])
        ticketer = Ticketer.create(self.org, self.admin, WeniChatsType.slug, "bob@acme.com", {})

        ticket = self.create_ticket(ticketer, contact, "Test ticket")
        ticket.status = "C"
        ticket.save()

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "C")

        url = f"/api/v2/internals/contact_has_open_ticket?contact_urn=tel:1234567890"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"has_open_ticket": False})


class ContactsWithMessagesViewTest(TembaTest):
    url = "/api/v2/internals/contacts_with_messages"

    def setUp(self):
        super().setUp()
        self.start = dt.datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        self.end = dt.datetime(2025, 1, 2, 23, 59, tzinfo=timezone.utc)
        self.contact1 = super().create_contact("Alice", urns=["tel:+1111111111"])
        self.contact1.created_on = self.start
        self.contact1.save(update_fields=["created_on"])
        self.contact2 = super().create_contact("Bob", urns=["tel:+2222222222"])
        self.contact2.created_on = self.start
        self.contact2.save(update_fields=["created_on"])
        self.contact3 = super().create_contact("Carol", urns=["tel:+3333333333"])
        self.contact3.created_on = self.start
        self.contact3.save(update_fields=["created_on"])

    def _create_contact_with_created_on(self, name, urns, created_on):
        contact = super().create_contact(name, urns=urns)
        contact.created_on = created_on
        contact.save(update_fields=["created_on"])
        return contact

    def create_msg(self, contact, text, created_on):
        return Msg.objects.create(org=self.org, contact=contact, text=text, created_on=created_on, direction="I")

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_missing_params(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_project_not_found(self):
        resp = self.client.get(
            self.url,
            {"project": "00000000-0000-0000-0000-000000000000", "start_date": "2025-01-01", "end_date": "2025-01-02"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.json())

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_only_contacts_with_multiple_msgs(self):
        # contact1: 2 msgs, contact2: 1 msg, contact3: 0 msgs
        self.create_msg(self.contact1, "msg1", self.start)
        self.create_msg(self.contact1, "msg2", self.end)
        self.create_msg(self.contact2, "msg3", self.start)
        resp = self.client.get(
            self.url, {"project": str(self.org.proj_uuid), "start_date": "2025-01-01", "end_date": "2025-01-02"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"] if "results" in resp.json() else resp.json()

        self.assertEqual(len(data), 2)
        contact_ids = {c["contact_id"] for c in data}
        self.assertIn(self.contact1.id, contact_ids)
        self.assertIn(self.contact2.id, contact_ids)
        self.assertNotIn(self.contact3.id, contact_ids)

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_returns_all_msgs_for_qualified_contacts(self):
        self.create_msg(self.contact1, "msg1", self.start)
        self.create_msg(self.contact1, "msg2", self.end)
        self.create_msg(self.contact1, "msg3", self.end)
        resp = self.client.get(
            self.url, {"project": str(self.org.proj_uuid), "start_date": "2025-01-01", "end_date": "2025-01-02"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"] if "results" in resp.json() else resp.json()

        self.assertEqual(len(data), 1)
        contact_ids = {c["contact_id"] for c in data}
        self.assertIn(self.contact1.id, contact_ids)
        contact1_data = next(c for c in data if c["contact_id"] == self.contact1.id)
        self.assertEqual(len(contact1_data["messages"]), 3)

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_pagination_limit(self):
        # create 3 contacts with 2 msgs each, all with created_on dentro do período
        cts = [self._create_contact_with_created_on(f"C{i}", [f"tel:+{i}"], self.start) for i in range(10, 13)]
        for c in cts:
            self.create_msg(c, "a", self.start)
            self.create_msg(c, "b", self.end)
        resp = self.client.get(
            self.url,
            {"project": str(self.org.proj_uuid), "start_date": "2025-01-01", "end_date": "2025-01-02", "limit": 2},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"] if "results" in resp.json() else resp.json()
        self.assertEqual(len(data), 2)

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_accepts_datetime_and_date(self):
        self.create_msg(self.contact1, "msg1", self.start)
        self.create_msg(self.contact1, "msg2", self.end)
        # date only
        resp1 = self.client.get(
            self.url, {"project": str(self.org.proj_uuid), "start_date": "2025-01-01", "end_date": "2025-01-02"}
        )
        # datetime
        resp2 = self.client.get(
            self.url,
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01T00:00:00Z",
                "end_date": "2025-01-02T23:59:59Z",
            },
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(len(resp1.json()["results"] if "results" in resp1.json() else resp1.json()), 1)
        self.assertEqual(len(resp2.json()["results"] if "results" in resp2.json() else resp2.json()), 1)

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_invalid_date_format(self):
        resp = self.client.get(
            self.url, {"project": str(self.org.proj_uuid), "start_date": "2025-01-01", "end_date": "not-a-date"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())
        self.assertIn("Invalid date format", resp.json()["error"])

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_missing_start_or_end_date(self):
        # missing start_date
        resp1 = self.client.get(self.url, {"project": str(self.org.proj_uuid), "end_date": "2025-01-02"})
        self.assertEqual(resp1.status_code, 400)
        self.assertIn("error", resp1.json())
        self.assertIn("start_date and end_date are required", resp1.json()["error"])
        # missing end_date
        resp2 = self.client.get(self.url, {"project": str(self.org.proj_uuid), "start_date": "2025-01-01"})
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("error", resp2.json())
        self.assertIn("start_date and end_date are required", resp2.json()["error"])

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_accepts_naive_datetime(self):
        self.create_msg(self.contact1, "msg1", self.start)
        self.create_msg(self.contact1, "msg2", self.end)
        # naive datetime (no timezone info)
        resp = self.client.get(
            self.url,
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01T00:00:00",
                "end_date": "2025-01-02T23:59:59",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"] if "results" in resp.json() else resp.json()
        self.assertEqual(len(data), 1)
        contact_ids = {c["contact_id"] for c in data}
        self.assertIn(self.contact1.id, contact_ids)
        contact1_data = next(c for c in data if c["contact_id"] == self.contact1.id)
        self.assertEqual(len(contact1_data["messages"]), 2)

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_no_contacts_with_msgs_in_period(self):
        resp = self.client.get(
            self.url,
            {"project": str(self.org.proj_uuid), "start_date": "2025-01-01", "end_date": "2025-01-02"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"] if "results" in resp.json() else resp.json()
        self.assertEqual(len(data), 0)


class ContactsImportUploadViewTest(TembaTest):
    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    def test_upload_returns_examples_for_each_column(self):
        # Ensure a matching field exists so "Field:Team" maps to type "field"
        ContactField.get_or_create(self.org, self.admin, key="team")

        csv_content = (
            "URN:whatsapp,Name,Field:Team,Field:NewThing\n"
            "5561987654321,Alice,A-Team,Hello\n"
            "556188888888,Bob,B-Team,World\n"
        ).encode("utf-8")

        upload = SimpleUploadedFile("import.csv", csv_content, content_type="text/csv")

        url = "/api/v2/internals/contacts_import_upload"
        resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("columns", data)
        self.assertEqual(data.get("num_records"), 2)

        cols = data["columns"]
        # URN column
        self.assertEqual(cols[0]["header"], "URN:whatsapp")
        self.assertEqual(cols[0]["type"], "urn")
        self.assertIsNone(cols[0]["matched_field"])
        self.assertEqual(cols[0]["example"], "5561987654321")
        # Name column
        self.assertEqual(cols[1]["header"], "Name")
        self.assertEqual(cols[1]["type"], "attribute")
        self.assertEqual(cols[1]["matched_field"], "name")
        self.assertEqual(cols[1]["example"], "Alice")
        # Field:Team column (existing field)
        self.assertEqual(cols[2]["header"], "Field:Team")
        self.assertEqual(cols[2]["type"], "field")
        self.assertEqual(cols[2]["matched_field"], "team")
        self.assertEqual(cols[2]["example"], "A-Team")
        # Field:NewThing column (new_field)
        self.assertEqual(cols[3]["header"], "Field:NewThing")
        self.assertEqual(cols[3]["type"], "new_field")
        self.assertIn("suggested_type", cols[3])
        self.assertEqual(cols[3]["example"], "Hello")

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    def test_examples_skip_blanks_and_explicit_clear(self):
        ContactField.get_or_create(self.org, self.admin, key="team")

        csv_content = ("URN:whatsapp,Field:Team,Field:EmptyTest\n" ",, -- \n" "12345,B, Y \n").encode("utf-8")

        upload = SimpleUploadedFile("import.csv", csv_content, content_type="text/csv")

        url = "/api/v2/internals/contacts_import_upload"
        resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})

        self.assertEqual(resp.status_code, 200)
        cols = resp.json()["columns"]

        # First row blanks should be skipped, explicit clear (--) skipped too, so pick from second row
        self.assertEqual(cols[0]["example"], "12345")
        self.assertEqual(cols[1]["example"], "B")
        self.assertEqual(cols[2]["example"], "Y")


class ContactsImportConfirmViewTest(TembaTest):
    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_missing_params(self):
        url = "/api/v2/internals/contacts_import_confirm/"
        # no import_id in URL
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)  # no matching route without import_id

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_import_not_found(self):
        url = "/api/v2/internals/contacts_import_confirm/9999/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
        # Either route 404 or view 404, both acceptable. If view is hit, expect JSON error.

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_project_mismatch(self):
        # not applicable anymore since GET doesn't accept project_uuid; ensure it forbids non-confirmer
        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_success_returns_info(self):
        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        # simulate that the current user confirmed (modified_by)
        contact_import.modified_by = self.user
        contact_import.save(update_fields=["modified_by"])
        # force request.user to be the confirmer
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = self.user.id
        with patch("rest_framework.request.Request.user", mock_user):
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ("status", "num_created", "num_updated", "num_errored", "errors", "time_taken"):
            self.assertIn(key, data)
class GroupsContactFieldsViewTest(TembaTest):
    url = "/api/v2/internals/groups_contact_fields"

    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_missing_params(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_missing_group_ids(self):
        resp = self.client.get(self.url, {"project_uuid": str(self.org.proj_uuid)})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("group_ids not provided", resp.json().get("error", ""))

    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_invalid_project(self):
        resp = self.client.get(self.url, {"project_uuid": "00000000-0000-0000-0000-000000000000", "group_ids": "1"})
        self.assertEqual(resp.status_code, 404)

    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_group_ids_must_be_integers(self):
        resp = self.client.get(self.url, {"project_uuid": str(self.org.proj_uuid), "group_ids": "abc,2"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("must contain only integers", resp.json().get("error", ""))

    @mock_mailroom
    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_dynamic_group_fields_included_with_null_example(self, mr_mocks):
        # create a user field and dynamic group referencing it
        team5 = self.create_field("team5", "Team5")
        query = 'team5 = "YES"'
        mr_mocks.parse_query(query, fields=[team5])

        dyn = self.create_group("DynTeam5", query=query)

        # call endpoint
        resp = self.client.get(
            self.url,
            {"project_uuid": str(self.org.proj_uuid), "group_ids": str(dyn.id)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"]
        keys = {f["key"] for f in data}
        self.assertIn("team5", keys)
        team5_item = next(i for i in data if i["key"] == "team5")
        self.assertIn("example", team5_item)
        self.assertIsNone(team5_item["example"])  # no contacts with value -> example null

    @mock_mailroom
    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_static_group_fields_from_contacts(self, mr_mocks):
        # create field and contact with that field value
        team3 = self.create_field("team3", "Team3")
        contact = self.create_contact("Alice", urns=["tel:+111"])
        mods = contact.update_fields({team3: "Opa"})
        contact.modify(self.admin, mods)

        # create static group with the contact
        grp = self.create_group("StaticGrp", contacts=[contact])

        # call endpoint
        resp = self.client.get(
            self.url,
            {"project_uuid": str(self.org.proj_uuid), "group_ids": str(grp.id)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"]
        keys = {f["key"] for f in data}
        self.assertIn("team3", keys)
        team3_item = next(i for i in data if i["key"] == "team3")
        self.assertEqual(team3_item["example"], "Opa")

    @mock_mailroom
    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_union_across_multiple_groups(self, mr_mocks):
        # dynamic group with team5
        team5 = self.create_field("team5", "Team5")
        q = 'team5 = "YES"'
        mr_mocks.parse_query(q, fields=[team5])
        dyn = self.create_group("DynTeam5", query=q)

        # static group with team3 value
        team3 = self.create_field("team3", "Team3")
        c = self.create_contact("Bob", urns=["tel:+222"])
        mods = c.update_fields({team3: "Opa"})
        c.modify(self.admin, mods)
        stat = self.create_group("StatTeam3", contacts=[c])

        gids = f"{dyn.id},{stat.id}"
        resp = self.client.get(
            self.url,
            {"project_uuid": str(self.org.proj_uuid), "group_ids": gids},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"]
        keys = {f["key"] for f in data}
        self.assertIn("team5", keys)
        self.assertIn("team3", keys)

    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_group_ids_only_separators(self):
        resp = self.client.get(
            self.url,
            {"project_uuid": str(self.org.proj_uuid), "group_ids": ",,,"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("comma-separated list of integers", resp.json().get("error", ""))

    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_no_groups_found(self):
        resp = self.client.get(
            self.url,
            {"project_uuid": str(self.org.proj_uuid), "group_ids": "999999,888888"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("No groups found", resp.json().get("error", ""))

    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_accepts_project_alias(self):
        grp = self.create_group("AliasProjectGrp")
        resp = self.client.get(
            self.url,
            {"project": str(self.org.proj_uuid), "group_ids": str(grp.id)},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.json())

    @mock_mailroom
    @skip_authentication(endpoint_path=GROUPS_CONTACT_FIELDS_PATH)
    def test_loop_branches_break_and_continue(self, mr_mocks):
        # two fields and three contacts; values found on first two contacts
        # ensure inner-loop 'continue' and outer-loop 'break' are exercised
        team3 = self.create_field("team3", "Team3")
        team5 = self.create_field("team5", "Team5")

        c1 = self.create_contact("C1", urns=["tel:+100"])
        mods1 = c1.update_fields({team3: "V1"})
        c1.modify(self.admin, mods1)

        c2 = self.create_contact("C2", urns=["tel:+200"])
        mods2 = c2.update_fields({team5: "V2"})
        c2.modify(self.admin, mods2)

        c3 = self.create_contact("C3", urns=["tel:+300"])  # no relevant fields

        grp = self.create_group("LoopBranchesGrp", contacts=[c1, c2, c3])

        resp = self.client.get(
            self.url,
            {"project_uuid": str(self.org.proj_uuid), "group_ids": str(grp.id)},
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        keys = {i["key"] for i in results}
        self.assertIn("team3", keys)
        self.assertIn("team5", keys)
        team3_item = next(i for i in results if i["key"] == "team3")
        team5_item = next(i for i in results if i["key"] == "team5")
        self.assertEqual(team3_item["example"], "V1")
        self.assertEqual(team5_item["example"], "V2")
