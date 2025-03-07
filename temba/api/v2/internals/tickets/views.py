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

from temba import mailroom
from temba.api.v2.internals.tickets.serializers import OpenTicketSerializer, TicketAssigneeSerializer
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.validators import LambdaURLValidator
from temba.contacts.models import Contact
from temba.tickets.models import Ticket, Ticketer, Topic

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

        self.ticketer = Ticketer.objects.filter(
            config__sector_uuid=str(serializer.validated_data["sector"]),
            org_id=serializer.validated_data["org_id"],
        ).first()
        contact = Contact.objects.get(uuid=serializer.validated_data["contact"])
        topic_id = self.get_topic_id(request)
        assignee_id = self.get_assignee_id(request)
        extra = f'{{"history_after":"{serializer.validated_data["conversation_started_on"]}"}}'

        try:
            response = mailroom.get_client().ticket_open(
                self.ticketer.org.id, contact.id, self.ticketer.id, topic_id, assignee_id, extra
            )
        except Exception as e:
            return Response(str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(response, status=status.HTTP_200_OK)

    def get_assignee_id(self, request):
        assignee = request.data.get("assignee")
        if assignee:
            try:
                assignee_user = User.objects.get(email=assignee)
                return assignee_user.id
            except User.DoesNotExist:
                pass
        return 0

    def get_topic_id(self, request):
        queue = request.data.get("queue")
        if queue:
            try:
                topic = Topic.objects.get(queue_uuid=queue)
                return topic.id
            except Topic.DoesNotExist:
                pass

        return self.ticketer.org.topics.last().id
