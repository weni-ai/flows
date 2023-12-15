from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from temba.channels.models import Channel
from temba.utils.whatsapp.tasks import update_channel_catalogs_status, update_local_products
from temba.wpp_products.models import Catalog
from temba.wpp_products.serializers import UpdateCatalogSerializer


class CatalogViewSet(viewsets.ViewSet, InternalGenericViewSet):
    def get_object(self) -> Channel:
        channel_uuid = self.request.data.get("channel")
        return get_object_or_404(Channel, uuid=channel_uuid)

    @action(detail=False, methods=["POST"], url_path="update-catalog")
    def update_catalog(self, request, *args, **kwargs):
        serializer = UpdateCatalogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        update_channel_catalogs_status(self.get_object(), validated_data.get("facebook_catalog_id"))
        return Response(status=status.HTTP_200_OK)


class ProductViewSet(viewsets.ViewSet, InternalGenericViewSet):
    def get_object(self) -> Channel:
        channel_uuid = self.request.data.get("channel")
        return get_object_or_404(Channel, uuid=channel_uuid)

    @action(detail=False, methods=["POST"], url_path="update-products")
    def update_products(self, request, *args, **kwargs):
        list_products = request.data
        for products in list_products:
            catalog = Catalog.objects.get(facebook_catalog_id=products.get("catalog"))
            update_local_products(catalog, products, self.get_object())

        return Response(status=status.HTTP_200_OK)
