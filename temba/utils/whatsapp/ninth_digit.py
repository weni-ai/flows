import re

from django.conf import settings

# Fallback default, used only when CONTACT_SEARCH_MIN_VARIANT_LEN is not defined.
# Keeps "99676" -> "9676" working while blocking "9676" -> "676", which matched
# thousands of unrelated contacts in production benchmarks.
DEFAULT_MIN_VARIANT_LEN = 4


def _min_variant_len() -> int:
    return getattr(settings, "CONTACT_SEARCH_MIN_VARIANT_LEN", DEFAULT_MIN_VARIANT_LEN)


def get_ninth_digit_variant(number: str):
    """
    Returns the number without the Brazilian extra 9th digit, or None when it does
    not apply.

    Only the no-9 variant is generated because the trigram index already covers the
    opposite direction (typed without 9 -> contact stored with 9). The variant is
    only returned when it keeps at least CONTACT_SEARCH_MIN_VARIANT_LEN digits, to
    avoid overly broad short fragments.
    """
    digits = re.sub(r"\D", "", number)

    if digits.startswith("55") and len(digits) >= 5 and digits[4] == "9":
        stripped = digits[:4] + digits[5:]
    elif len(digits) == 11 and digits[2] == "9":
        stripped = digits[:2] + digits[3:]
    elif digits.startswith("9"):
        stripped = digits[1:]
    else:
        return None

    if len(stripped) < _min_variant_len() or stripped == digits:
        return None

    return stripped


def get_number_search_terms(number: str) -> dict:
    """
    Splits a typed number into the terms used by the contacts search query.

    - "literal": sanitized digits, searched across all URN schemes.
    - "whatsapp_variant": the number without the Brazilian extra 9th digit, searched
      only within whatsapp URNs because stripping the 9 is a WhatsApp-specific rule.
      None when it does not apply.
    """
    digits = re.sub(r"\D", "", number)
    variant = get_ninth_digit_variant(digits)

    return {"literal": digits, "whatsapp_variant": variant}
