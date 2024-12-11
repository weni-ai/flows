from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from temba.api.v2.internals.tickets.serializers import TicketAssigneeSerializer
from temba.tickets.models import Ticket

User = get_user_model()


class TicketAssigneeView(APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = []

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
