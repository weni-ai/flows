from django.conf import settings
from django.utils.translation import ugettext_lazy as _

from ...models import Channel, ChannelType
from .views import ClaimView, UpdateForm


class ExternalV2Type(ChannelType):
    """
    A external channel v2 which speaks our own API language
    """

    code = "E2"
    category = ChannelType.Category.API

    courier_url = r"^e2/(?P<uuid>[a-z0-9\-]+)/(?P<action>sent|delivered|failed|received|receive|stopped)$"

    name = "External API V2"
    icon = "icon-power-cord"

    claim_blurb = _("Use our pluggable API to connect an external service you already have.")
    claim_view = None

    update_form = None

    schemes = None  # can be any scheme