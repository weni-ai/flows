import datetime as dt

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import exceptions as django_exceptions
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from temba.api.v2.internals.contacts.serializers import (
    ContactWithMessagesListSerializer,
    InternalContactFieldsValuesSerializer,
    InternalContactSerializer,
)
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.api.v2.serializers import ContactFieldReadSerializer, ContactFieldWriteSerializer
from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import Contact, ContactField, ContactGroup, ContactURN
from temba.msgs.models import Msg
from temba.orgs.models import Org
from temba.tickets.models import Ticket

User = get_user_model()


class InternalContactView(APIViewMixin, APIView):
    def post(self, request: Request):
        params = request.query_params
        token = params.get("token")

        if token is None:
            raise NotAuthenticated()

        if token != settings.BILLING_FIXED_ACCESS_TOKEN:
            raise AuthenticationFailed()

        serializer = InternalContactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contacts_uuids = serializer.validated_data.get("contacts")

        contacts = (
            Contact.objects.filter(uuid__in=contacts_uuids)
            .select_related("org")
            .only("uuid", "org__proj_uuid", "name")
        )

        response = {"results": []}

        for contact in contacts:
            contact_data = {
                "uuid": str(contact.uuid),
                "project_uuid": str(contact.org.proj_uuid),
                "name": contact.name,
                "urns": contact.get_urns().values("identity"),
            }

            response["results"].append(contact_data)

        return Response(response)


class InternalContactFieldsEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated & (CanCommunicateInternally | IsUserInOrg)]

    def get(self, request, *args, **kwargs):
        query_params = request.query_params
        project_uuid = query_params.get("project")
        key = query_params.get("key")

        if not project_uuid:
            return Response({"error": "Project not provided"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError):
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        contact_fields = ContactField.user_fields.filter(org=org, is_active=True)

        if key:
            contact_fields = contact_fields.filter(key=key)

        serializer = ContactFieldReadSerializer(contact_fields, many=True)

        return Response({"results": serializer.data})

    def post(self, request, *args, **kwargs):
        project_uuid = request.data.get("project")

        if not project_uuid:
            return Response({"error": "Project not provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
            user = User.objects.get(email=request.user.email)
        except (Org.DoesNotExist, django_exceptions.ValidationError):
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = ContactFieldWriteSerializer(
            data=request.data, context={"request": request, "org": org, "user": user}
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.validated_data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UpdateContactFieldsView(APIViewMixin, APIView, LambdaURLValidator):
    renderer_classes = [JSONRenderer]

    def patch(self, request, *args, **kwargs):
        validation_response = self.protected_resource(request)  # pragma: no cover
        if validation_response.status_code != 200:  # pragma: no cover
            return validation_response
        serializer = InternalContactFieldsValuesSerializer(data=request.data)
        if serializer.is_valid():
            serializer.update(instance=None, validated_data=serializer.validated_data)
            return Response({"message": "Contact fields updated successfully"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContactHasOpenTicketView(APIViewMixin, APIView):
    def get(self, request: Request):
        contact_urn = request.query_params.get("contact_urn")
        if contact_urn is None:
            return Response(status=400)
        try:
            contactURN = ContactURN.objects.get(identity=contact_urn)
        except ContactURN.DoesNotExist:
            return Response(status=404)

        has_open_ticket = Ticket.objects.filter(contact_id=contactURN.contact_id, status=Ticket.STATUS_OPEN).exists()
        return Response({"has_open_ticket": has_open_ticket})


# Service function for business logic
class ContactsWithMessagesService:
    @staticmethod
    def get_contacts_with_messages(org, start_date, end_date):
        contacts = org.contacts.filter(is_active=True, created_on__gte=start_date, created_on__lte=end_date)
        return contacts.prefetch_related(
            models.Prefetch(
                "msgs",
                queryset=Msg.objects.filter(
                    created_on__gte=start_date, created_on__lte=end_date, direction=Msg.DIRECTION_IN
                ).order_by("created_on"),
                to_attr="filtered_msgs",
            )
        )


class ContactsWithMessagesCursorPagination(CursorPagination):
    ordering = "created_on"
    page_size = 10
    page_size_query_param = "limit"
    max_page_size = 500


class ContactsWithMessagesView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    def get(self, request: Request):
        project_uuid = request.query_params.get("project")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if project_uuid is None:
            return Response({"error": "Project is required"}, status=400)
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)
        if not start_date or not end_date:
            return Response({"error": "start_date and end_date are required"}, status=400)

        # Accept date (YYYY-MM-DD) or datetime with timezone, minimal validation
        start_dt = parse_datetime(start_date)
        end_dt = parse_datetime(end_date)
        if not start_dt:
            d = parse_date(start_date)
            if d:
                start_dt = dt.datetime.combine(d, dt.time.min, tzinfo=timezone.utc)
        if not end_dt:
            d = parse_date(end_date)
            if d:
                end_dt = dt.datetime.combine(d, dt.time.max, tzinfo=timezone.utc)
        if not start_dt or not end_dt:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD or ISO 8601 with timezone."}, status=400)
        # If parsed datetimes are naive, make them UTC
        if timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt, timezone.utc)
        if timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt, timezone.utc)

        # Take all contacts created in the period
        all_contacts_qs = ContactsWithMessagesService.get_contacts_with_messages(org, start_dt, end_dt).order_by(
            "created_on"
        )
        paginator = ContactsWithMessagesCursorPagination()
        page = paginator.paginate_queryset(all_contacts_qs, request, view=self)
        contact_results = []
        for contact in page:
            filtered_msgs = getattr(contact, "filtered_msgs", [])
            if filtered_msgs:
                contact_results.append(
                    {
                        "contact_id": contact.id,
                        "messages": [
                            {"contact_id": contact.id, "msg_text": msg.text, "msg_created_on": msg.created_on}
                            for msg in sorted(filtered_msgs, key=lambda x: x.created_on, reverse=True)
                        ],
                    }
                )
        serializer = ContactWithMessagesListSerializer(contact_results, many=True)
        return paginator.get_paginated_response(serializer.data)


class GroupContactFieldsService:
    @staticmethod
    def _build_field_payload(field, example_value):
        return {
            "key": field.key,
            "label": field.label,
            "value_type": ContactFieldReadSerializer.VALUE_TYPES[field.value_type],
            "pinned": field.show_in_table,
            "example": example_value,
        }

    @classmethod
    def get_fields_with_examples(cls, org: Org, groups_qs):
        dynamic_fields_qs = (
            ContactField.user_fields.filter(org=org, is_active=True, dependent_groups__in=groups_qs)
            .only("id", "uuid", "key", "label", "value_type", "show_in_table")
            .distinct()
        )

        uuids_in_contacts = set()
        group_contacts_qs = (
            Contact.objects.filter(org=org, is_active=True, all_groups__in=groups_qs).only("fields").distinct()
        )
        for contact in group_contacts_qs.iterator(chunk_size=1000):
            if contact.fields:
                uuids_in_contacts.update(contact.fields.keys())

        contacts_fields_qs = (
            ContactField.user_fields.filter(org=org, is_active=True, uuid__in=list(uuids_in_contacts))
            .only("id", "uuid", "key", "label", "value_type", "show_in_table")
            .distinct()
        )

        field_map = {f.id: f for f in dynamic_fields_qs}
        for f in contacts_fields_qs:
            field_map.setdefault(f.id, f)
        fields = sorted(field_map.values(), key=lambda f: f.label)

        examples = {f.id: None for f in fields}
        pending_ids = set(examples.keys())
        for contact in group_contacts_qs.iterator(chunk_size=1000):
            if not pending_ids:
                break
            for f in fields:
                if f.id not in pending_ids:
                    continue
                value = contact.get_field_serialized(f)
                if value not in (None, "", []):
                    examples[f.id] = value
                    pending_ids.discard(f.id)

        return [cls._build_field_payload(f, examples.get(f.id)) for f in fields]


class GroupsContactFieldsView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request: Request):
        params = request.query_params
        project_uuid = params.get("project_uuid") or params.get("project")
        group_ids_param = params.get("group_ids")

        if not project_uuid:
            return Response({"error": "Project not provided"}, status=status.HTTP_400_BAD_REQUEST)
        if not group_ids_param:
            return Response({"error": "group_ids not provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError):
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        # parse comma-separated list; accept ONLY numeric IDs
        raw_tokens = [t.strip() for t in group_ids_param.split(",") if t.strip()]
        if not raw_tokens:
            return Response(
                {"error": "group_ids must be a comma-separated list of integers"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            numeric_ids = [int(tok) for tok in raw_tokens]
        except (TypeError, ValueError):
            return Response({"error": "group_ids must contain only integers"}, status=status.HTTP_400_BAD_REQUEST)

        groups_qs = ContactGroup.user_groups.filter(org=org, is_active=True, id__in=numeric_ids)

        if not groups_qs.exists():
            return Response({"error": "No groups found"}, status=status.HTTP_404_NOT_FOUND)

        results = GroupContactFieldsService.get_fields_with_examples(org, groups_qs)
        return Response({"results": results})
