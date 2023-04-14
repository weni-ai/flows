from django.utils.translation import ugettext_lazy as _

from temba.externals.models import ExternalServiceType
from .views import ConnectView
from .serializers import OmieSerializer


class OmieType(ExternalServiceType):
    """
    Type for using omie as a external service
    """

    CONFIG_APP_KEY = "app_key"
    CONFIG_APP_SECRET = "app_secret"

    serializer_class = OmieSerializer

    name = "Omie"
    slug = "omie"
    icon = "icon-power-cord"

    connect_view = ConnectView
    connect_blurb = _("omie external service")

    def is_available_to(self, user):
        return True
