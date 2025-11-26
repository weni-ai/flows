from types import SimpleNamespace
from uuid import uuid4

from rest_framework.test import APIRequestFactory

from django.test import TestCase

from temba.api.v2.internals.views import JWTAuthMockMixin


class JWTAuthMockMixinTests(JWTAuthMockMixin, TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        super().setUp()

    def test_creates_dummy_user_and_project_uuid_when_absent(self):
        request = self.factory.get("/")

        user, _ = self._mock_jwt_authenticate(request)

        self.assertEqual(request.user, user)
        self.assertEqual(request.user.email, "jwt-test@example.com")
        self.assertTrue(request.jwt_payload["project_uuid"])
        self.assertEqual(request.project_uuid, request.jwt_payload["project_uuid"])

    def test_uses_existing_user_and_org_project_uuid(self):
        real_user = SimpleNamespace(is_authenticated=True, email="real@example.com")
        project_uuid = uuid4()
        self.user = real_user
        self.org = SimpleNamespace(proj_uuid=project_uuid)
        request = self.factory.get("/")

        user, _ = self._mock_jwt_authenticate(request)

        self.assertIs(user, real_user)
        self.assertEqual(request.user.email, "real@example.com")
        self.assertEqual(request.jwt_payload["project_uuid"], str(project_uuid))
        self.assertEqual(request.project_uuid, str(project_uuid))
