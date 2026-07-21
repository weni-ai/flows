from django.utils.translation import ugettext_lazy as _

from temba.contacts.models import URN

from ...models import ChannelType
from .views import ClaimView

CONFIG_BASE_URL = "base_url"
CONFIG_AUTH_TOKEN = "auth_token"


class TelephonyPSTNType(ChannelType):
    """
    PSTN telephony channel for voice mode (Courier type TPH).
    """

    code = "TPH"
    category = ChannelType.Category.PHONE

    courier_url = r"^tph/receive"

    name = "Telephony PSTN"
    icon = "icon-channel-twilio"
    show_config_page = False
    show_public_addresses = True

    claim_blurb = _(
        "Connect a PSTN telephone number for voice conversations with your conversational agent. "
        "The dialed number (DID) identifies the channel; contacts are keyed by phone number."
    )
    claim_view = ClaimView

    schemes = [URN.TEL_SCHEME]
    max_length = 4096
    attachment_support = False
    free_sending = True

    configuration_blurb = _(
        "Configure your voice gateway to send committed caller transcripts to the Courier receive URL below."
    )

    configuration_urls = (
        dict(
            label=_("Inbound voice receive URL"),
            url="https://{{ channel.callback_domain }}{% url 'courier.tph' %}",
            description=_("Gateway endpoint for inbound voice turns (POST JSON)."),
        ),
    )
