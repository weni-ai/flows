import uuid

import sentry_sdk
from redis.exceptions import RedisError
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from django.db import transaction
from django.db.models import F, Min, Prefetch

from temba.api.auth.jwt import JWTAuthMixinRequired
from temba.api.support import InvalidQueryError
from temba.api.v2.internals.msgs import idempotency
from temba.api.v2.internals.msgs.observability import (
    OUTCOME_CONFLICT,
    OUTCOME_CREATED,
    OUTCOME_ERROR,
    OUTCOME_PROJECT_NOT_FOUND,
    OUTCOME_REJECTED_AUTH,
    OUTCOME_REJECTED_TENANT,
    OUTCOME_REJECTED_VALIDATION,
    OUTCOME_REPLAYED,
    REASON_DEDUPE_UNAVAILABLE,
    REASON_UNEXPECTED,
    bind_request_scope,
    extract_correlation_id,
    log_outcome,
)
from temba.api.v2.internals.msgs.permissions import ModuleJWTProjectScope
from temba.api.v2.internals.msgs.serializers import InternalMsgReadSerializer, MsgStreamSerializer
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.views_base import CreatedOnCursorPagination
from temba.channels.models import Channel
from temba.contacts.models import URN, Contact, ContactURN
from temba.msgs.models import Label, Msg, SystemLabel
from temba.orgs.models import Org

from .services import create_message_db_only


class InternalMessagesView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    DEFAULT_LIMIT = 10
    MAX_LIMIT = 10

    def normalize_urn(self, org, value):
        """
        Normalizes a URN string based on the organization's settings.
        """
        if org.is_anon:
            raise InvalidQueryError("URN lookups not allowed for anonymous organizations")

        try:
            return URN.identity(URN.normalize(value, country_code=org.default_country_code))
        except ValueError:
            raise InvalidQueryError("Invalid URN: %s" % value)

    class Pagination(CreatedOnCursorPagination):
        """
        Overridden paginator for Messages endpoint that switches from created_on to modified_on when looking
        at all incoming messages.
        """

        def get_ordering(self, request, queryset, view=None):
            if request.query_params.get("folder", "").lower() == "incoming":
                return "-modified_on", "-id"
            else:
                return CreatedOnCursorPagination.ordering

    FOLDER_FILTERS = {
        "inbox": SystemLabel.TYPE_INBOX,
        "flows": SystemLabel.TYPE_FLOWS,
        "archived": SystemLabel.TYPE_ARCHIVED,
        "outbox": SystemLabel.TYPE_OUTBOX,
        "failed": SystemLabel.TYPE_FAILED,
        "sent": SystemLabel.TYPE_SENT,
    }

    def get_filtered_queryset(self, org):
        """Get the filtered queryset based on request parameters."""
        params = self.request.query_params
        folder = params.get("folder")

        # Base queryset
        if folder:
            sys_label = self.FOLDER_FILTERS.get(folder.lower())
            if sys_label:
                queryset = SystemLabel.get_queryset(org, sys_label)
            elif folder == "incoming":
                queryset = Msg.objects.filter(org=org, direction="I")
            else:
                queryset = Msg.objects.filter(pk=-1)
        else:
            queryset = Msg.objects.filter(org=org).exclude(visibility=Msg.VISIBILITY_DELETED).exclude(msg_type=None)

        # Filter by contact_urn (optional)
        contact_urn = params.get("contact_urn")
        if contact_urn:
            contact = Contact.objects.filter(
                org=org, is_active=True, urns__identity=self.normalize_urn(org, contact_urn)
            ).first()
            queryset = queryset.filter(contact=contact)

        # Use prefetch rather than select_related for foreign keys to avoid joins
        queryset = queryset.prefetch_related(
            Prefetch("contact", queryset=Contact.objects.only("uuid", "name")),
            Prefetch("contact_urn", queryset=ContactURN.objects.only("scheme", "path", "display")),
            Prefetch("channel", queryset=Channel.objects.only("uuid", "name")),
            Prefetch("labels", queryset=Label.label_objects.only("uuid", "name").order_by("pk")),
        )

        channel_uuid = params.get("channel_uuid")
        if channel_uuid:
            queryset = queryset.filter(channel__uuid=channel_uuid)

        # Filter by before/after
        before = params.get("before")
        after = params.get("after")

        if folder and folder.lower() == "incoming":
            if before:
                queryset = queryset.filter(modified_on__lt=before)
            if after:
                queryset = queryset.filter(modified_on__gt=after)
        else:
            if before:
                queryset = queryset.filter(created_on__lt=before)
            if after:
                queryset = queryset.filter(created_on__gt=after)

        return queryset

    def get(self, request, *args, **kwargs):
        project_uuid = request.query_params.get("project_uuid")

        if not project_uuid:
            return Response({"error": "Project not provided"}, status=401)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        queryset = self.get_filtered_queryset(org)

        # Get limit from query params, use default if not provided
        try:
            limit = int(request.query_params.get("limit", self.DEFAULT_LIMIT))
            # Ensure limit doesn't exceed maximum
            limit = min(limit, self.MAX_LIMIT)
        except ValueError:
            limit = self.DEFAULT_LIMIT

        pagination = self.Pagination()
        pagination.page_size = limit
        page = pagination.paginate_queryset(queryset, request, self)
        serializer = InternalMsgReadSerializer(page, many=True, context={"org": org})

        return pagination.get_paginated_response(serializer.data)


class MsgStreamView(JWTAuthMixinRequired, APIViewMixin, APIView):
    permission_classes = [ModuleJWTProjectScope]

    def get_authenticate_header(self, request):
        # AD-004 rule 4: every JWT failure on this endpoint is 403. Returning no
        # challenge stops DRF from rewriting that failure to 401, including if the
        # shared authenticator later starts advertising WWW-Authenticate.
        return None

    def handle_exception(self, exc):
        project_uuid, channel_uuid, correlation_id = self._request_ids(self.request)
        if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            self._log(OUTCOME_REJECTED_AUTH, 403, project_uuid, channel_uuid, correlation_id, False)
        elif isinstance(exc, PermissionDenied):
            self._log(OUTCOME_REJECTED_TENANT, 403, project_uuid, channel_uuid, correlation_id, False)
        return super().handle_exception(exc)

    def post(self, request, *args, **kwargs):
        project_uuid, channel_uuid, correlation_id = self._request_ids(request)
        bind_request_scope(project_uuid=project_uuid, channel_uuid=channel_uuid, correlation_id=correlation_id)

        key = idempotency.extract_key(request)
        normalized_project = self._normalize_uuid(project_uuid)
        reserved = False
        body_hash = None
        if key and normalized_project:
            body_hash = idempotency.body_hash(request)
            try:
                state, replay_ids = idempotency.claim(normalized_project, key, body_hash)
            except RedisError:
                self._log(
                    OUTCOME_ERROR,
                    503,
                    normalized_project,
                    channel_uuid,
                    correlation_id,
                    True,
                    reason=REASON_DEDUPE_UNAVAILABLE,
                )
                return Response({"error": idempotency.SERVICE_UNAVAILABLE_ERROR}, status=503)
            if state == idempotency.CLAIM_HIT:
                self._log(OUTCOME_REPLAYED, 200, normalized_project, channel_uuid, correlation_id, True)
                return Response({"ids": replay_ids}, status=200)
            if state == idempotency.CLAIM_CONFLICT:
                self._log(
                    OUTCOME_CONFLICT,
                    409,
                    normalized_project,
                    channel_uuid,
                    correlation_id,
                    True,
                    reason=idempotency.CODE_IDEMPOTENCY_CONFLICT,
                )
                return Response(
                    {"code": idempotency.CODE_IDEMPOTENCY_CONFLICT, "error": idempotency.CONFLICT_ERROR},
                    status=409,
                )
            if state == idempotency.CLAIM_IN_PROGRESS:
                self._log(
                    OUTCOME_CONFLICT,
                    409,
                    normalized_project,
                    channel_uuid,
                    correlation_id,
                    True,
                    reason=idempotency.CODE_IDEMPOTENCY_IN_PROGRESS,
                )
                return Response(
                    {"code": idempotency.CODE_IDEMPOTENCY_IN_PROGRESS, "error": idempotency.IN_PROGRESS_ERROR},
                    status=409,
                )
            reserved = True

        serializer = MsgStreamSerializer(data=request.data)
        if not serializer.is_valid():
            self._release(normalized_project, key, reserved)
            self._log(
                OUTCOME_REJECTED_VALIDATION,
                400,
                normalized_project or project_uuid,
                channel_uuid,
                correlation_id,
                bool(key),
            )
            return Response(serializer.errors, status=400)

        data = serializer.validated_data
        try:
            org = Org.objects.get(proj_uuid=data["project_uuid"])
        except Org.DoesNotExist:
            self._release(normalized_project, key, reserved)
            self._log(OUTCOME_PROJECT_NOT_FOUND, 404, normalized_project, channel_uuid, correlation_id, bool(key))
            return Response({"error": "Project not found"}, status=404)

        # pick content field
        msg_data = data.get("msg") or {}
        text = data.get("text") or data.get("message") or msg_data.get("text") or ""
        attachments = data.get("attachments") or msg_data.get("attachments")

        # template can be a string (legacy) or a dict (whatsapp)
        template = data.get("template") or msg_data.get("template")

        contact_uuid = str(data.get("contact_uuid")) if data.get("contact_uuid") else None
        urns = data.get("urns") or [None]
        channel_for_msg = str(data.get("channel_uuid")) if data.get("channel_uuid") else None

        def create_ids():
            created_ids = []
            for urn in urns:
                msg = create_message_db_only(
                    org=org,
                    direction=data["direction"],
                    text=text,
                    contact_uuid=contact_uuid,
                    urn=urn,
                    channel_uuid=channel_for_msg,
                    status=data.get("status"),
                    created_on=data.get("created_on"),
                    sent_on=data.get("sent_on"),
                    attachments=attachments,
                    visibility=data.get("visibility"),
                    labels=data.get("labels"),
                    template=template,
                    metadata=msg_data,
                )
                created_ids.append(msg.id)
            return created_ids

        try:
            if reserved:
                with transaction.atomic():
                    created_ids = create_ids()
                    idempotency.store_success(normalized_project, key, body_hash, created_ids)
            else:
                created_ids = create_ids()
        except ValueError as exc:
            self._release(normalized_project, key, reserved)
            self._log(OUTCOME_REJECTED_VALIDATION, 400, normalized_project, channel_uuid, correlation_id, bool(key))
            return Response({"error": str(exc)}, status=400)
        except RedisError:
            self._release(normalized_project, key, reserved)
            self._log(
                OUTCOME_ERROR,
                503,
                normalized_project,
                channel_uuid,
                correlation_id,
                True,
                reason=REASON_DEDUPE_UNAVAILABLE,
            )
            return Response({"error": idempotency.SERVICE_UNAVAILABLE_ERROR}, status=503)
        except Exception:
            self._release(normalized_project, key, reserved)
            self._log(
                OUTCOME_ERROR,
                500,
                normalized_project,
                channel_uuid,
                correlation_id,
                bool(key),
                reason=REASON_UNEXPECTED,
            )
            sentry_sdk.capture_exception()
            raise

        self._log(OUTCOME_CREATED, 201, normalized_project or project_uuid, channel_uuid, correlation_id, bool(key))
        return Response({"ids": created_ids}, status=201)

    def _request_ids(self, request):
        data = request.data if isinstance(getattr(request, "data", None), dict) else {}
        project_uuid = data.get("project_uuid") if isinstance(data.get("project_uuid"), str) else None
        channel_uuid = data.get("channel_uuid") if isinstance(data.get("channel_uuid"), str) else None
        return project_uuid, channel_uuid, extract_correlation_id(request)

    def _normalize_uuid(self, value):
        if not value:
            return None
        try:
            return str(uuid.UUID(value))
        except ValueError:
            return None

    def _release(self, project_uuid, key, reserved):
        if reserved:
            idempotency.release(project_uuid, key)

    def _log(self, outcome, status, project_uuid, channel_uuid, correlation_id, key_present, reason=None):
        log_outcome(
            outcome,
            status=status,
            project_uuid=project_uuid,
            channel_uuid=channel_uuid,
            correlation_id=correlation_id,
            idempotency_key_present=key_present,
            reason=reason,
        )


class FirstContactsPagination(LimitOffsetPagination):
    default_limit = 500
    max_limit = 1000


class InternalFirstContactsView(JWTAuthMixinRequired, APIViewMixin, APIView):
    def get(self, request, *args, **kwargs):
        project_uuid = request.query_params.get("project_uuid")

        if not project_uuid:
            return Response({"error": "project_uuid is required"}, status=400)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        channel_uuid = request.query_params.get("channel_uuid")
        after = request.query_params.get("after")
        before = request.query_params.get("before")

        if not channel_uuid:
            return Response({"error": "channel_uuid is required"}, status=400)
        if not after:
            return Response({"error": "after is required"}, status=400)
        if not before:
            return Response({"error": "before is required"}, status=400)

        queryset = (
            Msg.objects.filter(
                org=org,
                channel__uuid=channel_uuid,
                created_on__gte=after,
                created_on__lt=before,
                direction=Msg.DIRECTION_IN,
            )
            .exclude(status__in=[Msg.STATUS_FAILED, Msg.STATUS_ERRORED])
            .values(contact_urn_identity=F("contact_urn__identity"))
            .annotate(first_created_on=Min("created_on"))
            .order_by("contact_urn_identity")
        )

        paginator = FirstContactsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)

        return paginator.get_paginated_response(page)
