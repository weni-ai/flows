import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from temba.contacts.models import URN

from ...models import MERCADOLIVRE_ACTIVE_ADDRESS_CONSTRAINT, MERCADOLIVRE_CHANNEL_TYPE_CODE, ChannelType
from .usecases import ensure_mercadolivre_contact_fields

# the same limit as Channel.address
MERCADOLIVRE_ADDRESS_MAX_LENGTH = 255


class MercadoLivreType(ChannelType):
    """
    A Mercado Livre channel type. One channel is one connected seller, and its address is the seller id. It serves both
    post-sale and pre-sale, and it has no claim view until the OAuth connection feature exists.
    """

    code = MERCADOLIVRE_CHANNEL_TYPE_CODE
    category = ChannelType.Category.SOCIAL_MEDIA

    # one path for every seller, the seller is found by the channel address
    courier_url = r"^ml/receive"

    name = "Mercado Livre"
    show_config_page = False

    schemes = [URN.MERCADOLIVRE_SCHEME]
    max_length = 350
    attachment_support = True

    # the database allows only one active channel per seller id, in any organization
    unique_active_address_constraint = MERCADOLIVRE_ACTIVE_ADDRESS_CONSTRAINT

    def clean_address(self, address):
        """
        The address is the seller id: digits only, without surrounding whitespace. Only the format is checked here.
        """

        if not isinstance(address, str):
            raise ValidationError(_("The seller id is required."))

        address = address.strip()

        if not address or len(address) > MERCADOLIVRE_ADDRESS_MAX_LENGTH or not re.match(r"^[0-9]+\Z", address):
            raise ValidationError(_("The seller id must be a number."))

        return address

    def activate(self, channel):
        # the type has no external call. It only makes sure the organization has the context fields. A failure here does
        # not remove the channel, as for the other channel types, and the use case can be run again
        ensure_mercadolivre_contact_fields(channel.org, channel.created_by)
