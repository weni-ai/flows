
from django.utils.translation import ugettext_lazy as _

from temba.tickets.models import TicketerType
from temba.tickets.types.wenichats.views import ConnectView

class WeniChatsType(TicketerType):
  """
  Type for using Weni Chats as a ticketer.
  """

  CONFIG_AUTH_TOKEN = "auth_token"
  CONFIG_PROJECT_FLOWS_UUID = "project_flows_uuid"
  CONFIG_SECTOR_UUID = "sector_uuid"

  name = "Weni Chats"
  slug = "wenichats"
  icon = "icon-power-cord"
  base_url = "https://chats.weni.ai/v1/external"

  connect_view = ConnectView
  # TODO: improve descriptiton
  connect_blurb = _(
    "%(link)s TODO DESCRIPTION Irure dolor amet enim laborum nisi laborum ea. Labore ullamco excepteur et esse Lorem pariatur. Lorem esse nisi commodo laboris tempor consectetur dolor amet ea nostrud ullamco velit. Aute non magna dolor id minim nostrud ex. Tempor consectetur nulla duis labore id anim sit non."
  ) % {"link": '<a href="https://chats.weni.ai/">Weni Chats</a>'}

  def is_available_to(self, user):
    return True
