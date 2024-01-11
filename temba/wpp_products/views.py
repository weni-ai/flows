from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from temba.channels.models import Channel
from temba.utils.whatsapp.tasks import update_channel_catalogs_status, update_local_catalogs
from temba.wpp_products.serializers import UpdateCatalogSerializer


class CatalogViewSet(viewsets.ViewSet, InternalGenericViewSet):
    @action(detail=True, methods=["POST"], url_path="update-status-catalog")
    def update_status_catalog(self, request, pk, *args, **kwargs):
        serializer = UpdateCatalogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        channel = get_object_or_404(Channel, uuid=pk, is_active=True)

        update_channel_catalogs_status(
            channel, validated_data.get("facebook_catalog_id"), validated_data.get("is_active")
        )
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST"], url_path="update-catalog")
    def update_catalog(
        self,
        request,
        pk,
        *args,
        **kwargs,
    ):
        channel = get_object_or_404(Channel, uuid=pk, is_active=True)

        if request.data:
            update_local_catalogs(channel, request.data.get("data"))
        return Response(status=status.HTTP_200_OK)
