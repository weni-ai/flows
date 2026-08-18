BR_COUNTRY_CODE = "55"
BR_DDD_LENGTH = 2
BR_COUNTRY_AND_DDD_LENGTH = len(BR_COUNTRY_CODE) + BR_DDD_LENGTH
BR_SUBSCRIBER_DIGITS_WITHOUT_NINE = 8
BR_EXTRA_NINE = "9"


def whatsapp_urn_variants(contact_urn: str) -> list:
    """Brazilian WhatsApp numbers are stored with or without the extra 9th
    digit depending on the source, so both spellings must be matched."""
    if not contact_urn.startswith("whatsapp:"):
        return [contact_urn]

    prefix, number = contact_urn.split(":", 1)
    if not number.startswith(BR_COUNTRY_CODE):
        return [contact_urn]

    remaining_digits = number[BR_COUNTRY_AND_DDD_LENGTH:]
    if len(remaining_digits) > BR_SUBSCRIBER_DIGITS_WITHOUT_NINE:
        other_number = number[:BR_COUNTRY_AND_DDD_LENGTH] + remaining_digits[1:]
    else:
        other_number = number[:BR_COUNTRY_AND_DDD_LENGTH] + BR_EXTRA_NINE + remaining_digits

    return [f"{prefix}:{num}" for num in (number, other_number)]
