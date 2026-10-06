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
    CreateTicketerSerializer,
    GetDepartmentsSerializer,
    OpenTicketSerializer,
    TicketAssigneeSerializer,
    TicketerDetailSerializer,
    TicketerListSerializer,
    UpdateTicketerSerializer,
)
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.serializers import TopicReadSerializer
from temba.api.v2.validators import LambdaURLValidator
from temba.orgs.models import Org
from temba.tickets.models import Ticket, Ticketer, Topic
from temba.tickets.types.internal.type import InternalType

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


def resolve_org_and_user(request, org_value, user_email):
    """
    Resolves the org and acting user and checks the caller may manage ticketers on that org.
    Returns (org, acting_user, None) on success or (None, None, Response) on failure.
    """
    if not org_value:
        return None, None, Response({"org": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

    try:
        org = Org.objects.get(proj_uuid=org_value)
    except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
        return None, None, Response({"org": ["Project not found"]}, status=status.HTTP_400_BAD_REQUEST)

    try:
        acting_user = User.objects.get(email=user_email)
    except User.DoesNotExist:
        return None, None, Response({"user": ["User not found"]}, status=status.HTTP_400_BAD_REQUEST)

    is_internal = request.user.user_permissions.filter(codename="can_communicate_internally").exists()
    if not is_internal:
        if request.user.email != acting_user.email:
            return (
                None,
                None,
                Response(
                    {"permission": ["Authenticated user must match payload user"]},
                    status=status.HTTP_403_FORBIDDEN,
                ),
            )

        if not request.user.has_org_perm(org, "tickets.ticketer_connect"):
            return (
                None,
                None,
                Response(
                    {"permission": ["User lacks tickets.ticketer_connect on this org"]},
                    status=status.HTTP_403_FORBIDDEN,
                ),
            )

    return org, acting_user, None


def get_active_ticketer(org, ticketer_uuid):
    try:
        return Ticketer.objects.get(uuid=ticketer_uuid, org=org, is_active=True)
    except (Ticketer.DoesNotExist, django_exceptions.ValidationError, ValueError):
        return None


class CreateTicketerView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request: Request):
        org, _, error = resolve_org_and_user(
            request, request.query_params.get("org"), request.query_params.get("user")
        )
        if error:
            return error

        queryset = Ticketer.objects.filter(org=org, is_active=True).order_by("-created_on")
        serializer = TicketerListSerializer(queryset, many=True)
        return Response({"results": serializer.data}, status=status.HTTP_200_OK)

    def post(self, request: Request):
        org, acting_user, error = resolve_org_and_user(request, request.data.get("org"), request.data.get("user"))
        if error:
            return error

        serializer = CreateTicketerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticketer = serializer.save()

        response = {
            "uuid": str(ticketer.uuid),
            "name": ticketer.name,
            "ticketer_type": ticketer.ticketer_type,
            "config": ticketer.config,
        }

        return Response(response, status=status.HTTP_201_CREATED)


class TicketerItemView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated]

    def _load(self, request, ticketer_uuid):
        org, acting_user, error = resolve_org_and_user(
            request,
            request.query_params.get("org") or request.data.get("org"),
            request.query_params.get("user") or request.data.get("user"),
        )
        if error:
            return None, None, error

        ticketer = get_active_ticketer(org, ticketer_uuid)
        if not ticketer:
            return None, None, Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        return ticketer, acting_user, None

    def get(self, request: Request, ticketer_uuid):
        ticketer, _, error = self._load(request, ticketer_uuid)
        if error:
            return error

        return Response(TicketerDetailSerializer(ticketer).data, status=status.HTTP_200_OK)

    def put(self, request: Request, ticketer_uuid):
        ticketer, _, error = self._load(request, ticketer_uuid)
        if error:
            return error

        serializer = UpdateTicketerSerializer(instance=ticketer, data=request.data)
        serializer.is_valid(raise_exception=True)
        ticketer = serializer.save()

        response = {
            "uuid": str(ticketer.uuid),
            "name": ticketer.name,
            "ticketer_type": ticketer.ticketer_type,
            "config": ticketer.config,
        }
        return Response(response, status=status.HTTP_200_OK)

    def delete(self, request: Request, ticketer_uuid):
        ticketer, acting_user, error = self._load(request, ticketer_uuid)
        if error:
            return error

        # Ticketer.is_internal compares a type instance to the class and is always False, so compare slugs
        if ticketer.ticketer_type == InternalType.slug:
            return Response(
                {"ticketer": ["Internal ticketers cannot be deleted"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ticketer.release(acting_user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OpenTicketView(APIViewMixin, APIView, LambdaURLValidator):
    renderer_classes = [JSONRenderer]

    def post(self, request, *args, **kwargs):
        validation_response = self.protected_resource(request)  # pragma: no cover
        if validation_response.status_code != 200:  # pragma: no cover
            return validation_response

        serializer = OpenTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticketer_id = serializer.validated_data["ticketer_id"]
        contact_id = serializer.validated_data["contact_id"]
        topic_id = serializer.validated_data["topic_id"]
        protocol = serializer.validated_data.get("protocol")
        assignee_id = self.get_assignee_id(request)

        extra_data = {}
        conversation_started_on = serializer.validated_data.get("conversation_started_on")
        if conversation_started_on:
            extra_data["history_after"] = str(conversation_started_on)
        if protocol:
            extra_data["protocol"] = protocol
        extra = str(extra_data).replace("'", '"')

        ticketer = Ticketer.objects.get(id=ticketer_id)

        try:
            response = mailroom.get_client().ticket_open(
                ticketer.org.id, contact_id, ticketer_id, topic_id, assignee_id, extra
            )
        except mailroom.MailroomException as e:
            return Response(str(e.response), status=status.HTTP_400_BAD_REQUEST)
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
