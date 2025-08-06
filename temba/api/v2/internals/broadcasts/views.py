from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally
from weni.internal.views import InternalGenericViewSet

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.serializers import WhatsappBroadcastWriteSerializer
from temba.msgs.models import Broadcast, BroadcastStatistics
from temba.orgs.models import Org

from .serializers import BroadcastSerializer, BroadcastWithStatisticsSerializer, UserAndProjectSerializer

User = get_user_model()


class BroadcastsViewSet(CreateModelMixin, InternalGenericViewSet):
    authentication_classes = []
    permission_classes = []
    serializer_class = BroadcastSerializer

    def get_serializer(self, *args, **kwargs):
        serializer = UserAndProjectSerializer(data=self.request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        project = serializer.validated_data["project"]

        context = dict(org=project.org, user=user)

        return super().get_serializer(*args, **kwargs, context=context)

    def create(self, request, *args, **kwargs):
        params = request.query_params
        token = params.get("token")

        if token is None:
            raise NotAuthenticated()

        if token != settings.ROUTER_FIXED_ACCESS_TOKEN:
            raise AuthenticationFailed()

        return super().create(request, *args, **kwargs)


class InternalWhatsappBroadcastsEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    def post(self, request, *args, **kwargs):
        project_uuid = request.data.get("project")

        if not project_uuid:
            return Response({"error": "Project not provided"}, status=401)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
            user, _ = User.objects.get_or_create(email=request.user.email)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        serializer = WhatsappBroadcastWriteSerializer(
            data=request.data, context={"request": request, "org": org, "user": user}
        )

        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Success"})

        return Response(serializer.errors, status=400)


class InternalBroadcastStatisticsEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]
    serializer_class = BroadcastWithStatisticsSerializer

    def get(self, request, *args, **kwargs):
        project_uuid = request.query_params.get("project_uuid")
        if not project_uuid:
            return Response({"error": "Project UUID not provided"}, status=400)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)
        qs = Broadcast.objects.filter(org=org)
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        name = request.query_params.get("name")
        broadcast_id = request.query_params.get("id")

        if start_date:
            qs = qs.filter(created_on__gte=start_date)
        if end_date:
            qs = qs.filter(created_on__lte=end_date)
        if name:
            qs = qs.filter(name__icontains=name)
        if broadcast_id:
            qs = qs.filter(id=broadcast_id)

        qs = qs.order_by("-created_on")
        data = BroadcastWithStatisticsSerializer(qs, many=True).data
        return Response(data)


class InternalBroadcastStatisticMontlyEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    def get(self, request, *args, **kwargs):
        project_uuid = request.query_params.get("project_uuid")
        if not project_uuid:
            return Response({"error": "Project UUID not provided"}, status=400)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        last_month_data = BroadcastStatistics.last_30_days_stats(org)
        return Response(last_month_data)
