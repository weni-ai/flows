import datetime as dt
from functools import wraps
from unittest.mock import MagicMock, patch

from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
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


def create_simple_csv_upload_for_test():
    """Helper to create simple CSV upload for testing"""
    csv_content = ("URN:whatsapp,Name\n" "5561987654321,Alice\n").encode("utf-8")
    return SimpleUploadedFile("import.csv", csv_content, content_type="text/csv")


def setup_contact_import_test_data(test_instance):
    """Helper to setup contact import test data"""
    contact_import = test_instance.create_contact_import("media/test_imports/simple.xlsx")
    contact_import.mappings = [
        {
            "header": "Field:Nick Name",
            "mapping": {"type": "new_field", "key": "nickname"},
        }
    ]
    contact_import.save(update_fields=["mappings"])
    return contact_import


def create_dummy_form_class():
    """Helper to create dummy form class for testing"""

    class DummyForm:
        GROUP_MODE_NEW = "new"

        def __init__(self, data, org=None, instance=None):
            self.instance = instance
            self.cleaned_data = {"add_to_group": False}

        def is_valid(self):
            return True

        def get_form_values(self):
            return [{"include": True, "name": "Nick Name", "value_type": "T"}]

    return DummyForm


def create_fake_s3_classes():
    """Helper to create fake S3 classes for testing"""

    class FakeS3Client:
        def __init__(self, should_raise=False):
            self.should_raise = should_raise

        def upload_fileobj(self, *args, **kwargs):
            if self.should_raise:
                raise RuntimeError("nope")
            return None

        def generate_presigned_url(self, *args, **kwargs):
            return "/downloads/dups.xlsx"

    class FakeBoto3:
        @staticmethod
        def client(*args, **kwargs):
            return FakeS3Client(should_raise=kwargs.get("should_raise", False))

    return FakeS3Client, FakeBoto3


def create_failing_fake_s3_classes():
    """Helper to create fake S3 classes that always fail for testing"""

    class FakeS3Client:
        def upload_fileobj(self, *args, **kwargs):
            raise RuntimeError("nope")

        def generate_presigned_url(self, *args, **kwargs):
            return "/downloads/dups.xlsx"

    class FakeBoto3:
        @staticmethod
        def client(*args, **kwargs):
            return FakeS3Client()

    return FakeS3Client, FakeBoto3


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
                url,
                data={"contacts": [str(contact1.uuid), str(contact2.uuid)]},
                content_type="application/json",
            )
            data = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue("results" in data)
            self.assertEqual(len(data.get("results")), 2)

            self.assertContains(response, str(contact1.uuid))


class ContactsExportByStatusViewTest(TembaTest):
    @patch("temba.api.v2.internals.contacts.views.ContactsExportByStatusView.authentication_classes", [])
    @patch("temba.api.v2.internals.contacts.views.ContactsExportByStatusView.permission_classes", [])
    def test_export_contacts_by_status_enqueues_and_responds(self):
        # use DRF APIClient to force authenticate a real user without OIDC
        client = APIClient()
        client.force_authenticate(user=self.admin)
        c1 = self.create_contact("C1", urns=["tel:+112"])
        c2 = self.create_contact("C2", urns=["tel:+113"])
        main = self.create_contact("A", urns=["tel:+111"])
        broadcast = self.create_broadcast(self.admin, "hi", contacts=[main, c1, c2])
        # mark only c1 and c2 as delivered for this broadcast
        broadcast.msgs.filter(contact_id__in=[c1.id, c2.id]).update(status=Msg.STATUS_DELIVERED)

        url = "/api/v2/internals/contacts_export_by_status"
        with patch("temba.api.v2.internals.contacts.views.on_transaction_commit", side_effect=lambda fn: fn()), patch(
            "temba.api.v2.internals.contacts.views.export_contacts_by_status_task.delay"
        ) as mock_delay:
            resp = client.post(
                url,
                data={
                    "project_uuid": str(self.org.proj_uuid),
                    "broadcast_id": broadcast.id,
                    "status": Msg.STATUS_DELIVERED,
                },
                format="json",
            )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("export_id", data)
        self.assertIn("message", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 2)
        mock_delay.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("temba.api.v2.internals.contacts.views.ContactsExportByStatusView.authentication_classes", [])
    @patch("temba.api.v2.internals.contacts.views.ContactsExportByStatusView.permission_classes", [])
    def test_export_contacts_by_status_builds_file_eager(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        c1 = self.create_contact("X1", urns=["tel:+115"])
        c2 = self.create_contact("X2", urns=["tel:+116"])
        main = self.create_contact("B", urns=["tel:+114"])
        broadcast = self.create_broadcast(self.admin, "hi", contacts=[main, c1, c2])
        broadcast.msgs.filter(contact_id__in=[c1.id, c2.id]).update(status=Msg.STATUS_DELIVERED)

        url = "/api/v2/internals/contacts_export_by_status"
        resp = client.post(
            url,
            data={
                "project_uuid": str(self.org.proj_uuid),
                "broadcast_id": broadcast.id,
                "status": Msg.STATUS_DELIVERED,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIsNotNone(data.get("export_id"))
        # In eager mode the view fills download_url immediately
        self.assertTrue("download_url" in data)


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
        self.assertEqual(
            response.json(),
            {"contact_fields": ["contact_fields must not be an empty dictionary"]},
        )

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

    @mock_mailroom
    @override_settings(INTERNAL_USER_EMAIL="super@user.com")
    @patch.object(LambdaURLValidator, "protected_resource")
    def test_update_contact_name(self, mr_mocks, mock_protected_resource):
        contact = self.create_contact("Old Name", urns=["twitterid:11111"])

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"
        body = {
            "project": self.org.proj_uuid,
            "contact_urn": "twitterid:11111",
            "contact_fields": {"name": "New Name"},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Contact fields updated successfully"})

        # verify if the name was updated
        contact.refresh_from_db()
        self.assertEqual(contact.name, "New Name")

    @mock_mailroom
    @override_settings(INTERNAL_USER_EMAIL="super@user.com")
    @patch.object(LambdaURLValidator, "protected_resource")
    def test_update_contact_language(self, mr_mocks, mock_protected_resource):
        contact = self.create_contact("Rigbt", urns=["twitterid:22222"])

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"
        body = {
            "project": self.org.proj_uuid,
            "contact_urn": "twitterid:22222",
            "contact_fields": {"language": "es"},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Contact fields updated successfully"})

        contact.refresh_from_db()
        self.assertEqual(contact.language, "es")

    @mock_mailroom
    @override_settings(INTERNAL_USER_EMAIL="super@user.com")
    @patch.object(LambdaURLValidator, "protected_resource")
    def test_update_contact_name_and_custom_field(self, mr_mocks, mock_protected_resource):
        contact = self.create_contact("Old Name", urns=["twitterid:33333"])
        self.create_field("nickname", "Apelido")

        mock_protected_resource.return_value = Response({"message": "Access granted!"}, status=status.HTTP_200_OK)

        url = "/api/v2/internals/update_contacts_fields"
        body = {
            "project": self.org.proj_uuid,
            "contact_urn": "twitterid:33333",
            "contact_fields": {"name": "Novo Nome", "nickname": "Felix"},
        }

        response = self.client.patch(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Contact fields updated successfully"})

        contact.refresh_from_db()
        self.assertEqual(contact.name, "Novo Nome")
        nickname_field = ContactField.get_by_key(contact.org, "nickname")
        self.assertEqual(contact.get_field_display(nickname_field), "Felix")


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
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_get_groups_success(self):
        # Cria grupos
        contact1 = self.create_contact("Alice")
        contact2 = self.create_contact("Bob")
        group1 = self.create_group("Group 1", contacts=[contact1, contact2])
        group3 = self.create_group("Group 3", contacts=[contact1])
        self.create_group("Group 2")

        url = f"/api/v2/internals/contact_groups?project_uuid={self.org.proj_uuid}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        results = data["results"]
        # Should return only groups with members
        group_uuids = {str(group1.uuid), str(group3.uuid)}
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
            elif r["uuid"] == str(group3.uuid):
                self.assertEqual(r["member_count"], 1)

    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_get_groups_no_project(self):
        url = "/api/v2/internals/contact_groups"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Project not provided"})

    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_get_groups_project_not_found(self):
        url = "/api/v2/internals/contact_groups?project_uuid=00000000-0000-0000-0000-000000000000"
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
        return Msg.objects.create(
            org=self.org,
            contact=contact,
            text=text,
            created_on=created_on,
            direction="I",
        )

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_missing_params(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_project_not_found(self):
        resp = self.client.get(
            self.url,
            {
                "project": "00000000-0000-0000-0000-000000000000",
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
            },
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
            self.url,
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
            },
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
            self.url,
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
            },
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
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
                "limit": 2,
            },
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
            self.url,
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
            },
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
        self.assertEqual(
            len(resp1.json()["results"] if "results" in resp1.json() else resp1.json()),
            1,
        )
        self.assertEqual(
            len(resp2.json()["results"] if "results" in resp2.json() else resp2.json()),
            1,
        )

    @skip_authentication(endpoint_path="temba.api.v2.internals.contacts.views.ContactsWithMessagesView")
    def test_invalid_date_format(self):
        resp = self.client.get(
            self.url,
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01",
                "end_date": "not-a-date",
            },
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
            {
                "project": str(self.org.proj_uuid),
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
            },
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
    @override_settings(INTERNAL_USER_EMAIL="internal@system.local")
    def test_upload_created_by_falls_back_to_internal_user(self):
        # Ensure internal user exists
        User.objects.create_user("internal@system.local", "internal@system.local")

        upload = create_simple_csv_upload_for_test()

        # Unauthenticated request to force fallback path
        with patch("rest_framework.request.Request.user") as mock_req_user:
            mock_req_user.is_authenticated = False
            url = "/api/v2/internals/contacts_import_upload"
            resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})

        self.assertEqual(resp.status_code, 200)
        # Verify ContactImport was created with created_by set to internal user
        from temba.contacts.models import ContactImport as ContactImportModel

        contact_import = ContactImportModel.objects.order_by("-id").first()
        self.assertIsNotNone(contact_import)
        self.assertIsNotNone(contact_import.created_by)
        self.assertEqual(contact_import.created_by.email, "internal@system.local")

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    @override_settings(INTERNAL_USER_EMAIL="internal-missing@system.local")
    def test_upload_created_by_fallback_missing_internal_user(self):
        # No user with INTERNAL_USER_EMAIL; ensure org.created_by is used as last resort
        # Remove created_by/modified_by on org to ensure branch picks at least one available attr safely
        # Many factories set both; here we just assert that created_by is set and not None after upload

        upload = create_simple_csv_upload_for_test()

        with patch("rest_framework.request.Request.user") as mock_req_user:
            mock_req_user.is_authenticated = False
            url = "/api/v2/internals/contacts_import_upload"
            resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})

        self.assertEqual(resp.status_code, 200)

        from temba.contacts.models import ContactImport as ContactImportModel

        contact_import = ContactImportModel.objects.order_by("-id").first()
        self.assertIsNotNone(contact_import)
        # When internal user not found, view falls back to org.created_by or modified_by
        self.assertIsNotNone(contact_import.created_by)

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

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    def test_upload_missing_params_returns_400(self):
        url = "/api/v2/internals/contacts_import_upload"
        # missing both project_uuid and file
        resp = self.client.post(url, {})
        self.assertEqual(resp.status_code, 400)

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    def test_upload_validation_error_from_service(self):
        # header with empty column should trigger validation error in service
        csv_content = ("Name,,URN:whatsapp\n" "Alice,,5561987654321\n").encode("utf-8")
        upload = SimpleUploadedFile("import.csv", csv_content, content_type="text/csv")
        url = "/api/v2/internals/contacts_import_upload"
        resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    def test_upload_general_exception_is_caught(self):
        # Force general exception inside process
        with patch(
            "temba.api.v2.internals.contacts.views.ContactImportDeduplicationService.process",
            side_effect=Exception("boom"),
        ):
            upload = SimpleUploadedFile("import.csv", b"URN:whatsapp\n123\n", content_type="text/csv")
            url = "/api/v2/internals/contacts_import_upload"
            resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Error parsing file", resp.json().get("error", ""))

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    @override_settings(AWS_STORAGE_BUCKET_NAME="bucket-xyz")
    def test_upload_duplicates_s3_success_and_absolute_url(self):
        # build CSV with duplicate URN to ensure duplicates workbook is generated
        csv_content = ("URN:whatsapp,Name\n" "5561987654321,Alice\n" "5561987654321,Bob\n").encode("utf-8")
        upload = SimpleUploadedFile("import.csv", csv_content, content_type="text/csv")

        _, FakeBoto3 = create_fake_s3_classes()

        with patch.dict("sys.modules", {"boto3": FakeBoto3}):
            url = "/api/v2/internals/contacts_import_upload"
            resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("duplicates", data)
        self.assertIsNotNone(data["duplicates"])  # duplicates exist
        # absolute URL conversion should have been applied
        self.assertTrue(str(data["duplicates"]["download_url"]).lower().startswith("http"))
        self.assertEqual(data["duplicates"]["error"], None)

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    @override_settings(AWS_STORAGE_BUCKET_NAME="bucket-xyz")
    def test_upload_duplicates_s3_failure_sets_error(self):
        csv_content = ("URN:whatsapp,Name\n" "5561987654321,Alice\n" "5561987654321,Bob\n").encode("utf-8")
        upload = SimpleUploadedFile("import.csv", csv_content, content_type="text/csv")

        _, FakeBoto3 = create_failing_fake_s3_classes()

        with patch.dict("sys.modules", {"boto3": FakeBoto3}):
            url = "/api/v2/internals/contacts_import_upload"
            resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("duplicates", data)
        self.assertIsNotNone(data["duplicates"])  # duplicates exist
        self.assertIn("S3 upload/presign failed", data["duplicates"]["error"])


class ContactImportDeduplicationServiceTest(TembaTest):
    def test_process_empty_file_raises(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        upload = SimpleUploadedFile("import.csv", b"", content_type="text/csv")
        with self.assertRaises(ValidationError):
            ContactImportDeduplicationService.process(self.org, upload, upload.name)

    def test_process_empty_header_raises(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        upload = SimpleUploadedFile("import.csv", b"Name,,URN:whatsapp\n", content_type="text/csv")
        with self.assertRaises(ValidationError):
            ContactImportDeduplicationService.process(self.org, upload, upload.name)

    def test_process_header_only_no_records_raises(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        # headers present but no data rows should raise
        csv = ("UUID,URN:whatsapp,Name\n").encode("utf-8")
        upload = SimpleUploadedFile("import.csv", csv, content_type="text/csv")
        with self.assertRaises(ValidationError) as ctx:
            ContactImportDeduplicationService.process(self.org, upload, upload.name)
        self.assertIn("doesn't contain any records", str(ctx.exception))

    @override_settings(AWS_STORAGE_BUCKET_NAME=None)
    def test_process_duplicates_and_bucket_not_configured(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        # duplicate URN in second row
        csv = ("URN:whatsapp,Name\n" "123,Alice\n" "123,Bob\n").encode("utf-8")
        upload = SimpleUploadedFile("import.csv", csv, content_type="text/csv")
        (
            mappings,
            num_unique,
            dedup_tmp,
            ext,
            dup_url,
            dup_count,
            dup_error,
        ) = ContactImportDeduplicationService.process(self.org, upload, upload.name)
        self.assertEqual(num_unique, 1)
        self.assertEqual(dup_count, 1)
        self.assertIsNone(dup_url)
        self.assertEqual(dup_error, "AWS bucket not configured")

    def test_process_path_suffix_error_falls_back_to_csv(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        csv = ("URN:whatsapp\n" "123\n").encode("utf-8")
        upload = SimpleUploadedFile("weirdname", csv, content_type="text/plain")
        # Patch Path used in the module to raise and force fallback
        with patch(
            "temba.api.v2.internals.contacts.services.Path",
            side_effect=Exception("bad path"),
        ):
            (
                mappings,
                num_unique,
                dedup_tmp,
                ext,
                dup_url,
                dup_count,
                dup_error,
            ) = ContactImportDeduplicationService.process(self.org, upload, upload.name)
        self.assertEqual(num_unique, 1)
        self.assertEqual(ext, "xlsx")


class ContactImportDeduplicationServiceS3Test(TembaTest):
    def test_upload_to_s3_no_client(self):
        # Force _get_s3_client to return None
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        with patch(
            "temba.api.v2.internals.contacts.services.ContactImportDeduplicationService._get_s3_client",
            return_value=None,
        ):
            url, err = ContactImportDeduplicationService._upload_to_s3_and_presign(
                bucket="bucket", key="k", tmp_name=__file__, readable_name="x.xlsx"
            )
        self.assertIsNone(url)
        self.assertIn("AWS client not available", err)


class ContactImportDeduplicationServiceUUIDTest(TembaTest):
    def test_process_tracks_seen_uuids(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        # Build CSV with explicit UUID column and two unique rows
        csv = (
            "UUID,URN:whatsapp,Name\n"
            "11111111-1111-1111-1111-111111111111,123,Alice\n"
            "22222222-2222-2222-2222-222222222222,456,Bob\n"
        ).encode("utf-8")
        upload = SimpleUploadedFile("import.csv", csv, content_type="text/csv")
        (
            mappings,
            num_unique,
            dedup_tmp,
            ext,
            dup_url,
            dup_count,
            dup_error,
        ) = ContactImportDeduplicationService.process(self.org, upload, upload.name)
        self.assertEqual(num_unique, 2)
        self.assertEqual(dup_count, 0)

    def test_process_marks_duplicate_uuid_as_duplicate(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )

        # same UUID on two rows -> second one should be treated as duplicate
        csv = (
            "UUID,Name\n" "11111111-1111-1111-1111-111111111111,Alice\n" "11111111-1111-1111-1111-111111111111,Bob\n"
        ).encode("utf-8")
        upload = SimpleUploadedFile("import.csv", csv, content_type="text/csv")
        (
            mappings,
            num_unique,
            dedup_tmp,
            ext,
            dup_url,
            dup_count,
            dup_error,
        ) = ContactImportDeduplicationService.process(self.org, upload, upload.name)
        self.assertEqual(num_unique, 1)
        self.assertEqual(dup_count, 1)


class ContactImportDeduplicationServiceMaxRecordsTest(TembaTest):
    def test_process_raises_when_exceed_max_records(self):
        from temba.api.v2.internals.contacts.services import (
            ContactImportDeduplicationService,
        )
        from temba.contacts.models import ContactImport as ContactImportModel

        old_max = ContactImportModel.MAX_RECORDS
        try:
            ContactImportModel.MAX_RECORDS = 1
            csv = ("URN:whatsapp,Name\n" "123,Alice\n" "456,Bob\n").encode("utf-8")
            upload = SimpleUploadedFile("import.csv", csv, content_type="text/csv")
            with self.assertRaises(ValidationError):
                ContactImportDeduplicationService.process(self.org, upload, upload.name)
        finally:
            ContactImportModel.MAX_RECORDS = old_max


class ContactsImportUploadViewMiscTest(TembaTest):
    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    def test_project_not_found_returns_404(self):
        upload = SimpleUploadedFile("import.csv", b"URN:whatsapp\n123\n", content_type="text/csv")
        url = "/api/v2/internals/contacts_import_upload"
        resp = self.client.post(
            url,
            {"project_uuid": "00000000-0000-0000-0000-000000000000", "file": upload},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Project not found", resp.json().get("error", ""))

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_UPLOAD_PATH)
    def test_columns_unknown_type_branch(self):
        # Patch process to return a mapping with unknown type to hit the else branch
        fake_mappings = [
            {"header": "ColX", "mapping": {"type": "unknown"}},
        ]
        with patch(
            "temba.api.v2.internals.contacts.views.ContactImportDeduplicationService.process",
            return_value=(
                fake_mappings,
                1,
                SimpleUploadedFile("d.xlsx", b"x"),
                "xlsx",
                None,
                0,
                None,
            ),
        ), patch(
            "temba.api.v2.internals.contacts.views.ContactImportPreviewService.extract_examples",
            return_value=["eg"],
        ):
            upload = SimpleUploadedFile("import.csv", b"ColX\nval\n", content_type="text/csv")
            url = "/api/v2/internals/contacts_import_upload"
            resp = self.client.post(url, {"project_uuid": str(self.org.proj_uuid), "file": upload})
        self.assertEqual(resp.status_code, 200)
        cols = resp.json()["columns"]
        self.assertEqual(cols[0]["type"], "unknown")


class ContactsImportConfirmViewGetMoreTest(TembaTest):
    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_forbidden_when_user_differs(self):
        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        # make a different user as modified_by
        other = self.create_user("other@example.com")
        contact_import.modified_by = other
        contact_import.save(update_fields=["modified_by"])
        self.login(self.user)
        url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_group_serialization_includes_member_count(self):
        from temba.contacts.models import ContactGroup

        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        group = ContactGroup.create_static(self.org, self.admin, "Team A")
        # stamp current user as confirmer
        contact_import.modified_by = self.user
        contact_import.group = group
        contact_import.save(update_fields=["modified_by", "group"])
        self.login(self.user)
        url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
        with patch("rest_framework.request.Request.user", self.user):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("group", data)
        self.assertIn("member_count", data["group"])

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_authenticated_but_not_confirmer_returns_403(self):
        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        # set a different confirmer
        other = self.create_user("confirmer@example.com")
        contact_import.modified_by = other
        contact_import.save(update_fields=["modified_by"])

        # force an authenticated request.user with a different id
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 999999
        with patch("rest_framework.request.Request.user", mock_user):
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)


class ContactImportPreviewServiceTest(TembaTest):
    def test_extract_examples_empty_file(self):
        from temba.api.v2.internals.contacts.views import ContactImportPreviewService

        # empty file should return Nones and seek back to start
        file = SimpleUploadedFile("empty.csv", b"", content_type="text/csv")
        mappings = [
            {"header": "Name", "mapping": {"type": "attribute", "name": "name"}},
            {"header": "Field:Team", "mapping": {"type": "new_field", "key": "team"}},
        ]
        examples = ContactImportPreviewService.extract_examples(file, "empty.csv", mappings)
        self.assertEqual(examples, [None, None])

    def test_extract_examples_path_exception_falls_back_to_csv(self):
        from temba.api.v2.internals.contacts.views import ContactImportPreviewService

        file = SimpleUploadedFile("noext", b"URN:whatsapp\n123\n", content_type="text/plain")
        mappings = [
            {
                "header": "URN:whatsapp",
                "mapping": {"type": "scheme", "scheme": "whatsapp"},
            },
        ]
        with patch(
            "temba.api.v2.internals.contacts.views.Path",
            side_effect=Exception("bad path"),
        ):
            examples = ContactImportPreviewService.extract_examples(file, "noext", mappings)
        self.assertEqual(examples, ["123"])


class ContactsImportConfirmViewPostTest(TembaTest):
    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_post_success_new_group_and_stamp_confirmer(self):
        from temba.api.v2.internals.contacts.views import ContactImportCRUDL
        from temba.contacts.models import ContactImport

        # create a simple contact import with one new_field mapping
        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        contact_import.mappings = [
            {
                "header": "Field:Nick Name",
                "mapping": {"type": "new_field", "key": "nickname"},
            }
        ]
        contact_import.save(update_fields=["mappings"])

        # Dummy form to drive the POST flow
        class DummyForm:
            GROUP_MODE_NEW = "new"
            GROUP_MODE_EXISTING = "existing"

            def __init__(self, data, org=None, instance=None):
                self._data = data
                self.instance = instance
                self._errors = {}
                self.cleaned_data = {
                    "add_to_group": True,
                    "group_mode": self.GROUP_MODE_NEW,
                    "new_group_name": "My Group",
                }

            def is_valid(self):
                return True

            def get_form_values(self):
                # include update for our single mapping
                return [{"include": True, "name": "Nick Name", "value_type": "T"}]

            @property
            def errors(self):
                return self._errors

        with patch.object(ContactImportCRUDL.Preview, "form_class", DummyForm), patch.object(
            ContactImport, "start_async"
        ) as mock_start:
            # authenticate with a real user to populate request.user
            self.login(self.user)
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.post(
                url,
                {"project_uuid": str(self.org.proj_uuid)},
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        contact_import.refresh_from_db()
        # mapping should be updated with form values
        mapping = contact_import.mappings[0]["mapping"]
        self.assertEqual(mapping["name"], "Nick Name")
        self.assertEqual(mapping["value_type"], "T")
        self.assertEqual(contact_import.group_name, "My Group")
        self.assertEqual(contact_import.modified_by_id, self.user.id)
        mock_start.assert_called_once()

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_post_existing_group(self):
        from temba.api.v2.internals.contacts.views import ContactImportCRUDL
        from temba.contacts.models import ContactImport, ContactGroup

        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        contact_import.mappings = [{"header": "Name", "mapping": {"type": "attribute", "name": "name"}}]
        contact_import.save(update_fields=["mappings"])
        group = ContactGroup.create_static(self.org, self.admin, "Customers")

        class DummyForm:
            GROUP_MODE_NEW = "new"
            GROUP_MODE_EXISTING = "existing"

            def __init__(self, data, org=None, instance=None):
                self._data = data
                self.instance = instance
                self._errors = {}
                self.cleaned_data = {
                    "add_to_group": True,
                    "group_mode": self.GROUP_MODE_EXISTING,
                    "existing_group": group,
                }

            def is_valid(self):
                return True

            def get_form_values(self):
                return [{"include": True}]

            @property
            def errors(self):
                return self._errors

        with patch.object(ContactImportCRUDL.Preview, "form_class", DummyForm), patch.object(
            ContactImport, "start_async"
        ):
            self.login(self.user)
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.post(
                url,
                {"project_uuid": str(self.org.proj_uuid)},
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        contact_import.refresh_from_db()
        self.assertEqual(contact_import.group_id, group.id)

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_post_invalid_form_returns_400(self):
        from temba.api.v2.internals.contacts.views import ContactImportCRUDL

        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")

        class DummyForm:
            def __init__(self, *args, **kwargs):
                self._errors = {"columns": ["invalid"]}

            def is_valid(self):
                return False

            @property
            def errors(self):
                return self._errors

        with patch.object(ContactImportCRUDL.Preview, "form_class", DummyForm):
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.post(
                url,
                {"project_uuid": str(self.org.proj_uuid)},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_post_import_not_found_returns_404(self):
        url = "/api/v2/internals/contacts_import_confirm/999999/"
        resp = self.client.post(
            url,
            {"project_uuid": str(self.org.proj_uuid)},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    @override_settings(INTERNAL_USER_EMAIL="internal@example.com")
    def test_post_confirmer_fallback_to_internal_user(self):
        from temba.api.v2.internals.contacts.views import ContactImportCRUDL

        # ensure internal user exists
        User.objects.create_user("internal@example.com", "internal@example.com")

        contact_import = setup_contact_import_test_data(self)
        DummyForm = create_dummy_form_class()

        with patch.object(ContactImportCRUDL.Preview, "form_class", DummyForm), patch(
            "rest_framework.request.Request.user"
        ) as mock_req_user:
            # unauthenticated request user to force internal email fallback
            mock_req_user.is_authenticated = False
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.post(
                url,
                {"project_uuid": str(self.org.proj_uuid)},
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        # ensure modified_by picked the internal user when request.user unauthenticated
        contact_import.refresh_from_db()
        self.assertIsNotNone(contact_import.modified_by)
        self.assertEqual(contact_import.modified_by.email, "internal@example.com")

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    @override_settings(INTERNAL_USER_EMAIL="missing-internal@example.com")
    def test_post_confirmer_fallback_when_internal_user_missing(self):
        from temba.api.v2.internals.contacts.views import ContactImportCRUDL

        contact_import = setup_contact_import_test_data(self)
        DummyForm = create_dummy_form_class()

        with patch.object(ContactImportCRUDL.Preview, "form_class", DummyForm), patch(
            "rest_framework.request.Request.user"
        ) as mock_req_user:
            mock_req_user.is_authenticated = False
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.post(
                url,
                {"project_uuid": str(self.org.proj_uuid)},
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        contact_import.refresh_from_db()
        # When internal user not found, it should fall back to org.modified_by or org.created_by
        self.assertIsNotNone(contact_import.modified_by)


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
        # expect nested structure: data has 'info' dict and 'group' key
        self.assertIn("info", data)
        self.assertIn("group", data)
        info = data["info"]
        for key in (
            "status",
            "num_created",
            "num_updated",
            "num_errored",
            "errors",
            "time_taken",
        ):
            self.assertIn(key, info)


class ContactsImportConfirmViewEdgeCasesTest(TembaTest):
    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_get_without_import_id_returns_400_direct(self):
        # call the view directly without URL kwargs to exercise the explicit 400 branch
        from rest_framework.test import APIRequestFactory
        from temba.api.v2.internals.contacts.views import ContactsImportConfirmView

        factory = APIRequestFactory()
        request = factory.get("/api/v2/internals/contacts_import_confirm/")
        view = ContactsImportConfirmView.as_view()
        resp = view(request)
        self.assertEqual(resp.status_code, 400)

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_post_missing_project_uuid_returns_400_direct(self):
        from rest_framework.test import APIRequestFactory
        from temba.api.v2.internals.contacts.views import ContactsImportConfirmView

        # use a valid import id but omit project_uuid in body
        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        factory = APIRequestFactory()
        request = factory.post(
            "/api/v2/internals/contacts_import_confirm/%d/" % contact_import.id,
            {},
            format="json",
        )
        view = ContactsImportConfirmView.as_view()
        resp = view(request, import_id=contact_import.id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Project is required", resp.data.get("error", ""))

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_post_missing_import_id_returns_400_direct(self):
        from rest_framework.test import APIRequestFactory
        from temba.api.v2.internals.contacts.views import ContactsImportConfirmView

        factory = APIRequestFactory()
        request = factory.post(
            "/api/v2/internals/contacts_import_confirm/",
            {"project_uuid": str(self.org.proj_uuid)},
            format="json",
        )
        view = ContactsImportConfirmView.as_view()
        resp = view(request)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("import_id is required", resp.data.get("error", ""))

    @skip_authentication(endpoint_path=CONTACTS_IMPORT_CONFIRM_PATH)
    def test_post_include_false_sets_mapping_ignore(self):
        from temba.api.v2.internals.contacts.views import ContactImportCRUDL
        from temba.contacts.models import ContactImport

        contact_import = self.create_contact_import("media/test_imports/simple.xlsx")
        # create a single mapping to be ignored
        contact_import.mappings = [{"header": "Name", "mapping": {"type": "attribute", "name": "name"}}]
        contact_import.save(update_fields=["mappings"])

        class DummyForm:
            GROUP_MODE_NEW = "new"
            GROUP_MODE_EXISTING = "existing"

            def __init__(self, data, org=None, instance=None):
                self.instance = instance
                self.cleaned_data = {"add_to_group": False}

            def is_valid(self):
                return True

            def get_form_values(self):
                # request to ignore the only column
                return [{"include": False}]

        with patch.object(ContactImportCRUDL.Preview, "form_class", DummyForm), patch.object(
            ContactImport, "start_async"
        ):
            self.login(self.user)
            url = f"/api/v2/internals/contacts_import_confirm/{contact_import.id}/"
            resp = self.client.post(
                url,
                {"project_uuid": str(self.org.proj_uuid)},
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        contact_import.refresh_from_db()
        self.assertEqual(contact_import.mappings[0]["mapping"], ContactImport.MAPPING_IGNORE)


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
        resp = self.client.get(
            self.url,
            {"project_uuid": "00000000-0000-0000-0000-000000000000", "group_ids": "1"},
        )
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


class InternalContactGroupsViewAdditionalTests(TembaTest):
    url = "/api/v2/internals/contact_groups"

    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_get_with_name_filter_and_order(self):
        # ensure groups have members; zero-member groups are excluded by the API
        c1 = self.create_contact("A1")
        c2 = self.create_contact("B1")
        c3 = self.create_contact("G1")
        self.create_group("Alpha", contacts=[c1])
        self.create_group("Beta", contacts=[c2])
        self.create_group("Gamma", contacts=[c3])

        resp = self.client.get(
            self.url,
            {"project_uuid": str(self.org.proj_uuid), "name": "a", "order_by": "name"},
        )
        self.assertEqual(resp.status_code, 200)
        names = [g["name"] for g in resp.json()["results"]]
        self.assertEqual(names, sorted(names))

    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_post_validations_and_success(self):
        # missing name
        resp = self.client.post(self.url, {"broadcast_id": 1, "status": "S"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Name is required"})

        # missing broadcast_id
        resp = self.client.post(self.url, {"name": "MyGroup", "status": "S"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Broadcast ID is required"})

        # invalid status
        resp = self.client.post(self.url, {"name": "MyGroup", "broadcast_id": 1, "status": "X"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Invalid status"})

        # valid success path
        contact = self.create_contact("Alice", urns=["tel:+111"])
        bcast = self.create_broadcast(self.admin, "hi", contacts=[contact])

        with patch("temba.api.v2.internals.contacts.views.User.objects.get") as mock_get_user, patch(
            "rest_framework.request.Request.user"
        ) as mock_req_user:
            mock_get_user.return_value = self.admin
            mock_req_user.is_authenticated = True
            mock_req_user.email = self.admin.email
            resp = self.client.post(
                self.url,
                {"name": "SuccessGroup", "broadcast_id": bcast.id, "status": "S"},
            )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body["group_uuid"])
        self.assertEqual(body["group_name"], "SuccessGroup")
        self.assertGreaterEqual(body["count"], 1)

    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_post_missing_status_returns_400(self):
        contact = self.create_contact("Alice", urns=["tel:+111"])
        bcast = self.create_broadcast(self.admin, "hi", contacts=[contact])
        resp = self.client.post(self.url, {"name": "NoStatusGroup", "broadcast_id": bcast.id})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Status is required"})

    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_post_broadcast_not_found_returns_404(self):
        resp = self.client.post(
            self.url,
            {"name": "MissingBroadcast", "broadcast_id": 999999, "status": "S"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project or Broadcast not found"})

    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.contacts.views.InternalContactGroupsView.permission_classes",
        [],
    )
    def test_post_user_not_found_returns_404(self):
        contact = self.create_contact("Alice", urns=["tel:+111"])
        bcast = self.create_broadcast(self.admin, "hi", contacts=[contact])
        with patch("temba.api.v2.internals.contacts.views.User.objects.get") as mock_get_user, patch(
            "rest_framework.request.Request.user"
        ) as mock_req_user:
            mock_req_user.is_authenticated = True
            mock_req_user.email = "missing@example.com"
            mock_get_user.side_effect = User.DoesNotExist
            resp = self.client.post(
                self.url,
                {"name": "UserMissingGroup", "broadcast_id": bcast.id, "status": "S"},
            )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "User not found"})
