from functools import wraps
from unittest.mock import patch

from django.test import override_settings

from temba.tests import TembaTest
from temba.contacts.models import ContactField


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
