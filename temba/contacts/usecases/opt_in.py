import logging

import requests

from django.conf import settings
from django.db import IntegrityError, transaction

from temba.api.v2.internals.contacts.serializers import _resolve_contact_field_for_update
from temba.contacts.models import URN, Contact, ContactGroup, ContactURN
from temba.contacts.validators import validate_contact_phone
from temba.conversion_events.urns import whatsapp_urn_variants
from temba.mailroom.client import MailroomException
from temba.orgs.models import Org

logger = logging.getLogger(__name__)

URN_IN_USE = "URNs in use by other contacts"


class OptInUnavailable(Exception):
    """Mailroom could not complete the write. Callers retry; this is not a duplicate."""


class EnsureResult:
    def __init__(self, group=None, created=False, error=None):
        self.group = group
        self.created = created
        self.error = error


class CreateResult:
    def __init__(self, outcome, contact=None, group=None):
        self.outcome = outcome
        self.contact = contact
        self.group = group


def ensure_audience(org, user):
    """
    Create or reuse the platform Opt-in group for this org.
    """
    active = _active_audience(org)
    if active:
        return EnsureResult(group=active, created=False)

    existing = ContactGroup.user_groups.filter(org=org, name=ContactGroup.OPT_IN_GROUP_NAME, is_active=True).first()
    if existing and existing.is_dynamic:
        return EnsureResult(error="opt_in_name_taken")

    if not existing:
        limit = org.get_limit(Org.LIMIT_GROUPS)
        if ContactGroup.user_groups.filter(org=org).count() >= limit:
            return EnsureResult(error="group_limit_reached")
        existing = ContactGroup.create_static(org, user, ContactGroup.OPT_IN_GROUP_NAME)

    existing.is_opt_in = True
    try:
        with transaction.atomic():
            existing.save(update_fields=("is_opt_in",))
    except IntegrityError:
        active = _active_audience(org)
        if active:
            return EnsureResult(group=active, created=False)
        raise
    return EnsureResult(group=existing, created=True)


def _normalize_whatsapp(raw):
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    urn = URN.normalize(URN.from_whatsapp(digits))
    scheme, path, _query, _display = URN.to_parts(urn)
    if scheme != URN.WHATSAPP_SCHEME or not URN.is_phone_based_path(path) or not URN.validate(urn):
        raise ValueError("invalid whatsapp")
    validate_contact_phone(f"+{path}" if not path.startswith("+") else path)
    return urn


def _find_duplicate(org, urn):
    for variant in whatsapp_urn_variants(urn):
        existing = ContactURN.lookup(org, variant, normalize=False)
        if existing and existing.contact_id:
            return existing.contact
    return None


def _urn_in_use(exc):
    response = exc.response
    message = response.get("error") if isinstance(response, dict) else response
    return URN_IN_USE in str(message or "")


def _active_audience(org):
    return ContactGroup.user_groups.filter(org=org, is_opt_in=True).first()


def create_opt_in_contact(org, user, name, whatsapp, email=None):
    group = _active_audience(org)
    if not group:
        return CreateResult("missing")

    urn = _normalize_whatsapp(whatsapp)
    if _find_duplicate(org, urn):
        return CreateResult("duplicate", group=group)

    fields = {}
    if email:
        field = _resolve_contact_field_for_update(org, user, "email")
        if field:
            fields[field] = email
        else:
            logger.warning("Skipping opt-in email field for org %s: field limit reached", org.id)

    _DEFAULT_MAILROOM_TIMEOUT_SECONDS = 5
    timeout = getattr(settings, "OPT_IN_MAILROOM_TIMEOUT_SECONDS", _DEFAULT_MAILROOM_TIMEOUT_SECONDS)
    try:
        contact = Contact.create(org, user, name, None, [urn], fields, [group], timeout=timeout)
    except MailroomException as exc:
        if _urn_in_use(exc) and _find_duplicate(org, urn):
            return CreateResult("duplicate", group=group)
        logger.warning("Opt-in contact create failed for org %s", org.id)
        raise OptInUnavailable() from exc
    except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
        logger.warning("Opt-in contact create unavailable for org %s", org.id)
        raise OptInUnavailable() from exc

    return CreateResult("created", contact=contact, group=group)


def _is_group_member(contact, group):
    prefetched = getattr(contact, "prefetched_user_groups", None)
    if prefetched is not None:
        return group in prefetched
    return contact.user_groups.filter(id=group.id).exists()


def fill_identifier(org, user, contact, email):
    group = _active_audience(org)
    if not group or not _is_group_member(contact, group):
        return "unchanged"

    field = _resolve_contact_field_for_update(org, user, "email")
    if not field:
        logger.warning("Skipping opt-in email fill for org %s: field limit reached", org.id)
        return "unchanged"
    if contact.get_field_value(field):
        return "unchanged"

    try:
        contact.modify(user, contact.update_fields({field: email}))
    except (MailroomException, requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
        logger.warning("Opt-in identifier fill unavailable for org %s", org.id)
        raise OptInUnavailable() from exc
    return "updated"
