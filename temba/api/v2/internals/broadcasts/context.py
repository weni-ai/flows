"""
Shared resolve logic for WhatsApp broadcast internal endpoints (Django sync + FastAPI bridge).
"""

from weni.internal.permissions import CanCommunicateInternally

from django.contrib.auth import get_user_model

from temba.orgs.models import Org

User = get_user_model()


class ProjectMismatch(ValueError):
    """Body/query/token project identifiers disagree."""


def _is_trusted_internal(drf_request) -> bool:
    user = getattr(drf_request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return CanCommunicateInternally().has_permission(drf_request, view=None) is True


def resolve_org_and_user_internal_whatsapp(*, drf_request, data):
    """
    Resolve org and acting user from the authenticated identity, not from untrusted body fields.

    Trusted internal callers (CanCommunicateInternally) may still act on behalf of a body
    user_email for a real project. Everyone else uses request.user or the JWT email.
    """
    jwt_payload = getattr(drf_request, "jwt_payload", None) or {}
    attached_org = getattr(drf_request, "org", None)
    jwt_project = jwt_payload.get("project_uuid") or jwt_payload.get("project")
    body_project = data.get("project") or data.get("project_uuid")

    if attached_org is not None:
        org = attached_org
        if body_project and str(body_project) != str(org.proj_uuid):
            raise ProjectMismatch("Project mismatch")
        if jwt_project and str(jwt_project) != str(org.proj_uuid):
            raise ProjectMismatch("Project mismatch")
    elif jwt_project:
        if body_project and str(body_project) != str(jwt_project):
            raise ProjectMismatch("Project mismatch")
        try:
            org = Org.objects.get(proj_uuid=jwt_project)
        except Org.DoesNotExist:
            raise ValueError("Project not found")
    else:
        project_uuid = body_project or getattr(drf_request, "project_uuid", None)
        if not project_uuid:
            raise ValueError("Project not provided")
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            raise ValueError("Project not found")

    jwt_email = jwt_payload.get("email") or jwt_payload.get("user_email")
    request_user = getattr(drf_request, "user", None)
    trusted = _is_trusted_internal(drf_request)
    body_email = data.get("user_email")

    if trusted and body_email:
        user, _ = User.objects.get_or_create(email=body_email)
    elif jwt_email:
        user, _ = User.objects.get_or_create(email=jwt_email)
    elif request_user and getattr(request_user, "is_authenticated", False) and getattr(request_user, "email", None):
        user, _ = User.objects.get_or_create(email=request_user.email)
    else:
        raise ValueError("User email not provided")

    setattr(drf_request, "_org", org)
    setattr(drf_request, "org", org)
    setattr(drf_request, "project_uuid", str(org.proj_uuid))
    return org, user
