from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.mixins import CreateModelMixin
from weni.internal.views import InternalGenericViewSet

from django.conf import settings
from django.contrib.auth import get_user_model

from .serializers import FlowStartSerializer, UserAndFlowSerializer

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
