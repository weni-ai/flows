import datetime as dt
import logging
from pathlib import Path
from typing import Optional

import pyexcel
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
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
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.db.transaction import on_commit as on_transaction_commit
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from temba.api.auth.jwt import OptionalJWTAuthentication
from temba.api.v2.internals.contacts.serializers import (
    ContactWithMessagesListSerializer,
    InternalContactFieldsValuesSerializer,
    InternalContactSerializer,
)
from temba.api.v2.internals.contacts.services import ContactImportDeduplicationService
from temba.api.v2.internals.helpers import get_object_or_404
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import HasValidJWT, IsUserInOrg
from temba.api.v2.serializers import (
    ContactFieldReadSerializer,
    ContactFieldWriteSerializer,
    ContactGroupWriteSerializer,
)
from temba.api.v2.validators import LambdaURLValidator
from temba.api.v2.views_base import DefaultLimitOffsetPagination
from temba.channels.models import Channel
from temba.contacts.models import Contact, ContactField, ContactGroup, ContactImport, ContactURN, ExportContactsTask
from temba.contacts.tasks import export_contacts_by_status_task
from temba.contacts.views import ContactImportCRUDL
from temba.msgs.models import Broadcast, Msg
from temba.orgs.models import Org
from temba.tickets.models import Ticket
from temba.utils.text import decode_stream

logger = logging.getLogger(__name__)

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
    authentication_classes = [OptionalJWTAuthentication, InternalOIDCAuthentication]
    permission_classes = [(IsAuthenticated & (CanCommunicateInternally | IsUserInOrg)) | HasValidJWT]

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
        email = self._get_request_email(request)
        project_uuid = request.data.get("project_uuid") or request.data.get("project")
        channel_uuid = request.data.get("channel_uuid") or request.data.get("channel")

        if project_uuid:
            self.org = get_object_or_404(Org, field_error_name="project", proj_uuid=project_uuid)

        elif channel_uuid:
            channel = get_object_or_404(Channel, field_error_name="channel", uuid=channel_uuid)
            self.org = channel.org
            if not self.org:
                return Response(
                    {"channel": "Channel is not associated with a project"}, status=status.HTTP_400_BAD_REQUEST
                )

        else:
            return Response(
                {"error": "At least either a channel or a project is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ContactFieldWriteSerializer(
            data=request.data,
            context={"request": request, "email": email, "org": self.org},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.validated_data)

    def _get_request_email(self, request):
        payload = getattr(request, "jwt_payload", None)
        if payload:
            return payload.get("email") or payload.get("user_email") or request.data.get("user_email")
        else:
            return request.data.get("user_email") or getattr(request.user, "email", None)


class UpdateContactFieldsView(APIViewMixin, APIView, LambdaURLValidator):
    authentication_classes = [OptionalJWTAuthentication]
    renderer_classes = [JSONRenderer]

    def patch(self, request, *args, **kwargs):
        if not getattr(request, "jwt_payload", None):
            validation_response = self.protected_resource(request)  # pragma: no cover
            if validation_response.status_code != 200:  # pragma: no cover
                return validation_response

        serializer = InternalContactFieldsValuesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.update(instance=None, validated_data=serializer.validated_data)

        return Response({"message": "Contact fields updated successfully"}, status=status.HTTP_200_OK)


class ContactGroupsService:
    @staticmethod
    def list_groups(org, name_filter: Optional[str], order_by: Optional[str]):
        queryset = ContactGroup.user_groups.filter(org=org, is_active=True)

        if name_filter:
            queryset = queryset.filter(name__icontains=name_filter)

        # Pre-compute member_count for ordering and response
        queryset = queryset.annotate(member_count=Coalesce(Sum("counts__count"), Value(0)))

        # Exclude groups with zero members
        queryset = queryset.filter(member_count__gt=0)

        ordering_map = {
            "name": "name",
            "-name": "-name",
            "member_count": "member_count",
            "-member_count": "-member_count",
            "created_on": "created_on",
            "-created_on": "-created_on",
        }
        # default to most recent first
        default_order = "-created_on"
        return queryset.order_by(ordering_map.get(order_by or default_order, default_order))


class InternalContactGroupsView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request: Request):
        """
        Get all contact groups from an organization (org) from the project_uuid.
        """
        project_uuid = request.query_params.get("project_uuid")
        if not project_uuid:
            return Response({"error": "Project not provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError):
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        name_filter = request.query_params.get("name")
        order_by = request.query_params.get("order_by") or request.query_params.get("order")
        groups = ContactGroupsService.list_groups(org, name_filter, order_by)
        paginator = DefaultLimitOffsetPagination()
        page = paginator.paginate_queryset(groups, request, view=self)
        results = []
        for group in page:
            results.append(
                {
                    "id": group.id,
                    "uuid": str(group.uuid),
                    "name": group.name,
                    "status": group.status,
                    "group_type": group.group_type,
                    "query": group.query,
                    "member_count": group.get_member_count(),
                }
            )
        return paginator.get_paginated_response(results)

    def post(self, request, *args, **kwargs):
        name = request.data.get("name")
        broadcast_id = request.data.get("broadcast_id")
        msg_status = request.data.get("status")

        # Validate required fields
        if not name:
            return Response({"error": "Name is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not broadcast_id:
            return Response({"error": "Broadcast ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        if msg_status:
            valid_statuses = [s[0] for s in Msg.STATUS_CHOICES]
            if msg_status not in valid_statuses:
                return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "Status is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Get org and user
        try:
            org = Broadcast.objects.get(id=broadcast_id).org
            user = User.objects.get(email=request.user.email)
        except (Org.DoesNotExist, django_exceptions.ValidationError, Broadcast.DoesNotExist):
            return Response({"error": "Project or Broadcast not found"}, status=status.HTTP_404_NOT_FOUND)

        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        # Create group
        group_serializer = ContactGroupWriteSerializer(data={"name": name}, context={"org": org, "user": user})
        group_serializer.is_valid(raise_exception=True)
        group = group_serializer.save()

        msgs = Msg.objects.filter(broadcast_id=broadcast_id, status=msg_status)

        contact_ids = msgs.values_list("contact_id", flat=True).distinct()
        contacts = Contact.objects.filter(id__in=contact_ids)

        # Add contacts to group
        group.contacts.add(*contacts)

        return Response(
            {
                "group_uuid": str(group.uuid),
                "group_name": group.name,
                "added_contacts": [str(c.uuid) for c in contacts],
                "count": contacts.count(),
            },
            status=status.HTTP_201_CREATED,
        )


class ContactsExportByStatusView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def post(self, request, *args, **kwargs):
        project_uuid = request.data.get("project_uuid") or request.data.get("project")
        broadcast_id = request.data.get("broadcast_id")
        msg_status = request.data.get("status")
        if not project_uuid:
            return Response({"error": "Project not provided"}, status=status.HTTP_400_BAD_REQUEST)

        # validate broadcast belongs to org
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
            broadcast = Broadcast.objects.get(id=broadcast_id)
            if broadcast.org_id != org.id:
                return Response({"error": "Broadcast not found for project"}, status=status.HTTP_404_NOT_FOUND)
        except (Org.DoesNotExist, Broadcast.DoesNotExist, django_exceptions.ValidationError):
            return Response({"error": "Project or Broadcast not found"}, status=status.HTTP_404_NOT_FOUND)

        # Optionally precompute count for response
        if msg_status:
            valid_statuses = [s[0] for s in Msg.STATUS_CHOICES]
            if msg_status not in valid_statuses:
                return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error": "Status is required"}, status=status.HTTP_400_BAD_REQUEST)

        msgs = Msg.objects.filter(broadcast_id=broadcast_id, status=msg_status)
        contact_count = msgs.values("contact_id").distinct().count()

        # create export record (we'll attach file in the async task)
        user = User.objects.get(email=request.user.email)
        export = ExportContactsTask.create(org=org, user=user, group=None, search=None, group_memberships=())

        # schedule background export building and notification
        on_transaction_commit(lambda: export_contacts_by_status_task.delay(export.pk, broadcast_id, msg_status))

        if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            message = f"We are preparing your export. We will e-mail you at {request.user.email} when it is ready."
            download_url = None
        else:
            # in eager mode, export may be ready immediately
            export.refresh_from_db()
            download_url = export.get_download_url()
            message = f"Export complete, you can find it here: {download_url}"

        return Response(
            {
                "export_id": export.id,
                "download_url": download_url,
                "count": contact_count,
                "message": message,
            },
            status=status.HTTP_201_CREATED,
        )


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


class ContactsImportUploadView(APIViewMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def post(self, request, *args, **kwargs):
        project_uuid = request.data.get("project_uuid")
        uploaded_file = request.FILES.get("file")
        if not project_uuid or not uploaded_file:
            return Response({"error": "Project and file are required."}, status=400)
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found."}, status=404)
        # Deduplicate uploaded file by UUID/URN and build duplicates XLSX if needed
        try:
            (
                mappings,
                num_records,
                dedup_tmp,
                dedup_ext,
                duplicates_url,
                duplicates_count,
                duplicates_error,
            ) = ContactImportDeduplicationService.process(org, uploaded_file, uploaded_file.name)
        except ValidationError as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            logger.exception("Error parsing import file")
            return Response({"error": f"Error parsing file: {str(e)}"}, status=400)
        # Extract example values from the deduplicated file before creating the import
        try:
            dedup_tmp.seek(0)
            examples = ContactImportPreviewService.extract_examples(dedup_tmp, f"dedup.{dedup_ext}", mappings)
        finally:
            dedup_tmp.seek(0)
        # Create the ContactImport object like the CRUDL
        # Use a system user if there is no authenticated request.user
        created_by_user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        if not created_by_user:
            internal_email = getattr(settings, "INTERNAL_USER_EMAIL", "")
            if internal_email:
                try:
                    created_by_user = User.objects.get(email=internal_email)
                except User.DoesNotExist:
                    created_by_user = None
        if not created_by_user:
            created_by_user = getattr(org, "created_by", None) or getattr(org, "modified_by", None)

        # Save the deduplicated file as the import source
        dedupulated_file = File(dedup_tmp, name=f"contacts_dedup.{dedup_ext}")

        contact_import = ContactImport.objects.create(
            org=org,
            file=dedupulated_file,
            original_filename=uploaded_file.name,
            mappings=mappings,
            num_records=num_records,
            status=ContactImport.STATUS_PENDING,
            created_by=created_by_user,
            modified_by=created_by_user,
        )
        # Create the fields/columns like the preview of the CRUDL
        org_fields = ContactField.user_fields.filter(org=org, is_active=True)
        fields = [{"key": f.key, "label": f.label, "type": f.value_type} for f in org_fields]
        columns = []
        for idx, item in enumerate(mappings):
            mapping = item["mapping"]
            col = {"header": item["header"], "example": examples[idx]}
            if mapping["type"] == "field":
                col["type"] = "field"
                col["matched_field"] = mapping["key"]
            elif mapping["type"] == "new_field":
                col["type"] = "new_field"
                col["suggested_type"] = mapping.get("value_type", "T")
            elif mapping["type"] == "attribute":
                col["type"] = "attribute"
                col["matched_field"] = mapping["name"]
            elif mapping["type"] == "scheme":
                col["type"] = "urn"
                col["matched_field"] = None
            else:
                col["type"] = mapping["type"]
            columns.append(col)
        # ensure duplicates_url is absolute when using non-S3 backends
        if duplicates_url and not str(duplicates_url).lower().startswith("http"):
            duplicates_url = request.build_absolute_uri(duplicates_url)

        # duplicates object (null if none). Include error message if S3 upload failed
        duplicates = None
        if duplicates_count:
            duplicates = {
                "download_url": duplicates_url,
                "count": duplicates_count,
                "error": duplicates_error,
            }

        return Response(
            {
                "import_id": contact_import.id,
                "num_records": num_records,
                "fields": fields,
                "columns": columns,
                "duplicates": duplicates,
                "errors": [],
            },
            status=200,
        )


class ContactsImportConfirmView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]
    parser_classes = [JSONParser]

    def get(self, request, import_id=None):
        if not import_id:
            return Response({"error": "import_id is required in URL."}, status=400)
        try:
            contact_import = ContactImport.objects.get(id=import_id)
        except ContactImport.DoesNotExist:
            return Response({"error": "Import not found."}, status=404)

        # ensure the requester is the same user who confirmed the import
        if not (getattr(request, "user", None) and request.user.is_authenticated):
            return Response({"error": "Forbidden."}, status=403)
        confirmer_id = contact_import.modified_by_id
        if not confirmer_id or request.user.id != confirmer_id:
            return Response({"error": "Forbidden."}, status=403)

        info = contact_import.get_info()
        group = contact_import.group
        if group:
            group = {
                "id": group.id,
                "uuid": str(group.uuid),
                "name": group.name,
                "status": group.status,
                "group_type": group.group_type,
                "query": group.query,
                "member_count": group.get_member_count(),
            }

        result = {
            "info": info,
            "group": group,
        }
        return Response(result, status=200)

    def post(self, request, import_id=None):
        project_uuid = request.data.get("project_uuid")
        if not project_uuid:
            return Response({"error": "Project is required."}, status=400)
        if not import_id:
            return Response({"error": "import_id is required in URL."}, status=400)
        try:
            contact_import = ContactImport.objects.get(id=import_id)
        except ContactImport.DoesNotExist:
            return Response({"error": "Import not found."}, status=404)
        # Simulate the form of the Preview of the CRUDL
        # Get the data from the request (add_to_group, group_mode, new_group_name, existing_group, columns, etc.)
        data = request.data.copy()

        # Instantiate the form of the Preview
        form_class = ContactImportCRUDL.Preview.form_class
        form = form_class(data, org=contact_import.org, instance=contact_import)
        if not form.is_valid():
            return Response({"error": form.errors}, status=400)
        # Save the changes in the mappings, groups, etc.
        obj = contact_import
        form_values = form.get_form_values()
        for i, fdata in enumerate(form_values):
            mapping = obj.mappings[i]["mapping"]
            if not fdata["include"]:
                mapping = ContactImport.MAPPING_IGNORE
            else:
                if mapping["type"] == "new_field":
                    mapping["key"] = ContactField.make_key(fdata["name"])
                    mapping["name"] = fdata["name"]
                    mapping["value_type"] = fdata["value_type"]
            obj.mappings[i]["mapping"] = mapping
        if form.cleaned_data.get("add_to_group"):
            group_mode = form.cleaned_data["group_mode"]
            if group_mode == form.GROUP_MODE_NEW:
                obj.group_name = form.cleaned_data["new_group_name"]
                obj.group = None
            elif group_mode == form.GROUP_MODE_EXISTING:
                obj.group = form.cleaned_data["existing_group"]
        # stamp the confirmer user
        confirmer = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        if not confirmer:
            internal_email = getattr(settings, "INTERNAL_USER_EMAIL", "")
            if internal_email:
                try:
                    confirmer = User.objects.get(email=internal_email)
                except User.DoesNotExist:
                    confirmer = None
        if not confirmer:
            confirmer = getattr(contact_import.org, "modified_by", None) or getattr(
                contact_import.org, "created_by", None
            )

        obj.modified_by = confirmer
        obj.save()
        # Trigger the import task (asynchronous)
        obj.start_async()
        return Response({"success": True, "import_id": obj.id}, status=200)


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

        # Take only contacts with messages in the period, then paginate
        contacts_with_msgs_qs = (
            ContactsWithMessagesService.get_contacts_with_messages(org, start_dt, end_dt)
            .filter(
                msgs__created_on__gte=start_dt,
                msgs__created_on__lte=end_dt,
                msgs__direction=Msg.DIRECTION_IN,
            )
            .distinct()
            .order_by("created_on", "id")
        )
        paginator = ContactsWithMessagesCursorPagination()
        page = paginator.paginate_queryset(contacts_with_msgs_qs, request, view=self)
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


# Service to extract example values for import preview
class ContactImportPreviewService:
    @staticmethod
    def extract_examples(file, filename: str, mappings: list) -> list:
        try:
            file_type = Path(filename).suffix[1:].lower()
        except Exception:
            file_type = "csv"

        stream = decode_stream(file) if file_type == "csv" else file
        data = pyexcel.iget_array(file_stream=stream, file_type=file_type)

        # skip headers
        try:
            next(data)
        except StopIteration:
            file.seek(0)
            return [None] * len(mappings)

        examples = [None] * len(mappings)
        for raw_row in data:
            row = ContactImport._parse_row(raw_row, len(mappings))
            for i, value in enumerate(row):
                if examples[i] is None and value and value != ContactImport.EXPLICIT_CLEAR:
                    examples[i] = value
            if all(v is not None for v in examples):
                break

        file.seek(0)
        return examples


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
