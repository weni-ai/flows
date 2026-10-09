from weni.internal.models import Project

from django.contrib.auth.models import User

from temba.contacts.models import ContactField

ORIGINAL_CONTACT_URN_KEY = "original_contact_urn"
ORIGINAL_CONTACT_URN_LABEL = "Original Contact URN"
SELLER_EMAIL_KEY = "seller_email"
SELLER_EMAIL_LABEL = "Seller Email"

LIVE_DESK_COPILOT_CONTACT_FIELDS = (
    (ORIGINAL_CONTACT_URN_KEY, ORIGINAL_CONTACT_URN_LABEL),
    (SELLER_EMAIL_KEY, SELLER_EMAIL_LABEL),
)


def create_live_desk_copilot_contact_fields(project: Project, user: User) -> list[ContactField]:
    fields = []

    for key, label in LIVE_DESK_COPILOT_CONTACT_FIELDS:
        field = ContactField.get_or_create(
            project.org,
            user,
            key=key,
            label=label,
            value_type=ContactField.TYPE_TEXT,
        )
        fields.append(field)

    return fields
