from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from django.contrib.auth.models import User
from django.db.models import Prefetch

from temba.api.auth.jwt import JWTAuthMixinRequired
from temba.api.support import InvalidQueryError
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
            user, _ = User.objects.get_or_create(email=request.user.email)
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
        serializer = InternalMsgReadSerializer(page, many=True, context={"org": org, "user": user})

        return pagination.get_paginated_response(serializer.data)


class MsgStreamView(APIViewMixin, APIView, JWTAuthMixinRequired):
    def post(self, request, *args, **kwargs):
        serializer = MsgStreamSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        project_uuid = data["project_uuid"]
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        # pick content field
        msg_data = data.get("msg") or {}
        text = data.get("text") or data.get("message") or msg_data.get("text") or ""
        attachments = data.get("attachments") or msg_data.get("attachments")

        # template can be a string (legacy) or a dict (whatsapp)
        template = data.get("template") or msg_data.get("template")

        try:
            msg = create_message_db_only(
                org=org,
                direction=data["direction"],
                text=text,
                contact_uuid=str(data.get("contact_uuid")) if data.get("contact_uuid") else None,
                urn=data.get("urn"),
                channel_uuid=str(data.get("channel_uuid")) if data.get("channel_uuid") else None,
                status=data.get("status"),
                created_on=data.get("created_on"),
                sent_on=data.get("sent_on"),
                attachments=attachments,
                visibility=data.get("visibility"),
                labels=data.get("labels"),
                template=template,
                metadata=msg_data,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        return Response({"id": msg.id}, status=201)
