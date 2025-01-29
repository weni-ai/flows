from unittest.mock import patch

from rest_framework import status
from rest_framework.response import Response

from django.test import override_settings

from temba.api.v2.validators import LambdaURLValidator
from temba.tests import TembaTest
from temba.tests.mailroom import mock_mailroom


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
