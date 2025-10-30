from unittest.mock import patch

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from django.test import TestCase

from temba.api.auth.jwt import OptionalJWTAuthentication, RequiredJWTAuthentication
from temba.api.v2.permissions import HasValidJWT


class OptionalJWTAuthenticationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = OptionalJWTAuthentication()

    def test_no_authorization_header_returns_none(self):
        request = self.factory.get("/")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    @patch("temba.api.auth.jwt.settings")
    def test_missing_public_key_returns_none_when_bearer(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = None
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer test-token"}
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    @patch("temba.api.auth.jwt.jwt.decode")
    @patch("temba.api.auth.jwt.settings")
    def test_success_sets_payload_and_project_uuid(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        payload = {"project_uuid": "proj-123", "email": "user@example.com"}
        mock_jwt_decode.return_value = payload

        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer valid-token"}

        user, _ = self.auth.authenticate(request)
        from django.contrib.auth.models import AnonymousUser

        self.assertIsInstance(user, AnonymousUser)
        self.assertEqual(getattr(request, "project_uuid", None), "proj-123")
        self.assertEqual(getattr(request, "jwt_payload", None), payload)


class RequiredJWTAuthenticationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = RequiredJWTAuthentication()

    @patch("temba.api.auth.jwt.settings")
    def test_missing_authorization_header_raises(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        request = self.factory.get("/")
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("Missing or invalid Authorization header", str(ctx.exception))

    @patch("temba.api.auth.jwt.jwt.decode")
    @patch("temba.api.auth.jwt.settings")
    def test_missing_project_uuid_raises(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        mock_jwt_decode.return_value = {"some": "payload"}
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer valid-token"}
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("project_uuid not found in token payload", str(ctx.exception))

    @patch("temba.api.auth.jwt.jwt.decode")
    @patch("temba.api.auth.jwt.settings")
    def test_required_success(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        payload = {"project_uuid": "proj-456"}
        mock_jwt_decode.return_value = payload
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer valid-token"}

        user, _ = self.auth.authenticate(request)
        from django.contrib.auth.models import AnonymousUser

        self.assertIsInstance(user, AnonymousUser)
        self.assertEqual(getattr(request, "project_uuid", None), "proj-456")
        self.assertEqual(getattr(request, "jwt_payload", None), payload)


class HasValidJWTTests(TestCase):
    def test_permission_granted_when_jwt_payload_present(self):
        request = APIRequestFactory().get("/")
        request.jwt_payload = {"k": "v"}
        self.assertTrue(HasValidJWT().has_permission(request, view=None))

    def test_permission_denied_when_no_jwt(self):
        request = APIRequestFactory().get("/")
        self.assertFalse(HasValidJWT().has_permission(request, view=None))
