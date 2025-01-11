from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model

from temba.tests.base import TembaTest

User = get_user_model()


class TestInternalWhatsappBroadcast(TembaTest):
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_success(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "contacts": [contact.uuid],
                "msg": {
                    "text": "Essa é uma mensagem de teste para @contact.name",
                },
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"message": "Success"})

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_project_not_provided(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

        url = "/api/v2/internals/whatsapp_broadcasts"
        body = {
            "contacts": [contact.uuid],
            "msg": {
                "text": "Essa é uma mensagem de teste para @contact.name",
            },
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Project not provided"})

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_project_not_found(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

        url = "/api/v2/internals/whatsapp_broadcasts"
        body = {
            "project": self.org.uuid,
            "contacts": [contact.uuid],
            "msg": {
                "text": "Essa é uma mensagem de teste para @contact.name",
            },
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Project not found"})

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_serializer_error(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "msg": {"text": "Essa é uma mensagem de teste para @contact.name"},
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 400)
