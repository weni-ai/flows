from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from smartmin.views import SmartReadView, SmartUpdateView

from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from temba.channels.models import Channel
from temba.orgs.views import OrgPermsMixin
from temba.request_logs.models import HTTPLog
from temba.templates.models import TemplateTranslation
from temba.utils.views import PostOnlyMixin
from temba.wpp_products.models import Catalog

from .tasks import refresh_whatsapp_contacts, update_local_catalogs, update_local_products


class RefreshView(PostOnlyMixin, OrgPermsMixin, SmartUpdateView):
    """
    Responsible for firing off our contact refresh task
    """

    model = Channel
    fields = ()
    success_message = _("Contacts refresh begun, it may take a few minutes to complete.")
    success_url = "uuid@channels.channel_configuration"
    permission = "channels.channel_claim"
    slug_url_kwarg = "uuid"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(org=self.get_user().get_org())

    def post_save(self, obj):
        refresh_whatsapp_contacts.delay(obj.id)
        return obj


class TemplatesView(OrgPermsMixin, SmartReadView):
    """
    Displays a simple table of all the templates synced on this whatsapp channel
    """

    model = Channel
    fields = ()
    permission = "channels.channel_read"
    slug_url_kwarg = "uuid"
    template_name = "utils/whatsapp/templates.html"

    def get_gear_links(self):
        return [
            dict(
                title=_("Sync Logs"),
                href=reverse(f"channels.types.{self.object.get_type().slug}.sync_logs", args=[self.object.uuid]),
            )
        ]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(org=self.get_user().get_org())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # include all our templates as well
        context["translations"] = TemplateTranslation.objects.filter(channel=self.object).order_by("template__name")
        return context


class SyncLogsView(OrgPermsMixin, SmartReadView):
    """
    Displays a simple table of the WhatsApp Templates Synced requests for this channel
    """

    model = Channel
    fields = ()
    permission = "channels.channel_read"
    slug_url_kwarg = "uuid"
    template_name = "utils/whatsapp/sync_logs.html"

    def get_gear_links(self):
        return [
            dict(
                title=_("Message Templates"),
                href=reverse(f"channels.types.{self.object.get_type().slug}.templates", args=[self.object.uuid]),
            )
        ]

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(org=self.get_user().get_org())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # include all our http sync logs as well
        context["sync_logs"] = (
            HTTPLog.objects.filter(
                log_type__in=[
                    HTTPLog.WHATSAPP_TEMPLATES_SYNCED,
                    HTTPLog.WHATSAPP_TOKENS_SYNCED,
                    HTTPLog.WHATSAPP_CONTACTS_REFRESHED,
                    HTTPLog.WHATSAPP_CHECK_HEALTH,
                ],
                channel=self.object,
            )
            .order_by("-created_on")
            .prefetch_related("channel")
        )
        return context


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
