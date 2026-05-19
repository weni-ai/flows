import uuid

from fastapi.testclient import TestClient

from temba.fastapi_app.main import app
from temba.tests.base import TembaTest


class TestHealthEndpoint(TembaTest):
    def setUp(self):
        super().setUp()
        self.client_fastapi = TestClient(app)

    def test_health_root(self):
        resp = self.client_fastapi.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_at_health(self):
        resp = self.client_fastapi.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_under_fastapi_prefix(self):
        resp = self.client_fastapi.get("/fastapi/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_under_fastapi_prefix_health(self):
        resp = self.client_fastapi.get("/fastapi/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class TestInternalWhatsappBroadcastFastAPI(TembaTest):
    url = "/fastapi/internal/whatsapp_broadcasts"

    def setUp(self):
        super().setUp()
        self.client_fastapi = TestClient(app)

    def test_project_not_provided_returns_401(self):
        body = {
            "urns": ["whatsapp:5561912345678"],
            "user_email": "user@example.com",
            "msg": {"text": "Hi"},
        }
        resp = self.client_fastapi.post(self.url, json=body)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {"detail": {"error": "Project not provided"}})

    def test_project_not_found_returns_404(self):
        body = {
            "project": str(uuid.uuid4()),
            "urns": ["whatsapp:5561912345678"],
            "user_email": "user@example.com",
            "msg": {"text": "Hi"},
        }
        resp = self.client_fastapi.post(self.url, json=body)

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"detail": {"error": "Project not found"}})

    def test_user_email_missing_returns_401(self):
        body = {
            "project": str(self.org.proj_uuid),
            "urns": ["whatsapp:5561912345678"],
            "msg": {"text": "Hi"},
        }
        resp = self.client_fastapi.post(self.url, json=body)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {"detail": {"error": "User email not provided"}})

    def test_serializer_error_returns_400(self):
        body = {
            "project": str(self.org.proj_uuid),
            "user_email": "user@example.com",
            "msg": {"text": "Hi"},
        }
        resp = self.client_fastapi.post(self.url, json=body)

        self.assertEqual(resp.status_code, 400)

    def test_success_returns_201(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        body = {
            "project": str(self.org.proj_uuid),
            "user_email": "user@example.com",
            "contacts": [str(contact.uuid)],
            "msg": {"text": "Hello @contact.name"},
        }
        resp = self.client_fastapi.post(self.url, json=body)

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("id", data)
        self.assertIn("created_on", data)
        self.assertEqual(data["contacts"][0]["uuid"], str(contact.uuid))
        self.assertEqual(data["metadata"].get("text"), body["msg"]["text"])

    def test_authorization_header_does_not_break(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        body = {
            "project": str(self.org.proj_uuid),
            "user_email": "user@example.com",
            "contacts": [str(contact.uuid)],
            "msg": {"text": "Hi"},
        }
        resp = self.client_fastapi.post(
            self.url,
            json=body,
            headers={"Authorization": "Bearer not-a-real-token"},
        )

        self.assertEqual(resp.status_code, 201)
