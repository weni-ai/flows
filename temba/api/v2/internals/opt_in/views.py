import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from weni_commons.auth import CanCommunicateInternally as WeniCanCommunicateInternally, WeniAuthentication
from weni_commons.auth.helpers import get_auth_context

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Prefetch

from temba.api.v2.internals.opt_in.serializers import OptInContactCreateSerializer, OptInIdentifierSerializer
from temba.api.v2.internals.views import APIViewMixin
from temba.contacts.models import Contact, ContactGroup
from temba.contacts.usecases.opt_in import OptInUnavailable, create_opt_in_contact, ensure_audience, fill_identifier
from temba.orgs.models import Org

logger = logging.getLogger(__name__)
User = get_user_model()


class OptInView(APIViewMixin, APIView):
    authentication_classes = [WeniAuthentication]
    permission_classes = [WeniCanCommunicateInternally]

    def org_or_response(self, request):
        auth = get_auth_context(request)
        project_uuid = getattr(auth, "project_uuid", None)
        if not project_uuid:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            return Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

    def internal_user(self):
        return User.objects.get(email=settings.INTERNAL_USER_EMAIL)

    def log_outcome(self, org, endpoint, outcome, contact_uuid=None):
        logger.info(
            "opt_in org_id=%s endpoint=%s outcome=%s contact_uuid=%s",
            org.id,
            endpoint,
            outcome,
            contact_uuid or "",
        )


def _audience_body(group):
    return {"group_uuid": str(group.uuid), "name": group.name, "count": group.get_member_count()}


class OptInAudienceView(OptInView):
    def get(self, request):
        org = self.org_or_response(request)
        if isinstance(org, Response):
            return org
        group = ContactGroup.user_groups.filter(org=org, is_opt_in=True).first()
        if not group:
            self.log_outcome(org, "audience", "opt_in_audience_missing")
            return Response({"error": "opt_in_audience_missing"}, status=status.HTTP_404_NOT_FOUND)
        self.log_outcome(org, "audience", "ok")
        return Response(_audience_body(group))

    def post(self, request):
        org = self.org_or_response(request)
        if isinstance(org, Response):
            return org
        result = ensure_audience(org, self.internal_user())
        if result.error:
            self.log_outcome(org, "audience", result.error)
            code = status.HTTP_400_BAD_REQUEST if result.error == "group_limit_reached" else status.HTTP_409_CONFLICT
            return Response({"error": result.error}, status=code)
        self.log_outcome(org, "audience", "created" if result.created else "ok")
        body = _audience_body(result.group)
        return Response(body, status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK)


class OptInContactCreateView(OptInView):
    def post(self, request):
        org = self.org_or_response(request)
        if isinstance(org, Response):
            return org
        serializer = OptInContactCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = create_opt_in_contact(
                org, self.internal_user(), data["name"], data["whatsapp"], data.get("email")
            )
        except OptInUnavailable:
            self.log_outcome(org, "contacts", "contact_service_unavailable")
            return Response({"error": "contact_service_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if result.outcome == "missing":
            self.log_outcome(org, "contacts", "opt_in_audience_missing")
            return Response({"error": "opt_in_audience_missing"}, status=status.HTTP_409_CONFLICT)
        if result.outcome == "duplicate":
            self.log_outcome(org, "contacts", "duplicate_number")
            return Response({"outcome": "duplicate_number"})
        self.log_outcome(org, "contacts", "created", contact_uuid=str(result.contact.uuid))
        return Response(
            {
                "outcome": "created",
                "contact_uuid": str(result.contact.uuid),
                "group_uuid": str(result.group.uuid),
            },
            status=status.HTTP_201_CREATED,
        )


class OptInContactFillView(OptInView):
    def patch(self, request, contact_uuid):
        org = self.org_or_response(request)
        if isinstance(org, Response):
            return org
        contact = (
            Contact.objects.filter(org=org, uuid=contact_uuid, is_active=True)
            .prefetch_related(
                Prefetch("all_groups", queryset=ContactGroup.user_groups.all(), to_attr="prefetched_user_groups")
            )
            .first()
        )
        if not contact:
            self.log_outcome(org, "contacts_fill", "not_found")
            return Response({"error": "Contact not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = OptInIdentifierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            outcome = fill_identifier(org, self.internal_user(), contact, serializer.validated_data["email"])
        except OptInUnavailable:
            self.log_outcome(org, "contacts_fill", "contact_service_unavailable", contact_uuid=str(contact.uuid))
            return Response({"error": "contact_service_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        self.log_outcome(org, "contacts_fill", outcome, contact_uuid=str(contact.uuid))
        return Response({"outcome": outcome})
