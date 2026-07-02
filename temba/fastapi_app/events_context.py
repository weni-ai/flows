"""
Org/user resolution for the FastAPI events endpoint.

Mirrors BaseAPIView._resolve_org_from_params / _resolve_internal_user so that the
FastAPI service can hand fetch_events_for_org a real user with org context set.
"""

from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from temba.orgs.models import Org

User = get_user_model()


def resolve_org_and_user_for_events(*, project_uuid: Optional[str]) -> Tuple[Org, "User"]:
    """
    Returns (org, user) given a project UUID. Raises ValueError on missing/invalid project
    or when no suitable internal user can be resolved.

    The returned user already has ``user.set_org(org)`` applied so that downstream
    helpers calling ``user.get_org()`` work as in the Django path.
    """
    if not project_uuid:
        raise ValueError("Project not provided")

    try:
        org = Org.objects.filter(proj_uuid=project_uuid).first()
    except ValidationError:
        org = None
    if not org:
        raise ValueError("Project not found")

    user = _resolve_internal_user(org)
    if not user:
        raise ValueError("Internal user not found")

    user.set_org(org)
    return org, user


def _resolve_internal_user(org: Org):
    internal_email = getattr(settings, "INTERNAL_USER_EMAIL", "")
    if internal_email:
        try:
            return User.objects.get(email=internal_email)
        except User.DoesNotExist:
            pass

    return getattr(org, "created_by", None) or getattr(org, "modified_by", None)
