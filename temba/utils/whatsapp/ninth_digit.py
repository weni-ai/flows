import re

from django.conf import settings

# Fallback defaults, used only when the matching setting is not defined.
# CONTACT_SEARCH_MIN_VARIANT_LEN keeps "99676" -> "9676" working while blocking
# "9676" -> "676", which matched thousands of unrelated contacts in production.
# CONTACT_SEARCH_MIN_TERM_LEN mirrors the trigram analyzer minimum (3 chars).
DEFAULT_MIN_VARIANT_LEN = 4
DEFAULT_MIN_TERM_LEN = 3


def _min_variant_len() -> int:
    return getattr(settings, "CONTACT_SEARCH_MIN_VARIANT_LEN", DEFAULT_MIN_VARIANT_LEN)


def _min_term_len() -> int:
    return getattr(settings, "CONTACT_SEARCH_MIN_TERM_LEN", DEFAULT_MIN_TERM_LEN)


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

    - "literal": the typed digits, searched across all URN schemes. Empty when it
      has fewer than CONTACT_SEARCH_MIN_TERM_LEN digits, since the trigram analyzer
      matches nothing below that.
    - "whatsapp_variant": the number without the Brazilian extra 9th digit, searched
      only within whatsapp URNs because stripping the 9 is a WhatsApp-specific rule.
      None when it does not apply or equals the literal.
    """
    digits = re.sub(r"\D", "", number)

    literal = digits if len(digits) >= _min_term_len() else ""

    variant = get_ninth_digit_variant(digits)
    if variant == literal:
        variant = None

    return {"literal": literal, "whatsapp_variant": variant}
