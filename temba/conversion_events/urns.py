def whatsapp_urn_variants(contact_urn: str) -> list:
    """Brazilian WhatsApp numbers are stored with or without the extra 9th
    digit depending on the source, so both spellings must be matched."""
    if not contact_urn.startswith("whatsapp:"):
        return [contact_urn]

    prefix, number = contact_urn.split(":", 1)
    if not number.startswith("55"):
        return [contact_urn]

    remaining_digits = number[4:]
    if len(remaining_digits) > 8:
        other_number = number[:4] + remaining_digits[1:]
    else:
        other_number = number[:4] + "9" + remaining_digits

    return [f"{prefix}:{num}" for num in (number, other_number)]
