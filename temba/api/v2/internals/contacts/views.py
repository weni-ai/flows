import datetime as dt
import logging
from pathlib import Path

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
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from temba.api.v2.internals.contacts.serializers import (
    ContactWithMessagesListSerializer,
    InternalContactFieldsValuesSerializer,
    InternalContactSerializer,
)
from temba.api.v2.internals.contacts.services import ContactImportDeduplicationService
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.api.v2.serializers import ContactFieldReadSerializer, ContactFieldWriteSerializer
from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import Contact, ContactField, ContactImport, ContactURN
from temba.contacts.views import ContactImportCRUDL
from temba.msgs.models import Msg
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
