from collections import Counter

from temba.contacts.models import ContactField, ContactURN
from temba.templates.parameter_format import (
    NAMED_TEMPLATE_CHANNEL_TYPES,
    OPTIONAL_FILLER,
    is_named_format,
    is_provided_value,
)


class NamedTemplateBroadcastError(Exception):
    pass


def declared_parameter_names(template):
    translations = list(template.translations.filter(is_active=True))
    if not translations:
        return []

    names_by_translation = []
    for translation in translations:
        names = list(translation.parameter_names or [])
        names_by_translation.append((translation, tuple(names)))

    unique = {names for _, names in names_by_translation}
    if len(unique) > 1:
        disagreeing = next(
            translation for translation, names in names_by_translation if names != names_by_translation[0][1]
        )
        raise NamedTemplateBroadcastError(
            f"Named dispatch is blocked because translation {disagreeing.language} declares different parameter names"
        )

    return list(names_by_translation[0][1])


def assert_named_template_ready(template, channel=None):
    if not is_named_format(template.parameter_format):
        return

    names = declared_parameter_names(template)
    if not names:
        raise NamedTemplateBroadcastError("This template is not ready for named dispatch")

    if channel is not None and channel.channel_type not in NAMED_TEMPLATE_CHANNEL_TYPES:
        raise NamedTemplateBroadcastError(
            f"Channel {channel.uuid} does not support named parameters for template {template.uuid}"
        )

    if channel is None:
        channel_types = set(
            template.translations.filter(is_active=True).values_list("channel__channel_type", flat=True)
        )
        if channel_types and not channel_types.issubset(NAMED_TEMPLATE_CHANNEL_TYPES):
            raise NamedTemplateBroadcastError(
                f"Template {template.uuid} cannot be dispatched with named parameters on this channel"
            )

    return names


def _policy_for(template, name):
    policies = template.parameter_policies or {}
    policy = policies.get(name) or {}
    required = policy.get("required", True)
    if required is None:
        required = True
    return {
        "required": bool(required),
        "default": policy.get("default"),
        "contact_field": policy.get("contact_field"),
    }


def _contact_field_value(contact, field_key, field_cache):
    if not contact or not field_key:
        return None
    field = field_cache.get(field_key)
    if field is None:
        return None
    value = contact.get_field_display(field)
    return value if is_provided_value(value) else None


def _load_contacts_by_urn(org, urns):
    if not urns:
        return {}
    rows = ContactURN.objects.filter(org=org, identity__in=urns, contact__is_active=True).select_related("contact")
    return {row.identity: row.contact for row in rows}


def _load_field_cache(org, names, template):
    keys = set()
    for name in names:
        field_key = _policy_for(template, name).get("contact_field")
        if field_key:
            keys.add(field_key)
    if not keys:
        return {}
    fields = ContactField.user_fields.filter(org=org, key__in=keys, is_active=True)
    return {field.key: field for field in fields}


def resolve_named_recipients(org, template, recipients, batch_named_variables, extra_urns=None):
    names = declared_parameter_names(template)
    if not names:
        raise NamedTemplateBroadcastError("This template is not ready for named dispatch")

    normalized = []
    for recipient in recipients or []:
        urn = recipient.get("urn")
        variables = recipient.get("variables") or {}
        normalized.append({"urn": urn, "variables": variables})

    for urn in extra_urns or []:
        normalized.append({"urn": urn, "variables": {}})

    urns = [item["urn"] for item in normalized]
    duplicates = [urn for urn, count in Counter(urns).items() if count > 1]
    if duplicates:
        raise NamedTemplateBroadcastError(f"Recipient {duplicates[0]} is repeated")

    field_cache = _load_field_cache(org, names, template)
    contacts_by_urn = _load_contacts_by_urn(org, urns) if field_cache else {}

    accepted = []
    rejected = []
    recipient_variables = {}

    for item in normalized:
        urn = item["urn"]
        supplied = item["variables"]
        contact = contacts_by_urn.get(urn)
        resolved = {}
        missing = None

        for name in names:
            policy = _policy_for(template, name)
            value = supplied.get(name)
            if is_provided_value(value):
                resolved[name] = str(value)
                continue
            batch_value = (batch_named_variables or {}).get(name)
            if is_provided_value(batch_value):
                resolved[name] = str(batch_value)
                continue
            fallback = _contact_field_value(contact, policy.get("contact_field"), field_cache)
            if is_provided_value(fallback):
                resolved[name] = str(fallback)
                continue
            if is_provided_value(policy.get("default")):
                resolved[name] = str(policy["default"])
                continue
            if policy["required"]:
                missing = name
                break
            resolved[name] = OPTIONAL_FILLER

        if missing:
            rejected.append({"urn": urn, "parameter": missing, "reason": "required_parameter_missing"})
            continue

        accepted.append(urn)
        recipient_variables[urn] = resolved

    if normalized and not accepted:
        raise NamedTemplateBroadcastError("All recipients were held back because a required parameter is missing")

    return {
        "accepted_urns": accepted,
        "rejected": rejected,
        "recipient_variables": recipient_variables,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
    }
