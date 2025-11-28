from types import SimpleNamespace
from uuid import uuid4

from rest_framework.test import APIRequestFactory

from django.test import TestCase

from temba.api.v2.internals.views import JWTAuthMockMixin


class JWTAuthMockMixinTests(JWTAuthMockMixin, TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        super().setUp()

    def test_creates_dummy_user_with_empty_payload(self):
        request = self.factory.get("/")

        user, _ = self._mock_jwt_authenticate(request)

        self.assertEqual(request.user, user)
        self.assertEqual(request.user.email, "jwt-test@example.com")
        self.assertIsNone(request.jwt_payload["project_uuid"])
        self.assertIsNone(request.project_uuid)
        self.assertIsNone(request.jwt_payload["channel_uuid"])
        self.assertIsNone(request.channel_uuid)

    def test_uses_existing_user_and_payload_kwargs(self):
        real_user = SimpleNamespace(is_authenticated=True, email="real@example.com")
        project_uuid = str(uuid4())
        channel_uuid = str(uuid4())
        self.user = real_user
        request = self.factory.get("/")

        user, _ = self._mock_jwt_authenticate(request, project_uuid=project_uuid, channel_uuid=channel_uuid)

        self.assertIs(user, real_user)
        self.assertEqual(request.user.email, "real@example.com")
        self.assertEqual(request.jwt_payload["project_uuid"], project_uuid)
        self.assertEqual(request.jwt_payload["channel_uuid"], channel_uuid)
        self.assertEqual(request.project_uuid, project_uuid)
        self.assertEqual(request.channel_uuid, channel_uuid)
