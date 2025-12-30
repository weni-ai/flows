from rest_framework.exceptions import NotAuthenticated, NotFound, ParseError, PermissionDenied
from rest_framework.permissions import BasePermission

from django.contrib.auth import get_user_model
from django.core import exceptions as django_exceptions

from temba.orgs.models import Org


class IsUserInOrg(BasePermission):
    """
    Permission that ensures the authenticated user belongs to the organization consulted via project_uuid.
    Expects project UUID to be present in request query params or body.

    Side-effect: on success, attaches:
      - request.project_uuid (str)
      - request.org (Org)

    Note: some endpoints historically return 401 when project is missing; those can set:
      - project_uuid_required_status = 401
      - project_uuid_required_detail = "Project not provided"
    """

    PROJECT_UUID_QUERY_KEYS = ("project_uuid", "project")
    PROJECT_UUID_BODY_KEYS = ("project_uuid", "project")

    def _get_project_uuid(self, request, view):
        # already set by auth layer or earlier middleware
        existing = getattr(request, "project_uuid", None)
        if existing:
            return existing

        query_params = getattr(request, "query_params", None) or {}
        data = getattr(request, "data", None) or {}

        for k in self.PROJECT_UUID_QUERY_KEYS:
            v = query_params.get(k)
            if v:
                return v
        for k in self.PROJECT_UUID_BODY_KEYS:
            v = data.get(k)
            if v:
                return v

        return None

    def _raise_project_uuid_missing(self, view):
        status = getattr(view, "project_uuid_required_status", 400)
        detail = getattr(view, "project_uuid_required_detail", "project_uuid is required")
        if status == 401:
            raise NotAuthenticated(detail=detail)
        raise ParseError(detail=detail)

    def _get_user_for_membership_check(self, request):
        """
        Prefer request.user if it's a real Django user. Fall back to lookup by email for
        cases where auth backends may yield a lightweight user object.
        """
        user = getattr(request, "user", None)
        if user is None:
            return None

        if getattr(user, "id", None):
            return user

        email = getattr(user, "email", None)
        if not email:
            return None

        User = get_user_model()
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist:
            return None

    def has_permission(self, request, view):
        project_uuid = self._get_project_uuid(request, view)
        if not project_uuid:
            self._raise_project_uuid_missing(view)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
            raise NotFound(detail="Project not found")

        user = self._get_user_for_membership_check(request)
        if not user:
            raise PermissionDenied(detail="User not found")

        if not org.has_user(user):
            raise PermissionDenied(detail="User does not belong to this project")

        # attach for downstream view reuse
        setattr(request, "org", org)
        setattr(request, "project_uuid", str(org.proj_uuid))
        return True


class HasValidJWT(BasePermission):
    """
    Grants permission if request was successfully authenticated via JWT.
    Relies on JWTModuleAuthentication setting `request.jwt_payload`.
    """

    def has_permission(self, request, view):
        return getattr(request, "jwt_payload", None) is not None
