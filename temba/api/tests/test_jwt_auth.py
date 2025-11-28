from unittest.mock import patch

import jwt
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from django.conf import settings as django_settings
from django.test import TestCase

from temba.api.auth.jwt import (
    JWTAuthMixinOptional,
    JWTAuthMixinRequired,
    OptionalJWTAuthentication,
    RequiredJWTAuthentication,
)
from temba.api.v2.permissions import HasValidJWT


class OptionalJWTAuthenticationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = OptionalJWTAuthentication()

    def test_getters_return_modules(self):
        self.assertIs(self.auth.get_settings(), django_settings)
        self.assertIs(self.auth.get_jwt(), jwt)

    def test_no_authorization_header_returns_none(self):
        request = self.factory.get("/")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_invalid_header_type_returns_none(self):
        request = self.factory.get("/")
        request.headers = {"Authorization": 123}  # non-string
        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_invalid_header_prefix_returns_none(self):
        request = self.factory.get("/")
        request.headers = {"Authorization": "Token abc"}  # not Bearer
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

    @patch("temba.api.auth.jwt.jwt.decode")
    @patch("temba.api.auth.jwt.settings")
    def test_success_sets_project_from_project_key(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        mock_jwt_decode.return_value = {"project": "proj-abc"}

        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer valid-token"}

        self.auth.authenticate(request)
        self.assertEqual(getattr(request, "project_uuid", None), "proj-abc")

    @patch("temba.api.auth.jwt.settings")
    def test_invalid_token_returns_none(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer invalid-token"}
        with patch("temba.api.auth.jwt.jwt.decode", side_effect=jwt.InvalidTokenError("bad")):
            self.assertIsNone(self.auth.authenticate(request))

    @patch("temba.api.auth.jwt.settings")
    def test_expired_token_returns_none(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer expired-token"}
        with patch("temba.api.auth.jwt.jwt.decode", side_effect=jwt.ExpiredSignatureError("expired")):
            self.assertIsNone(self.auth.authenticate(request))

    @patch("temba.api.auth.jwt.jwt.decode")
    @patch("temba.api.auth.jwt.settings")
    def test_success_sets_payload_and_channel_uuid(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        payload = {"channel_uuid": "chan-456", "email": "user@example.com"}
        mock_jwt_decode.return_value = payload

        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer valid-token"}

        user, _ = self.auth.authenticate(request)
        from django.contrib.auth.models import AnonymousUser

        self.assertIsInstance(user, AnonymousUser)
        self.assertEqual(getattr(request, "jwt_payload", None), payload)
        self.assertEqual(getattr(request, "channel_uuid", None), "chan-456")


class RequiredJWTAuthenticationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = RequiredJWTAuthentication()

    def test_getters_return_modules(self):
        self.assertIs(self.auth.get_settings(), django_settings)
        self.assertIs(self.auth.get_jwt(), jwt)

    @patch("temba.api.auth.jwt.settings")
    def test_missing_public_key_raises(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = None
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer any"}
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("JWT_PUBLIC_KEY not configured", str(ctx.exception))

    @patch("temba.api.auth.jwt.settings")
    def test_missing_authorization_header_raises(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        request = self.factory.get("/")
        with self.assertRaises(AuthenticationFailed) as ctx:
            self.auth.authenticate(request)
        self.assertIn("Missing or invalid Authorization header", str(ctx.exception))

    @patch("temba.api.auth.jwt.settings")
    def test_invalid_authorization_prefix_raises(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        request = self.factory.get("/")
        request.headers = {"Authorization": "Token abc"}
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

    @patch("temba.api.auth.jwt.settings")
    def test_required_expired_token_raises(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer expired-token"}
        with patch("temba.api.auth.jwt.jwt.decode", side_effect=jwt.ExpiredSignatureError("expired")):
            with self.assertRaises(AuthenticationFailed) as ctx:
                self.auth.authenticate(request)
            self.assertIn("Token expired", str(ctx.exception))

    @patch("temba.api.auth.jwt.settings")
    def test_required_invalid_token_raises(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy-public-key"
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer invalid-token"}
        with patch("temba.api.auth.jwt.jwt.decode", side_effect=jwt.InvalidTokenError("bad")):
            with self.assertRaises(AuthenticationFailed) as ctx:
                self.auth.authenticate(request)
            self.assertIn("Invalid token", str(ctx.exception))


class HasValidJWTTests(TestCase):
    def test_permission_granted_when_jwt_payload_present(self):
        request = APIRequestFactory().get("/")
        request.jwt_payload = {"k": "v"}
        self.assertTrue(HasValidJWT().has_permission(request, view=None))

    def test_permission_denied_when_no_jwt(self):
        request = APIRequestFactory().get("/")
        self.assertFalse(HasValidJWT().has_permission(request, view=None))


class JWTAuthMixinsTests(TestCase):
    def test_required_mixin_properties(self):
        class Dummy(JWTAuthMixinRequired):
            request = None

        d = Dummy()
        req = APIRequestFactory().get("/")
        req.project_uuid = "proj-required"
        req.jwt_payload = {"a": 1}
        d.request = req
        self.assertEqual(d.project_uuid, "proj-required")
        self.assertEqual(d.jwt_payload, {"a": 1})

    def test_optional_mixin_properties(self):
        class Dummy(JWTAuthMixinOptional):
            request = None

        d = Dummy()
        req = APIRequestFactory().get("/")
        req.project_uuid = "proj-optional"
        req.jwt_payload = {"b": 2}
        d.request = req
        self.assertEqual(d.project_uuid, "proj-optional")
        self.assertEqual(d.jwt_payload, {"b": 2})
