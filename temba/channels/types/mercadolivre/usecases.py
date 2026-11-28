import logging

from sentry_sdk import capture_message

from temba.contacts.models import ContactField
from temba.orgs.models import Org

logger = logging.getLogger(__name__)

ML_KIND_KEY = "ml_kind"
ML_BUYER_ID_KEY = "ml_buyer_id"
ML_NICKNAME_KEY = "ml_nickname"
ML_PACK_ID_KEY = "ml_pack_id"
ML_ORDER_IDS_KEY = "ml_order_ids"
ML_ITEM_ID_KEY = "ml_item_id"
ML_QUESTION_ID_KEY = "ml_question_id"

# the context of a buyer conversation, shared by post-sale (pack and order ids) and pre-sale (item and question ids).
# All of them are text, Mailroom writes the values. The keys are the contract with the other services
MERCADOLIVRE_CONTACT_FIELDS = (
    (ML_KIND_KEY, "ML Kind"),
    (ML_BUYER_ID_KEY, "ML Buyer ID"),
    (ML_NICKNAME_KEY, "ML Nickname"),
    (ML_PACK_ID_KEY, "ML Pack ID"),
    (ML_ORDER_IDS_KEY, "ML Order IDs"),
    (ML_ITEM_ID_KEY, "ML Item ID"),
    (ML_QUESTION_ID_KEY, "ML Question ID"),
)


def ensure_mercadolivre_contact_fields(org, user) -> list[ContactField]:
    """
    Creates the Mercado Livre text contact fields that the organization does not have yet, and returns the ones created.

    A field that already exists with one of the keys is used as it is: its label, type and values are not changed. It is
    safe to call this again. When the organization has no room under its field limit the missing fields are skipped, a
    warning is logged and nothing is raised, so the channel that called this stays valid.
    """

    created = []
    limit = org.get_limit(Org.LIMIT_FIELDS)

    for key, label in MERCADOLIVRE_CONTACT_FIELDS:
        if ContactField.user_fields.active_for_org(org=org).filter(key__iexact=key).exists():
            continue

        if ContactField.user_fields.count_active_for_org(org=org) >= limit:
            msg = f"Skipping creation of Mercado Livre contact fields for org {org.id}: field limit reached"
            logger.warning(msg)
            capture_message(msg, level="warning")
            break

        created.append(ContactField.get_or_create(org, user, key, label=label, value_type=ContactField.TYPE_TEXT))

    return created
