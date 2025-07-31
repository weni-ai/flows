from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
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

from temba.api.v2.internals.contacts.serializers import (
    InternalContactFieldsValuesSerializer,
    InternalContactSerializer,
)
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.serializers import ContactFieldReadSerializer, ContactFieldWriteSerializer
from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import Contact, ContactField, ContactURN
from temba.tickets.models import Ticket
from temba.orgs.models import Org

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
