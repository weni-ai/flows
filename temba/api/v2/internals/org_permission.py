from rest_framework.permissions import BasePermission

from django.contrib.auth import get_user_model

from temba.orgs.models import Org


class IsUserInOrg(BasePermission):
    """
    Permission that ensures the authenticated user belongs to the organization consulted via project_uuid.
    Expects project_uuid to be in request.query_params or request.data.
    """

    def has_permission(self, request, view):
        project_uuid = (
            request.query_params.get("project_uuid")
            or request.query_params.get("project")
            or request.data.get("project_uuid")
            or request.data.get("project")
        )
        if not project_uuid:
            return False
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return False
        User = get_user_model()
        try:
            user = User.objects.get(email=request.user.email)
        except User.DoesNotExist:
            return False
        return org.has_user(user)
