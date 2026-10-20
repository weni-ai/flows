from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally
from weni.internal.views import InternalGenericViewSet

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg

from .serializers import FlowImportSerializer, FlowStartSerializer, UserAndFlowSerializer
from .usecases import FlowImportDTO, FlowImportUseCase

User = get_user_model()


class FlowStartViewSet(CreateModelMixin, InternalGenericViewSet):
    authentication_classes = []
    permission_classes = []
    serializer_class = FlowStartSerializer

    def get_serializer(self, *args, **kwargs):
        serializer = UserAndFlowSerializer(data=self.request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        flow = serializer.validated_data["flow"]

        context = dict(user=user, flow=flow, org=flow.org)

        return super().get_serializer(*args, **kwargs, context=context)

    def create(self, request, *args, **kwargs):
        params = request.query_params
        token = params.get("token")

        if token is None:
            raise NotAuthenticated()

        if token != settings.ROUTER_FIXED_ACCESS_TOKEN:
            raise AuthenticationFailed()

        return super().create(request, *args, **kwargs)


class FlowImportView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated & (CanCommunicateInternally | IsUserInOrg)]

    def post(self, request: Request):
        serializer = FlowImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dto = FlowImportDTO(
            project_uuid=serializer.validated_data["project_uuid"],
            user_email=request.user.email,
            definition=serializer.validated_data["definition"],
            is_mutable=serializer.validated_data.get("is_mutable", True),
        )

        usecase = FlowImportUseCase()
        results = usecase.import_flows(dto)
        return Response({"results": results}, status=status.HTTP_201_CREATED)
