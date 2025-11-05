from django.conf.urls import url
from django.utils.translation import ugettext_lazy as _

from ...models import TicketerType
from .views import ConfigureView, ConnectView


class FreshchatType(TicketerType):

    CONFIG_OAUTH_TOKEN = "oauth_token"
    CONFIG_FRESHCHAT_DOMAIN = "freshchat_domain"

    name = "Freshchat"
    slug = "freshchat"
    icon = "icon-freshchat"

    connect_view = ConnectView
    connect_blurb = _("%(link)s freshchat ticketer.") % {"link": '<a href="https://freshchat.com/">Freshchat</a>'}

    def is_available_to(self, user):
        return True

    def get_urls(self):
        """
        Returns all the URLs this ticketer exposes to Django, the URL should be relative.
        """
        return [
            self.get_connect_url(),
            url(r"^configure/(?P<uuid>[a-z0-9\-]+)/$", ConfigureView.as_view(), name="configure"),
        ]
