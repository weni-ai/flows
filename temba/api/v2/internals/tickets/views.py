from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from django.contrib.auth import get_user_model
from django.core import exceptions as django_exceptions
from django.shortcuts import get_object_or_404

from temba import mailroom
from temba.api.v2.internals.tickets.serializers import (
    GetDepartmentsSerializer,
    OpenTicketSerializer,
    TicketAssigneeSerializer,
)
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.serializers import TopicReadSerializer
from temba.api.v2.validators import LambdaURLValidator
from temba.orgs.models import Org
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
        # validation_response = self.protected_resource(request)  # pragma: no cover
        # if validation_response.status_code != 200:  # pragma: no cover
        #     return validation_response

        serializer = OpenTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticketer_id = serializer.validated_data["ticketer_id"]
        contact_id = serializer.validated_data["contact_id"]
        topic_id = serializer.validated_data["topic_id"]
        assignee_id = self.get_assignee_id(request)
        extra = f'{{"history_after":"{serializer.validated_data["conversation_started_on"]}"}}'

        ticketer = Ticketer.objects.get(id=ticketer_id)

        try:
            response = mailroom.get_client().ticket_open(
                ticketer.org.id, contact_id, ticketer_id, topic_id, assignee_id, extra
            )
        except mailroom.client.MailroomException as e:
            return Response(e.response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
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


class GetDepartmentsView(APIViewMixin, APIView, LambdaURLValidator):
    renderer_classes = [JSONRenderer]

    def get(self, request, *args, **kwargs):
        validation_response = self.protected_resource(request)  # pragma: no cover

        if validation_response.status_code != 200:  # pragma: no cover
            return validation_response

        query_params = request.query_params
        project_uuid = query_params.get("project")

        org = validate_project_exists(project_uuid)

        if not org:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        queryset = Ticketer.objects.filter(org=org, is_active=True)

        # filter by uuid (optional)
        uuid = query_params.get("uuid")
        if uuid:
            queryset = queryset.filter(uuid=uuid)

        serializer = GetDepartmentsSerializer(
            queryset,
            many=True,
        )

        return Response({"results": serializer.data})


class GetQueuesView(APIViewMixin, APIView, LambdaURLValidator):
    renderer_classes = [JSONRenderer]

    def get(self, request, *args, **kwargs):
        validation_response = self.protected_resource(request)  # pragma: no cover

        if validation_response.status_code != 200:  # pragma: no cover
            return validation_response

        query_params = request.query_params
        project_uuid = query_params.get("project")

        org = validate_project_exists(project_uuid)

        if not org:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        queryset = Topic.objects.filter(org=org, is_active=True)

        serializer = TopicReadSerializer(
            queryset,
            many=True,
        )

        return Response({"results": serializer.data})


def validate_project_exists(project_uuid):
    if not project_uuid:
        return None

    try:
        return Org.objects.get(proj_uuid=project_uuid)
    except (Org.DoesNotExist, django_exceptions.ValidationError):
        return None
