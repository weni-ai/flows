from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework.mixins import CreateModelMixin
from rest_framework.exceptions import NotAuthenticated, AuthenticationFailed

from weni.internal.views import InternalGenericViewSet
from .serializers import UserAndProjectSerializer, BroadcastSerializer


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
