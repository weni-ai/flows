from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.renderers import JSONRenderer
from rest_framework.viewsets import GenericViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally
from weni.internal.views import InternalGenericViewSet

from temba.api.v2.internals.tickets.serializers import TicketAssigneeSerializer
from temba.tickets.models import Ticket, Ticketer
from django.shortcuts import get_object_or_404

class TicketAssigneeView(APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]


    def post(self, request: Request):
        serializer = TicketAssigneeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket = get_object_or_404(Ticket, uuid=serializer.validated_data["uuid"])

        ticket.assignee = serializer.validated_data["email"]
        ticket.save()

        response = {"results": {"ticketer": ticket.uuid, "assignee": ticket.assignee}}

        return Response(response, status=status.HTTP_200_OK)
