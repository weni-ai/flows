import re
import secrets

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from temba.contacts.models import Contact, ContactAnchor, ContactIdentityEvent, ContactURN
from temba.msgs.models import Protocol

CONFIRMATION_TTL = 600
AI_INACTIVITY_KEY = "ai_inactivity_hours"
HUMAN_INACTIVITY_KEY = "human_inactivity_hours"
AI_INACTIVITY_DEFAULT = 1
HUMAN_INACTIVITY_DEFAULT = 96

ANCHOR_TYPES = {
    ContactAnchor.ANCHOR_COMMERCE_USER_ID,
    ContactAnchor.ANCHOR_VERIFIED_EMAIL,
    ContactAnchor.ANCHOR_TAX_DOCUMENT,
}


class IdentityResult:
    def __init__(self, *, code=None, status=200, **payload):
        self.code = code
        self.status = status
        self.payload = payload

    @property
    def ok(self):
        return self.code is None


def normalize_anchor(anchor_type, value):
    if anchor_type not in ANCHOR_TYPES:
        raise ValueError("validation")
    if value is None or str(value).strip() == "":
        raise ValueError("validation")
    value = str(value).strip()
    if anchor_type == ContactAnchor.ANCHOR_VERIFIED_EMAIL:
        return value.lower()
    if anchor_type == ContactAnchor.ANCHOR_TAX_DOCUMENT:
        return re.sub(r"[^0-9A-Za-z]", "", value).upper()
    return value


def issue_confirmation_code(org, urn):
    code = f"{secrets.randbelow(1000000):06d}"
    cache.set(_code_key(org.id, urn.id), code, CONFIRMATION_TTL)
    return code


def attach(org, *, urn_id, anchor_type, value, verified, actor):
    try:
        value = normalize_anchor(anchor_type, value)
    except ValueError:
        return IdentityResult(code="validation", status=400, error="validation")

    try:
        with transaction.atomic():
            return _attach_locked(org, urn_id, anchor_type, value, bool(verified), actor or "api")
    except IntegrityError:
        with transaction.atomic():
            urn = _lookup_urn(org, urn_id, lock=False)
            _event(
                org,
                actor=actor or "api",
                anchor_type=anchor_type,
                urn=urn,
                protocol_ids=_protocol_ids(urn) if urn else [],
                consumer=urn.contact if urn else None,
                attachment_status=urn.attachment_status if urn else None,
                outcome=ContactIdentityEvent.OUTCOME_CONFLICT,
            )
        return IdentityResult(code="conflicting_consumer", status=409, error="conflicting_consumer")


def detach(org, *, urn_id, target_consumer_id, confirmation_code, actor, privileged):
    with transaction.atomic():
        urn = _lookup_urn(org, urn_id, lock=True)
        if urn is None:
            return IdentityResult(code="validation", status=400, error="validation")
        if not privileged and not _confirmation_matches(org, urn, confirmation_code):
            return IdentityResult(code="confirmation_required", status=409, error="confirmation_required")
        result = _detach_locked(org, urn, target_consumer_id, actor or "api")
    if result.ok:
        cache.delete(_code_key(org.id, urn.id))
    return result


def read_graph(org, *, urn_id=None, consumer_id=None):
    if not urn_id and not consumer_id:
        return IdentityResult(code="validation", status=400, error="validation")
    contact = None
    urn = None
    if urn_id:
        urn = _lookup_urn(org, urn_id, lock=False)
        if urn is None:
            return IdentityResult(code="validation", status=400, error="validation")
        contact = urn.contact
    else:
        contact = Contact.objects.filter(org=org, uuid=str(consumer_id)).first()
        if contact is None:
            return IdentityResult(code="validation", status=400, error="validation")
    anchors = [
        {"type": anchor.anchor_type, "value": anchor.value, "verified": anchor.verified}
        for anchor in contact.anchors.all()
    ]
    urns = [
        {"urn_id": item.id, "identity": item.identity, "attachment_status": item.attachment_status}
        for item in contact.urns.all()
    ]
    protocols = [
        {"id": protocol.id, "uuid": str(protocol.uuid), "state": protocol.state, "urn_id": protocol.urn_id}
        for protocol in Protocol.objects.filter(org=org, contact=contact)
    ]
    return IdentityResult(
        consumer_id=str(contact.uuid),
        attachment_status=urn.attachment_status if urn else None,
        urns=urns,
        anchors=anchors,
        protocols=protocols,
    )


def set_inactivity(org, *, ai_inactivity_hours=None, human_inactivity_hours=None):
    config = dict(org.config or {})
    if ai_inactivity_hours is not None:
        try:
            ai_inactivity_hours = int(ai_inactivity_hours)
        except (TypeError, ValueError):
            return IdentityResult(code="validation", status=400, error="validation")
        if ai_inactivity_hours < 1 or ai_inactivity_hours > 24:
            return IdentityResult(code="validation", status=400, error="validation")
        config[AI_INACTIVITY_KEY] = ai_inactivity_hours
    if human_inactivity_hours is not None:
        try:
            human_inactivity_hours = int(human_inactivity_hours)
        except (TypeError, ValueError):
            return IdentityResult(code="validation", status=400, error="validation")
        if human_inactivity_hours < 1 or human_inactivity_hours > 672:
            return IdentityResult(code="validation", status=400, error="validation")
        config[HUMAN_INACTIVITY_KEY] = human_inactivity_hours
    org.config = config
    org.save(update_fields=["config"])
    return IdentityResult(
        ai_inactivity_hours=config.get(AI_INACTIVITY_KEY, AI_INACTIVITY_DEFAULT),
        human_inactivity_hours=config.get(HUMAN_INACTIVITY_KEY, HUMAN_INACTIVITY_DEFAULT),
    )


def forget_consumer(org, *, consumer_id, actor):
    contact = Contact.objects.filter(org=org, uuid=str(consumer_id)).first()
    if contact is None:
        return IdentityResult(code="validation", status=400, error="validation")
    contact.fields = {}
    contact.save(update_fields=["fields"])
    _event(
        org,
        actor=actor or "api",
        anchor_type=None,
        urn=None,
        protocol_ids=list(Protocol.objects.filter(contact=contact).values_list("id", flat=True)),
        consumer=contact,
        attachment_status=None,
        outcome=ContactIdentityEvent.OUTCOME_DELETED,
    )
    return IdentityResult(consumer_id=str(contact.uuid), outcome=ContactIdentityEvent.OUTCOME_DELETED)


def _attach_locked(org, urn_id, anchor_type, value, verified, actor):
    urn = _lookup_urn(org, urn_id, lock=True)
    if urn is None or urn.contact_id is None:
        return IdentityResult(code="validation", status=400, error="validation")

    source = Contact.objects.select_for_update().get(id=urn.contact_id)
    existing = ContactAnchor.objects.select_for_update().filter(org=org, anchor_type=anchor_type, value=value).first()
    protocol_ids = _protocol_ids(urn)

    if not verified:
        return _claim(org, urn, source, existing, anchor_type, value, actor, protocol_ids)

    if existing and existing.contact_id != source.id:
        if _verified_anchor_conflict(source, existing.contact):
            _event(
                org,
                actor=actor,
                anchor_type=anchor_type,
                urn=urn,
                protocol_ids=protocol_ids,
                consumer=source,
                attachment_status=urn.attachment_status,
                outcome=ContactIdentityEvent.OUTCOME_CONFLICT,
            )
            return IdentityResult(code="conflicting_consumer", status=409, error="conflicting_consumer")
        if not existing.verified:
            existing.verified = True
            existing.save(update_fields=["verified"])
        moved = _move_urn(urn, existing.contact, ContactURN.ATTACHMENT_CONFIRMED)
        _event(
            org,
            actor=actor,
            anchor_type=anchor_type,
            urn=urn,
            protocol_ids=moved,
            consumer=existing.contact,
            attachment_status=ContactURN.ATTACHMENT_CONFIRMED,
            outcome=ContactIdentityEvent.OUTCOME_ATTACHED,
        )
        return _attached(existing.contact, moved)

    if existing and existing.contact_id == source.id:
        if urn.attachment_status == ContactURN.ATTACHMENT_CONFIRMED and existing.verified:
            _event(
                org,
                actor=actor,
                anchor_type=anchor_type,
                urn=urn,
                protocol_ids=protocol_ids,
                consumer=source,
                attachment_status=ContactURN.ATTACHMENT_CONFIRMED,
                outcome=ContactIdentityEvent.OUTCOME_NOOP,
            )
            return _attached(source, protocol_ids, outcome=ContactIdentityEvent.OUTCOME_NOOP)
        existing.verified = True
        existing.save(update_fields=["verified"])
        urn.attachment_status = ContactURN.ATTACHMENT_CONFIRMED
        urn.save(update_fields=["attachment_status"])
        _event(
            org,
            actor=actor,
            anchor_type=anchor_type,
            urn=urn,
            protocol_ids=protocol_ids,
            consumer=source,
            attachment_status=ContactURN.ATTACHMENT_CONFIRMED,
            outcome=ContactIdentityEvent.OUTCOME_ATTACHED,
        )
        return _attached(source, protocol_ids)

    ContactAnchor.objects.create(org=org, contact=source, anchor_type=anchor_type, value=value, verified=True)
    urn.attachment_status = ContactURN.ATTACHMENT_CONFIRMED
    urn.save(update_fields=["attachment_status"])
    _event(
        org,
        actor=actor,
        anchor_type=anchor_type,
        urn=urn,
        protocol_ids=protocol_ids,
        consumer=source,
        attachment_status=ContactURN.ATTACHMENT_CONFIRMED,
        outcome=ContactIdentityEvent.OUTCOME_ATTACHED,
    )
    return _attached(source, protocol_ids)


def _claim(org, urn, source, existing, anchor_type, value, actor, protocol_ids):
    if existing is None:
        ContactAnchor.objects.create(org=org, contact=source, anchor_type=anchor_type, value=value, verified=False)
    elif existing.contact_id != source.id:
        # A verified anchor already belongs to someone else. A claim does not merge.
        pass
    urn.attachment_status = ContactURN.ATTACHMENT_CLAIMED
    urn.save(update_fields=["attachment_status"])
    _event(
        org,
        actor=actor,
        anchor_type=anchor_type,
        urn=urn,
        protocol_ids=protocol_ids,
        consumer=source,
        attachment_status=ContactURN.ATTACHMENT_CLAIMED,
        outcome=ContactIdentityEvent.OUTCOME_CLAIMED,
    )
    return IdentityResult(
        consumer_id=str(source.uuid),
        attachment_status=ContactURN.ATTACHMENT_CLAIMED,
        affected_protocol_ids=protocol_ids,
        outcome=ContactIdentityEvent.OUTCOME_CLAIMED,
    )


def _detach_locked(org, urn, target_consumer_id, actor):
    source = urn.contact
    protocol_ids = _protocol_ids(urn)
    if target_consumer_id in (None, ""):
        if urn.attachment_status == ContactURN.ATTACHMENT_NOT_ATTACHED and not source.anchors.exists():
            _event(
                org,
                actor=actor,
                anchor_type=None,
                urn=urn,
                protocol_ids=protocol_ids,
                consumer=source,
                attachment_status=ContactURN.ATTACHMENT_NOT_ATTACHED,
                outcome=ContactIdentityEvent.OUTCOME_NOOP,
            )
            return IdentityResult(
                consumer_id=str(source.uuid),
                attachment_status=ContactURN.ATTACHMENT_NOT_ATTACHED,
                affected_protocol_ids=protocol_ids,
                outcome=ContactIdentityEvent.OUTCOME_NOOP,
            )
        provisional = Contact.objects.create(
            org=org,
            name="",
            created_by=source.created_by,
            modified_by=source.modified_by,
            created_on=timezone.now(),
        )
        moved = _move_urn(urn, provisional, ContactURN.ATTACHMENT_NOT_ATTACHED)
        _event(
            org,
            actor=actor,
            anchor_type=None,
            urn=urn,
            protocol_ids=moved,
            consumer=provisional,
            attachment_status=ContactURN.ATTACHMENT_NOT_ATTACHED,
            outcome=ContactIdentityEvent.OUTCOME_DETACHED,
        )
        return IdentityResult(
            consumer_id=str(provisional.uuid),
            attachment_status=ContactURN.ATTACHMENT_NOT_ATTACHED,
            affected_protocol_ids=moved,
            outcome=ContactIdentityEvent.OUTCOME_DETACHED,
        )

    target = Contact.objects.select_for_update().filter(org=org, uuid=str(target_consumer_id)).first()
    if target is None:
        return IdentityResult(code="validation", status=400, error="validation")
    if _verified_anchor_conflict(source, target):
        _event(
            org,
            actor=actor,
            anchor_type=None,
            urn=urn,
            protocol_ids=protocol_ids,
            consumer=source,
            attachment_status=urn.attachment_status,
            outcome=ContactIdentityEvent.OUTCOME_CONFLICT,
        )
        return IdentityResult(code="conflicting_consumer", status=409, error="conflicting_consumer")
    status = (
        ContactURN.ATTACHMENT_CONFIRMED
        if target.anchors.filter(verified=True).exists()
        else ContactURN.ATTACHMENT_NOT_ATTACHED
    )
    moved = _move_urn(urn, target, status)
    _event(
        org,
        actor=actor,
        anchor_type=None,
        urn=urn,
        protocol_ids=moved,
        consumer=target,
        attachment_status=status,
        outcome=ContactIdentityEvent.OUTCOME_DETACHED,
    )
    return IdentityResult(
        consumer_id=str(target.uuid),
        attachment_status=status,
        affected_protocol_ids=moved,
        outcome=ContactIdentityEvent.OUTCOME_DETACHED,
    )


def _move_urn(urn, target, status):
    old = urn.contact
    protocol_ids = _protocol_ids(urn)
    if protocol_ids:
        Protocol.objects.filter(id__in=protocol_ids).update(contact=target)
    urn.contact = target
    urn.attachment_status = status
    urn.save(update_fields=["contact", "attachment_status"])
    if old and old.id != target.id:
        _archive_empty_provisional(old)
    return protocol_ids


def _archive_empty_provisional(contact):
    if contact.urns.exists() or contact.anchors.exists():
        return
    contact.status = Contact.STATUS_ARCHIVED
    contact.save(update_fields=["status"])


def _verified_anchor_conflict(source, target):
    if source is None or target is None or source.id == target.id:
        return False
    source_values = {anchor.anchor_type: anchor.value for anchor in source.anchors.filter(verified=True)}
    if not source_values:
        return False
    for anchor in target.anchors.filter(verified=True):
        current = source_values.get(anchor.anchor_type)
        if current is not None and current != anchor.value:
            return True
    return False


def _protocol_ids(urn):
    if urn is None:
        return []
    return list(Protocol.objects.filter(urn=urn).values_list("id", flat=True))


def _lookup_urn(org, urn_id, *, lock):
    queryset = ContactURN.objects.filter(org=org)
    if lock:
        queryset = queryset.select_for_update()
    text = str(urn_id)
    if text.isdigit():
        found = queryset.filter(id=int(text)).first()
        if found:
            return found
    return queryset.filter(identity=text).first()


def _event(org, *, actor, anchor_type, urn, protocol_ids, consumer, attachment_status, outcome):
    ContactIdentityEvent.objects.create(
        org=org,
        actor=actor or "api",
        anchor_type=anchor_type or "",
        urn=urn,
        affected_protocol_ids=list(protocol_ids or []),
        consumer=consumer,
        attachment_status=attachment_status or "",
        outcome=outcome,
    )


def _attached(contact, protocol_ids, outcome=ContactIdentityEvent.OUTCOME_ATTACHED):
    return IdentityResult(
        consumer_id=str(contact.uuid),
        attachment_status=ContactURN.ATTACHMENT_CONFIRMED,
        affected_protocol_ids=protocol_ids,
        outcome=outcome,
    )


def _confirmation_matches(org, urn, confirmation_code):
    if not confirmation_code:
        return False
    return cache.get(_code_key(org.id, urn.id)) == str(confirmation_code)


def _code_key(org_id, urn_id):
    return f"identity-detach:{org_id}:{urn_id}"
