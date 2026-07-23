"""
Shared validation rules for contact data.

Centralizes contact attribute validation (name, phone) so every entry point
(public API, internal API, UI form, file import) applies the same rule.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

CONTACT_NAME_MIN_LEN = 1
CONTACT_NAME_MAX_LEN = 100

# Phone digit count limits, not counting the leading "+"
CONTACT_PHONE_MIN_DIGITS = 8
CONTACT_PHONE_MAX_DIGITS = 15

_NON_DIGITS_RE = re.compile(r"[^0-9]")


def clean_contact_name(value):
    """
    Trims and validates a contact name.

    Returns the trimmed name on success, or None when the input is None.
    Raises django.core.exceptions.ValidationError otherwise.

    Rules:
        * None is allowed (anonymous contacts created by URN are still valid).
        * Empty or whitespace-only strings are not allowed.
        * Trimmed length must not exceed CONTACT_NAME_MAX_LEN.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValidationError(_("Contact name must be a string."))

    cleaned = value.strip()

    if len(cleaned) < CONTACT_NAME_MIN_LEN:
        raise ValidationError(_("Contact name cannot be empty."))

    if len(cleaned) > CONTACT_NAME_MAX_LEN:
        raise ValidationError(_("Contact name cannot exceed %(max)d characters.") % {"max": CONTACT_NAME_MAX_LEN})

    return cleaned


def validate_contact_phone(value):
    """
    Validates a phone number string. Counts only digits (the leading "+" and any
    formatting characters are ignored).

    Returns the original value on success, or None when the input is None.
    Raises django.core.exceptions.ValidationError otherwise.

    Rules:
        * None is allowed (callers may treat phone as optional).
        * Total digit count must be between CONTACT_PHONE_MIN_DIGITS and
          CONTACT_PHONE_MAX_DIGITS (inclusive).
    """
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValidationError(_("Phone number must be a string."))

    digits = _NON_DIGITS_RE.sub("", value)

    if len(digits) < CONTACT_PHONE_MIN_DIGITS:
        raise ValidationError(_("Phone number must have at least %(min)d digits.") % {"min": CONTACT_PHONE_MIN_DIGITS})

    if len(digits) > CONTACT_PHONE_MAX_DIGITS:
        raise ValidationError(_("Phone number cannot exceed %(max)d digits.") % {"max": CONTACT_PHONE_MAX_DIGITS})

    return value
