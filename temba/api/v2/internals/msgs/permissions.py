"""Tenant scope for the internal stream endpoint.

Lives on this view only. The shared JWT authenticator and JWTAuthMixinRequired
stay unchanged.
"""

import uuid
from collections.abc import Mapping

from rest_framework.permissions import BasePermission

from django.core.exceptions import ValidationError

from temba.api.auth.jwt import jwt_tenant_claims
from temba.channels.models import Channel


class ModuleJWTProjectScope(BasePermission):
    """Allow the call only when the body project is the one in the module JWT.

    A missing body project is left to the serializer, which rejects it with 400.
    An invalid or different project is denied here, before idempotency and before
    any write.
    """

    def has_permission(self, request, view):
        project_claim, channel_claim = jwt_tenant_claims(getattr(request, "jwt_payload", None))
        authorized = self._authorized_project(project_claim, channel_claim)
        if authorized is None:
            return False

        data = getattr(request, "data", None)
        if isinstance(data, Mapping) and "project_uuid" in data:
            try:
                body_project = uuid.UUID(str(data.get("project_uuid")))
            except (ValueError, TypeError, AttributeError):
                return False
            if body_project != authorized:
                return False
        return True

    def _authorized_project(self, project_claim, channel_claim):
        if project_claim and channel_claim:
            if not self._channel_belongs_to_project(channel_claim, project_claim):
                return None
            return self._parse_uuid(project_claim)
        if project_claim:
            return self._parse_uuid(project_claim)
        if channel_claim:
            channel = self._active_channel(channel_claim)
            if channel is None:
                return None
            return channel.org.proj_uuid
        return None

    def _parse_uuid(self, value):
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    def _active_channel(self, channel_uuid):
        try:
            return Channel.objects.filter(uuid=channel_uuid, is_active=True).select_related("org").first()
        except (ValidationError, ValueError):
            return None

    def _channel_belongs_to_project(self, channel_uuid, project_uuid):
        try:
            return Channel.objects.filter(uuid=channel_uuid, is_active=True, org__proj_uuid=project_uuid).exists()
        except (ValidationError, ValueError):
            return False
