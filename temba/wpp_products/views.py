from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from django.shortcuts import get_object_or_404

from temba.channels.models import Channel
from temba.utils.whatsapp.tasks import (
    update_is_active_catalog_from_integrations,
    update_local_catalogs,
    update_local_products,
)
from temba.wpp_products.models import Catalog


class CatalogViewSet(viewsets.ViewSet):
    def create(self, request, channel_uuid, feed_id, catalog_id, *args, **kwargs):
        channel = get_object_or_404(Channel, uuid=channel_uuid)

        business_id = channel.config.get("wa_business_id")
        wa_waba_id = channel.config.get("wa_waba_id")

        if business_id is None:
            raise ValidationError("The channel does not have a business id on [config.wa_business_id]")

        if wa_waba_id is None:
            raise ValidationError("The channel does not have a wa_waba_id on [config.wa_waba_id]")

        catalog_data, valid = channel.get_type().get_api_catalogs(channel)
        if not valid:
            raise ValidationError("An error occured in update catalogs")

        # Update all the catalogs from that channel
        update_local_catalogs(channel, catalog_data)

        # Update only the products from the catalog passed in request
        catalog = Catalog.objects.get(facebook_catalog_id=catalog_id)
        update_local_catalogs(channel, catalog)

        products_data, valid = channel.get_type().get_api_products(channel, catalog)
        if not valid:
            raise ValidationError("An error occured in update products")

        update_local_products(catalog, products_data, channel)

        return Response("The flows is updated", status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"])
    def update_catalog(self, request, *args, **kwargs):
        channel = request.data.get("channel")

        if not channel:
            return Response("Channel not provided", status=status.HTTP_400_BAD_REQUEST)

        facebook_catalog_id = request.data.get("facebook_catalog_id")
        if not facebook_catalog_id:
            raise ValidationError("Facebook catalog id not provided")

        if channel and facebook_catalog_id:
            response = update_is_active_catalog_from_integrations(channel, facebook_catalog_id)
            return Response(status=status.HTTP_200_OK, data=str(response))
