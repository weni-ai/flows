import json
import uuid
from unittest.mock import patch

import jwt as pyjwt

from fastapi import HTTPException
from fastapi.testclient import TestClient
from temba.fastapi_app.auth import verify_jwt
from temba.fastapi_app.broadcasts import app, post_internal_whatsapp_broadcast
from temba.msgs.models import Broadcast
from temba.tests.base import TembaTest


def _parse(resp) -> tuple[int, dict]:
    return resp.status_code, json.loads(resp.body or b"{}")


class TestHealthEndpoint(TembaTest):
    """Routing-only tests; no DB needed, TestClient is fine here."""

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


class TestPostInternalWhatsappBroadcast(TembaTest):
    """
    Calls the FastAPI handler function directly to avoid the starlette TestClient threadpool
    (which would force TransactionTestCase). All DB-dependent assertions run in the same
    thread as the Django TestCase transaction.
    """

    def setUp(self):
        super().setUp()
        if not self.org.proj_uuid:
            self.org.proj_uuid = uuid.uuid4()
            self.org.save(update_fields=("proj_uuid",))

    def test_project_not_provided_returns_401(self):
        with self.assertRaises(HTTPException) as ctx:
            post_internal_whatsapp_broadcast(
                body={
                    "urns": ["whatsapp:5561912345678"],
                    "user_email": "user@example.com",
                    "msg": {"text": "Hi"},
                },
                jwt_payload={},
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, {"error": "Project not provided"})

    def test_project_not_found_returns_404(self):
        with self.assertRaises(HTTPException) as ctx:
            post_internal_whatsapp_broadcast(
                body={
                    "urns": ["whatsapp:5561912345678"],
                    "msg": {"text": "Hi"},
                },
                jwt_payload={"project_uuid": str(uuid.uuid4()), "email": "user@example.com"},
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, {"error": "Project not found"})

    def test_user_email_missing_returns_401(self):
        with self.assertRaises(HTTPException) as ctx:
            post_internal_whatsapp_broadcast(
                body={
                    "urns": ["whatsapp:5561912345678"],
                    "msg": {"text": "Hi"},
                },
                jwt_payload={"project_uuid": str(self.org.proj_uuid)},
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, {"error": "User email not provided"})

    def test_body_user_email_without_identity_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            post_internal_whatsapp_broadcast(
                body={
                    "project": str(self.org.proj_uuid),
                    "user_email": "admin@a.com",
                    "urns": ["whatsapp:5561912345678"],
                    "msg": {"text": "Hi"},
                },
                jwt_payload={"project_uuid": str(self.org.proj_uuid)},
            )

        self.assertEqual(ctx.exception.status_code, 401)

    def test_serializer_error_returns_400(self):
        resp = post_internal_whatsapp_broadcast(
            body={
                "project": str(self.org.proj_uuid),
                "msg": {"text": "Hi"},
            },
            jwt_payload={"project_uuid": str(self.org.proj_uuid), "email": "user@example.com"},
        )
        status_code, _ = _parse(resp)
        self.assertEqual(status_code, 400)

    def test_success_returns_201(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        resp = post_internal_whatsapp_broadcast(
            body={
                "project": str(self.org.proj_uuid),
                "contacts": [str(contact.uuid)],
                "msg": {"text": "Hello @contact.name"},
            },
            jwt_payload={"project_uuid": str(self.org.proj_uuid), "email": "user@example.com"},
        )

        status_code, data = _parse(resp)
        self.assertEqual(status_code, 201)
        self.assertIn("id", data)
        self.assertIn("created_on", data)
        self.assertEqual(data["contacts"][0]["uuid"], str(contact.uuid))
        self.assertEqual(data["metadata"].get("text"), "Hello @contact.name")

    def test_custom_data_success_and_absence(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        custom_data = {"order_id": "1234567890-01", "tags": ["vip"]}
        jwt = {"project_uuid": str(self.org.proj_uuid), "email": "user@example.com"}
        resp = post_internal_whatsapp_broadcast(
            body={
                "project": str(self.org.proj_uuid),
                "contacts": [str(contact.uuid)],
                "msg": {"text": "Hello", "custom_data": custom_data},
            },
            jwt_payload=jwt,
        )
        status_code, data = _parse(resp)
        self.assertEqual(status_code, 201)
        self.assertEqual(custom_data, Broadcast.objects.get(id=data["id"]).metadata["custom_data"])

        resp = post_internal_whatsapp_broadcast(
            body={
                "project": str(self.org.proj_uuid),
                "contacts": [str(contact.uuid)],
                "msg": {"text": "Hello"},
            },
            jwt_payload=jwt,
        )
        status_code, data = _parse(resp)
        self.assertEqual(status_code, 201)
        self.assertNotIn("custom_data", Broadcast.objects.get(id=data["id"]).metadata)

        resp = post_internal_whatsapp_broadcast(
            body={
                "project": str(self.org.proj_uuid),
                "contacts": [str(contact.uuid)],
                "msg": {"text": "Hello", "custom_data": {}},
            },
            jwt_payload=jwt,
        )
        status_code, data = _parse(resp)
        self.assertEqual(status_code, 201)
        self.assertNotIn("custom_data", Broadcast.objects.get(id=data["id"]).metadata)

    def test_custom_data_invalid(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        jwt = {"project_uuid": str(self.org.proj_uuid), "email": "user@example.com"}
        before = Broadcast.objects.filter(org=self.org).count()
        nested = {}
        current = nested
        for _ in range(32):
            current["x"] = {}
            current = current["x"]
        cases = [
            (None, "custom_data must be an object"),
            ("x", "custom_data must be an object"),
            ([], "custom_data must be an object"),
            (1, "custom_data must be an object"),
            ({"pad": "x" * 16385}, "custom_data must be at most 16384 bytes when serialized"),
            (nested, "custom_data must have at most 32 levels of nesting"),
            ({"$x": 1}, "custom_data keys must not start with '$' or contain '.'"),
            ({"outer": {"a.b": 1}}, "custom_data keys must not start with '$' or contain '.'"),
            ({"items": [{"bad.key": True}]}, "custom_data keys must not start with '$' or contain '.'"),
        ]
        for payload, message in cases:
            resp = post_internal_whatsapp_broadcast(
                body={
                    "project": str(self.org.proj_uuid),
                    "contacts": [str(contact.uuid)],
                    "msg": {"text": "Hello", "custom_data": payload},
                },
                jwt_payload=jwt,
            )
            status_code, data = _parse(resp)
            self.assertEqual(status_code, 400)
            self.assertEqual(data["msg"], [message])
        self.assertEqual(before, Broadcast.objects.filter(org=self.org).count())

    def test_jwt_payload_project_uuid_is_used(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        resp = post_internal_whatsapp_broadcast(
            body={
                "contacts": [str(contact.uuid)],
                "msg": {"text": "Hi"},
            },
            jwt_payload={
                "project_uuid": str(self.org.proj_uuid),
                "email": "user-from-jwt@example.com",
            },
        )

        status_code, data = _parse(resp)
        self.assertEqual(status_code, 201)
        self.assertEqual(data["contacts"][0]["uuid"], str(contact.uuid))

    def test_jwt_project_and_body_project_mismatch_returns_403(self):
        with self.assertRaises(HTTPException) as ctx:
            post_internal_whatsapp_broadcast(
                body={
                    "project": str(uuid.uuid4()),
                    "contacts": [],
                    "msg": {"text": "Hi"},
                },
                jwt_payload={
                    "project_uuid": str(self.org.proj_uuid),
                    "email": "user-from-jwt@example.com",
                },
            )

        self.assertEqual(ctx.exception.status_code, 403)


class TestVerifyJwt(TembaTest):
    """Auth dependency tested in isolation — no FastAPI/Starlette TestClient involved."""

    def test_missing_authorization_returns_403(self):
        with self.assertRaises(HTTPException) as ctx:
            verify_jwt(authorization=None)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, {"error": "Missing or invalid Authorization header"})

    def test_non_bearer_authorization_returns_403(self):
        with self.assertRaises(HTTPException) as ctx:
            verify_jwt(authorization="Basic abc")

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, {"error": "Missing or invalid Authorization header"})

    def test_missing_public_key_returns_403(self):
        with self.settings(JWT_PUBLIC_KEY=""):
            with self.assertRaises(HTTPException) as ctx:
                verify_jwt(authorization="Bearer some.token.here")

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, {"error": "JWT public key not configured"})

    def test_invalid_token_returns_403(self):
        with self.settings(JWT_PUBLIC_KEY="dummy-key"):
            with self.assertRaises(HTTPException) as ctx:
                verify_jwt(authorization="Bearer not-a-jwt")

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, {"error": "Invalid token"})

    @patch("temba.fastapi_app.auth.jwt.decode", side_effect=pyjwt.ExpiredSignatureError())
    def test_expired_token_returns_403(self, _mock_decode):
        with self.settings(JWT_PUBLIC_KEY="dummy-key"):
            with self.assertRaises(HTTPException) as ctx:
                verify_jwt(authorization="Bearer expired.jwt.here")

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, {"error": "Token expired"})

    @patch("temba.fastapi_app.auth.jwt.decode", return_value={"email": "x@example.com", "project_uuid": "abc"})
    def test_valid_token_returns_payload(self, _mock_decode):
        with self.settings(JWT_PUBLIC_KEY="dummy-key"):
            payload = verify_jwt(authorization="Bearer valid.jwt.here")

        self.assertEqual(payload, {"email": "x@example.com", "project_uuid": "abc"})
