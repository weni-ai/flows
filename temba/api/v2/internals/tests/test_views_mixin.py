from types import SimpleNamespace
from uuid import uuid4

from rest_framework.test import APIRequestFactory

from django.test import TestCase

from temba.api.v2.internals.views import APIViewMixin, JWTAuthMockMixin


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


class GetOrgFromRequestTests(TestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.mixin = APIViewMixin()

    def test_returns_existing_request_org_fast_path(self):
        """
        Covers the fast-path branch where request.org is already present.
        """
        request = self.factory.get("/")
        org = SimpleNamespace(id=123, proj_uuid=uuid4())
        request.org = org

        result = self.mixin.get_org_from_request(request)

        self.assertIs(result, org)

    def test_require_project_uuid_ignores_request_org_and_returns_missing(self):
        """
        When require_project_uuid=True, request.org must not short-circuit; missing project_uuid should error.
        """
        request = self.factory.get("/")
        request.org = SimpleNamespace(id=123, proj_uuid=uuid4())

        result = self.mixin.get_org_from_request(request, require_project_uuid=True, missing_status=401)

        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.data, {"error": "Project not provided"})
