from django.conf.urls import url

from temba.contacts.models import URN

from ...models import ChannelType
from .views import ClaimView, OutlookCallback, OutlookStart


class EmailType(ChannelType):
    """
    A generic EMAIL channel
    """

    code = "EM"
    category = ChannelType.Category.API

    courier_url = r"^em/(?P<uuid>[a-z0-9\-]+)/receive$"

    name = "Email"

    schemes = [URN.EMAIL_SCHEME]

    show_config_page = False

    claim_blurb = "Use an email API to connect."
    claim_view = ClaimView

    def get_urls(self):
        return [
            self.get_claim_url(),
            url(r"^outlook/start$", OutlookStart.as_view(channel_type=self), name="outlook_start"),
            url(r"^outlook/callback$", OutlookCallback.as_view(channel_type=self), name="outlook_callback"),
        ]

    def deactivate(self, channel):
        config = dict(channel.config or {})
        config.pop("access_token", None)
        config.pop("refresh_token", None)
        channel.config = config
