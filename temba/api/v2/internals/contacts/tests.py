from functools import wraps
from unittest.mock import MagicMock, patch
import uuid

from django.conf import settings
import pytz
from rest_framework import status
from rest_framework.response import Response

from django.contrib.auth import get_user_model
from django.test import override_settings

from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import ContactField
from temba.tests import TembaTest
from temba.tests.mailroom import mock_mailroom
from temba.tickets.models import Ticketer
from temba.tickets.types.wenichats.type import WeniChatsType

User = get_user_model()


CONTACT_FIELDS_ENDPOINT_PATH = "temba.api.v2.internals.contacts.views.InternalContactFieldsEndpoint"


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
