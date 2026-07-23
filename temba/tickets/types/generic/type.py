from django.utils.translation import ugettext_lazy as _

from temba.tickets.models import TicketerType
from temba.tickets.types.generic.views import ConnectView


class GenericType(TicketerType):
    """
    Generic ticketer type.
    """

    name = "Generic"
    slug = "generic"
    icon = "icon-channel-external"

    CONFIG_BASE_URL = "base_url"
    CONFIG_API_TOKEN = "api_token"
    CONFIG_WEBHOOK_SECRET = "webhook_secret"

    # Optional metadata enrichment for partner-side context
    CONFIG_PROJECT_UUID = "project_uuid"
    CONFIG_PROJECT_NAME = "project_name"

    # Optional per-endpoint route overrides. When empty, DefaultRoutes is used.
    CONFIG_ROUTE_OPEN = "route_open"
    CONFIG_ROUTE_FORWARD = "route_forward"
    CONFIG_ROUTE_CLOSE = "route_close"
    CONFIG_ROUTE_REOPEN = "route_reopen"
    CONFIG_ROUTE_HISTORY = "route_history"

    connect_view = ConnectView
    connect_blurb = _("%(link)s generic ticketer.") % {"link": '<a href="https://www.generic.com/">Generic</a>'}

    def is_available_to(self, user):
        return True
