from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.files.uploadedfile import UploadedFile
from temba.contacts.models import ContactImport

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import exceptions as django_exceptions

from temba.api.v2.internals.contacts.serializers import (
    InternalContactFieldsValuesSerializer,
    InternalContactSerializer,
)
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.serializers import ContactFieldReadSerializer, ContactFieldWriteSerializer
from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import Contact, ContactField, ContactURN
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
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

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
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    def post(self, request, *args, **kwargs):
        project_uuid = request.data.get("project")
        file = request.FILES.get("file")
        if not project_uuid or not file:
            return Response({"error": "Project and file are required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError):
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            mappings, num_records = ContactImport.try_to_parse(org, file.file, file.name)
        except Exception as e:
            return Response({"error": f"File parsing failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        contact_import = ContactImport.objects.create(
            org=org,
            file=file,
            original_filename=file.name,
            mappings=mappings,
            num_records=num_records,
            status=ContactImport.STATUS_PENDING,
            created_by=request.user,
            modified_by=request.user,
        )
        return Response({
            "import_id": contact_import.id,
            "num_records": num_records,
            "errors": [],
        }, status=status.HTTP_200_OK)

class ContactsImportConfirmView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    def post(self, request, *args, **kwargs):
        import_id = request.data.get("import_id")
        if not import_id:
            return Response({"error": "import_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            contact_import = ContactImport.objects.get(id=import_id)
        except ContactImport.DoesNotExist:
            return Response({"error": "Import not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            contact_import.start()
        except Exception as e:
            return Response({"error": f"Import processing failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"success": True, "import_id": import_id}, status=status.HTTP_200_OK)
