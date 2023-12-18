from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from temba.channels.models import Channel
from temba.utils.whatsapp.tasks import update_channel_catalogs_status, update_local_catalogs, update_local_products
from temba.wpp_products.serializers import UpdateCatalogSerializer


class CatalogViewSet(viewsets.ViewSet, InternalGenericViewSet):
    def get_object(self) -> Channel:
        channel_uuid = self.request.data.get("channel")
        return get_object_or_404(Channel, uuid=channel_uuid)

    @action(detail=False, methods=["POST"], url_path="update-active-catalog")
    def update__active_catalog(self, request, *args, **kwargs):
        serializer = UpdateCatalogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        update_channel_catalogs_status(self.get_object(), validated_data.get("facebook_catalog_id"))
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"], url_path="update-catalog")
    def update_catalog(self, request, *args, **kwargs):
        update_local_catalogs(self.get_object(), request.data.get("data"))
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"], url_path="create-product")
    def create_product(self, request, *args, **kwargs):
        products = request.data.get("products")
        for product in products:
            update_local_products(product)
        return Response(status=status.HTTP_200_OK)
