from temba.contacts.models import URN

from ...models import ChannelType


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
