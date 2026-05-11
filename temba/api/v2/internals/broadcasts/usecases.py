from rest_framework import status
from rest_framework.response import Response

from django.contrib.auth import get_user_model

from temba.api.v2.serializers import WhatsappBroadcastReadSerializer, WhatsappBroadcastWriteSerializer
from temba.orgs.models import Org

from .idempotency import (
    LOOKUP_CONFLICT,
    LOOKUP_HIT,
    LOOKUP_INFLIGHT,
    compute_body_hash,
    extract_idempotency_key,
    idempotency_lookup,
    idempotency_release,
    idempotency_store_success,
)

User = get_user_model()


class CreateWhatsappBroadcastUseCase:
    """
    Orchestrates the internal WhatsApp broadcast endpoint: resolves the
    authenticated user, runs the write serializer, and (optionally) enforces
    the Idempotency-Key contract documented in
    ``bulk_send/docs/idempotency-key.md``.

    The use case owns the full request-to-response lifecycle so the view can
    stay a one-liner. Idempotency is transparent: when the header is absent,
    behavior is identical to the legacy flow.
    """

    def execute(self, request, project_uuid) -> Response:
        idem_key = extract_idempotency_key(request)
        body_hash = compute_body_hash(request) if idem_key else None

        if idem_key:
            short_circuit = self._check_idempotency(project_uuid, idem_key, body_hash)
            if short_circuit is not None:
                return short_circuit

        try:
            response = self._create_broadcast(request, project_uuid)
        except Exception:
            if idem_key:
                idempotency_release(project_uuid, idem_key)
            raise

        if idem_key:
            self._finalize_idempotency(project_uuid, idem_key, body_hash, response)

        return response

    def _check_idempotency(self, project_uuid, idem_key: str, body_hash: str) -> Response | None:
        lookup_state, cached = idempotency_lookup(project_uuid, idem_key, body_hash)
        if lookup_state == LOOKUP_HIT:
            return Response(cached["body"], status=cached["status"])
        if lookup_state == LOOKUP_CONFLICT:
            return Response(
                {"error": "Idempotency-Key reused with different body"},
                status=status.HTTP_409_CONFLICT,
            )
        if lookup_state == LOOKUP_INFLIGHT:
            return Response(
                {"error": "Request with this Idempotency-Key is already being processed"},
                status=status.HTTP_409_CONFLICT,
            )
        return None

    def _finalize_idempotency(self, project_uuid, idem_key: str, body_hash: str, response: Response) -> None:
        if 200 <= response.status_code < 300:
            idempotency_store_success(project_uuid, idem_key, body_hash, response.status_code, response.data)
        else:
            idempotency_release(project_uuid, idem_key)

    def _create_broadcast(self, request, project_uuid) -> Response:
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        # When authenticated via JWT, prefer email from token; otherwise use request.user
        if getattr(request, "jwt_payload", None):
            email = (
                request.jwt_payload.get("email")
                or request.jwt_payload.get("user_email")
                or request.data.get("user_email")
            )
        else:
            email = getattr(request.user, "email", None)

        if not email:
            return Response({"error": "User email not provided"}, status=401)

        user, _ = User.objects.get_or_create(email=email)

        serializer = WhatsappBroadcastWriteSerializer(
            data=request.data, context={"request": request, "org": org, "user": user}
        )

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        broadcast = serializer.save()
        response_serializer = WhatsappBroadcastReadSerializer(
            instance=broadcast, context={"request": request, "org": org, "user": user}
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
