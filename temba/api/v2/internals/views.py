from types import SimpleNamespace
from unittest.mock import patch

from rest_framework.renderers import JSONRenderer


class APIViewMixin:
    authentication_classes = []
    permission_classes = []
    pagination_class = None
    renderer_classes = [JSONRenderer]
    throttle_classes = []


class JWTAuthMockMixin:
    """
    Test helper that patches RequiredJWTAuthentication to always accept a fake Bearer token.
    """

    jwt_patch_target = "temba.api.auth.jwt.RequiredJWTAuthentication.authenticate"

    def setUp(self):
        super().setUp()
        self.auth_headers = {"HTTP_AUTHORIZATION": "Bearer test-token"}
        self._jwt_patch = patch(self.jwt_patch_target, side_effect=self._mock_jwt_authenticate)
        self._jwt_patch.start()
        self.addCleanup(self._jwt_patch.stop)

    def _mock_jwt_authenticate(self, request, *args, **kwargs):
        user = getattr(self, "user", None)
        if user is None:
            if not hasattr(self, "_jwt_dummy_user"):
                self._jwt_dummy_user = SimpleNamespace(is_authenticated=True, email="jwt-test@example.com")
            user = self._jwt_dummy_user

        payload = {
            "project_uuid": kwargs.get("project_uuid"),
            "channel_uuid": kwargs.get("channel_uuid"),
        }
        if getattr(self, "jwt_payload_patch", None):
            payload.update(self.jwt_payload_patch)

        request.jwt_payload = payload
        request.project_uuid = payload.get("project_uuid")
        request.channel_uuid = payload.get("channel_uuid")
        request.user = user
        return (user, None)
