from django.utils.translation import ugettext_lazy as _

from temba.contacts.models import URN

from ...models import ChannelType
from . import provisioning
from .views import ClaimView

MAX_MESSAGE_LENGTH = 4096


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
    max_length = MAX_MESSAGE_LENGTH
    attachment_support = False
    free_sending = True

    configuration_blurb = _(
        "Configure your voice gateway to send committed caller transcripts to the Courier receive URL below."
    )

    configuration_urls = (
        {
            "label": _("Inbound voice receive URL"),
            "url": "https://{{ channel.callback_domain }}{% url 'courier.tph' %}",
            "description": _("Gateway endpoint for inbound voice turns (POST JSON)."),
        },
    )

    def activate(self, channel):
        """
        Creates the SIP credential of the channel in KubeVoIP when provisioning is enabled. An error propagates so that
        ``Channel.create`` releases the channel: a TPH channel is never left half provisioned.
        """
        if not provisioning.is_enabled():
            return

        provisioning.provision_channel(channel)

    def deactivate(self, channel):
        """
        Revokes the SIP credential. It runs even when provisioning is disabled, so that turning the feature off never
        leaves a credential that cannot be revoked. Failures are reported inside and never block the release.
        """
        provisioning.deprovision_channel(channel)
