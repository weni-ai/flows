from types import SimpleNamespace
from unittest.mock import patch

from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from django.core import exceptions as django_exceptions

from temba.orgs.models import Org


class APIViewMixin:
    authentication_classes = []
    permission_classes = []
    pagination_class = None
    renderer_classes = [JSONRenderer]
    throttle_classes = []

    def get_org_from_request(
        self,
        request,
        *,
        query_keys=("project_uuid", "project"),
        body_keys=("project_uuid", "project"),
        require_project_uuid=False,
        missing_status=400,
        missing_error="Project not provided",
        not_found_status=404,
        not_found_error="Project not found",
    ):
        """
        Returns Org for this request, attaching `request.org` and `request.project_uuid`.

        If org can't be resolved, returns a DRF Response with the legacy `{error: ...}` payload.
        This is intentionally view-level (not permission-level) because many unit tests (and some
        internal callers) patch out DRF authentication/permissions.
        """

        # If an explicit project UUID is required, don't fall back to request.org (which may be
        # set by legacy middleware / session context) because many endpoints and tests require the
        # caller to provide project_uuid/project explicitly.
        if not require_project_uuid:
            org = getattr(request, "org", None)
            if org is not None:
                return org

        project_uuid = getattr(request, "project_uuid", None)

        query_params = getattr(request, "query_params", None) or {}
        data = getattr(request, "data", None) or {}

        # Prefer explicit project_uuid/project from params/body over any pre-attached org
        if not project_uuid:
            for k in query_keys:
                v = query_params.get(k)
                if v:
                    project_uuid = v
                    break

        if not project_uuid:
            for k in body_keys:
                v = data.get(k)
                if v:
                    project_uuid = v
                    break

        if not project_uuid:
            return Response({"error": missing_error}, status=missing_status)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
            return Response({"error": not_found_error}, status=not_found_status)

        setattr(request, "org", org)
        setattr(request, "project_uuid", str(org.proj_uuid))
        return org


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
