from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from temba.channels.models import Channel
from temba.utils.whatsapp.tasks import (
    update_channel_catalogs_status,
    update_local_catalogs,
    update_local_products_vtex_task,
)
from temba.wpp_products.models import Catalog
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


class ProductViewSet(viewsets.ViewSet, InternalGenericViewSet):
    def get_object(self) -> Channel:
        channel_uuid = self.request.data.get("channel_uuid")
        return get_object_or_404(Channel, uuid=channel_uuid)

    @action(detail=False, methods=["POST"], url_path="update-products")
    def update_products(self, request, *args, **kwargs):
        catalog = request.data.get("catalog")
        products = request.data.get("products")

        catalog_object = Catalog.objects.filter(facebook_catalog_id=catalog.get("facebook_catalog_id")).first()
        if not catalog_object:
            catalog_object = Catalog.get_or_create(
                catalog.get("name"), self.get_object(), False, catalog.get("facebook_catalog_id")
            )

        update_local_products_vtex_task.delay(catalog_object.pk, products, self.get_object().pk)

        return Response(status=status.HTTP_200_OK)
