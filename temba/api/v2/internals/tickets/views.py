from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from temba.api.v2.internals.tickets.serializers import TicketAssigneeSerializer, OpenTicketSerializer
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import Contact
from temba.tickets.models import Ticket, Ticketer, Topic
from temba import mailroom

User = get_user_model()


class TicketAssigneeView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    def post(self, request: Request):
        serializer = TicketAssigneeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket = get_object_or_404(Ticket, uuid=serializer.validated_data["uuid"])
        user_email = serializer.validated_data["email"]

        assignee, _ = User.objects.get_or_create(email=user_email)

        ticket.assignee = assignee
        ticket.save()

        response = {"results": {"ticketer": ticket.uuid, "assignee": ticket.assignee.email}}

        return Response(response, status=status.HTTP_200_OK)


class OpenTicketView(APIViewMixin, APIView, LambdaURLValidator):
    renderer_classes = [JSONRenderer]

    def post(self, request, *args, **kwargs):
        validation_response = self.protected_resource(request)  # pragma: no cover
        if validation_response.status_code != 200:  # pragma: no cover
            return validation_response

        serializer = OpenTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticketer = Ticketer.objects.filter(config__sector_uuid=str(serializer.validated_data["sector"])).first()
        contact = Contact.objects.get(uuid=serializer.validated_data["contact"])
        topic = Topic.objects.get(queue_uuid=serializer.validated_data["queue"])
        topic_id = topic.id if topic else ticketer.org.topics.get(is_default=True)
        try:
            assignee_user = User.objects.get(email=serializer.validated_data["assignee"])
            assignee_id = assignee_user.id
        except User.DoesNotExist:
            assignee_id = 0
        extra = f'{{"history_after":"{serializer.validated_data["conversation_started_on"]}"}}'

        return mailroom.get_client().ticket_open(
            ticketer.org.id, contact.id, ticketer.id, topic_id, assignee_id, extra
        )
