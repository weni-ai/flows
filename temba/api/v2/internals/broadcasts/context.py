"""
Shared resolve logic for WhatsApp broadcast internal endpoints (sync, deferred, FastAPI bridge).
"""

import json

from django.contrib.auth import get_user_model

from temba.orgs.models import Org


User = get_user_model()


def celery_json_safe_broadcast_payload(data: dict) -> dict:
    """Round-trip so UUID/datetime/other values become JSON-compatible for Celery brokers."""
    return json.loads(json.dumps(data, default=str))


def resolve_org_and_user_internal_whatsapp(*, drf_request, data):
    """
    Mirrors InternalWhatsappBroadcastsEndpoint: resolve org by project UUID and user by JWT/email or request.user.

    drf_request: rest_framework.request.Request (optional .jwt_payload already set).
    data: mutable dict-like body with optional "project".
    Raises ValueError with an error message usable for HTTP responses when resolution fails.
    """
    project_uuid = data.get("project") or getattr(drf_request, "project_uuid", None)

    if not project_uuid:
        raise ValueError("Project not provided")

    try:
        org = Org.objects.get(proj_uuid=project_uuid)
    except Org.DoesNotExist:
        raise ValueError("Project not found")

    if getattr(drf_request, "jwt_payload", None):
        email = (
            drf_request.jwt_payload.get("email")
            or drf_request.jwt_payload.get("user_email")
            or data.get("user_email")
        )
    else:
        email = getattr(getattr(drf_request, "user", None), "email", None)

    if not email:
        raise ValueError("User email not provided")

    user, _ = User.objects.get_or_create(email=email)

    # Ensure serializers that read request.org see the resolved org where applicable.
    setattr(drf_request, "_org", org)
