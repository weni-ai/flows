from rest_framework.permissions import BasePermission

from django.contrib.auth import get_user_model
from django.core import exceptions as django_exceptions

from temba.orgs.models import Org, OrgRole


class IsUserInOrg(BasePermission):
    """
    Permission that ensures the authenticated user belongs to the organization consulted via project_uuid.
    Expects project UUID to be present in request query params or body.

    Side-effect: on success, attaches:
      - request.project_uuid (str)
      - request.org (Org)

    Missing project UUID is left to the view (legacy 400 payloads). An unknown
    UUID, or a query/body/token disagreement, is denied (no fail-open).
    """

    PROJECT_UUID_QUERY_KEYS = ("project_uuid", "project")
    PROJECT_UUID_BODY_KEYS = ("project_uuid", "project")

    # None means any explicit org role. Subclasses set a tuple of OrgRole.
    allowed_roles = None

    def _iter_project_uuid_candidates(self, request, view):
        existing = getattr(request, "project_uuid", None)
        if existing:
            yield existing

        query_params = getattr(request, "query_params", None) or {}
        data = getattr(request, "data", None) or {}

        for k in self.PROJECT_UUID_QUERY_KEYS:
            v = query_params.get(k)
            if v:
                yield v
        for k in self.PROJECT_UUID_BODY_KEYS:
            v = data.get(k)
            if v:
                yield v

    def _get_project_uuid(self, request, view):
        candidates = [str(v) for v in self._iter_project_uuid_candidates(request, view) if v]
        if not candidates:
            return None
        unique = set(candidates)
        if len(unique) > 1:
            return False  # sentinel: mismatch
        return candidates[0]

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
        if project_uuid is False:
            return False
        if not project_uuid:
            # Let the view return its own legacy error response (400)
            return True

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
            return False

        user = self._get_user_for_membership_check(request)
        if not user:
            return False

        if not self._user_is_allowed(org, user):
            return False

        setattr(request, "org", org)
        setattr(request, "project_uuid", str(org.proj_uuid))
        return True

    def _user_is_allowed(self, org, user) -> bool:
        if not self.allowed_roles:
            return org.has_user(user)
        return org.get_users(roles=list(self.allowed_roles)).filter(id=user.id).exists()


class IsAdminEditorOrAgentInOrg(IsUserInOrg):
    """
    Same project resolution as IsUserInOrg, but only Administrator, Editor
    (contributor) and Agent (human service / chat user) roles may proceed. Role
    is read from the org membership, not from staff status.
    """

    allowed_roles = (OrgRole.ADMINISTRATOR, OrgRole.EDITOR, OrgRole.AGENT)


class HasValidJWT(BasePermission):
    """
    Grants permission if request was successfully authenticated via JWT.
    Relies on JWTModuleAuthentication setting `request.jwt_payload`.
    """

    def has_permission(self, request, view):
        return getattr(request, "jwt_payload", None) is not None
