import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model

from temba.flows.models import Flow
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

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_queue_invalid_value(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "contacts": [contact.uuid],
                "queue": "invalid",
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 400)
            error = response.json()
            self.assertIn("non_field_errors", error)
            self.assertIn("Queue must be either", error["non_field_errors"][0])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_template_batch_requires_name_groups_and_disallows_contacts(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            group1 = self.create_group("Group 1", contacts=[])
            group2 = self.create_group("Group 2", contacts=[])

            url = "/api/v2/internals/whatsapp_broadcasts"

            # missing name
            body = {
                "project": self.org.proj_uuid,
                "queue": "TEMPLATE_BATCH",
                "groups": [str(group1.uuid)],
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Name is required for template_batch queue", response.json()["non_field_errors"][0])

            # missing groups even if urns provided
            body = {
                "project": self.org.proj_uuid,
                "queue": "TEMPLATE_BATCH",
                "name": "Batch Name",
                "urns": ["whatsapp:5561912345678"],
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Groups are required for template_batch queue", response.json()["non_field_errors"][0])

            # contacts not allowed even if groups provided
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            body = {
                "project": self.org.proj_uuid,
                "queue": "TEMPLATE_BATCH",
                "name": "Batch Name",
                "groups": [str(group1.uuid), str(group2.uuid)],
                "contacts": [str(contact.uuid)],
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Contacts are not allowed for template_batch queue", response.json()["non_field_errors"][0])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_only_for_template_batch(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "queue": "wpp_broadcast_batch",
                "trigger_flow_uuid": str(uuid.uuid4()),
                "msg": {"text": "hello"},
                "urns": ["whatsapp:5561912345678"],
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn(
                "trigger_flow_uuid is only allowed when queue is template_batch",
                response.json()["non_field_errors"][0],
            )

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_not_found_and_wrong_type(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"

            # not found
            body = {
                "project": self.org.proj_uuid,
                "queue": "template_batch",
                "name": "Batch Name",
                "groups": [str(self.create_group("G", contacts=[]).uuid)],
                "trigger_flow_uuid": str(uuid.uuid4()),
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Trigger flow not found for this workspace", response.json()["non_field_errors"][0])

            # wrong type
            background_flow = self.create_flow(flow_type=Flow.TYPE_BACKGROUND)
            body["trigger_flow_uuid"] = str(background_flow.uuid)
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Trigger flow must be a messaging or voice flow", response.json()["non_field_errors"][0])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_success(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"
            flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
            group = self.create_group("G", contacts=[])

            body = {
                "project": self.org.proj_uuid,
                "queue": "template_batch",
                "name": "Batch Name",
                "groups": [str(group.uuid)],
                "trigger_flow_uuid": str(flow.uuid),
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"message": "Success"})
