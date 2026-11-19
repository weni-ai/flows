import re

from django.conf import settings

from temba.channels.models import Channel, ChannelLog
from temba.contacts.models import ContactURN
from temba.msgs.models import Msg
from temba.utils import json, redact

# Stored failed_reason codes, exposed as stable API strings. Order matches Msg.FAILED_CHOICES.
FAILED_REASON_API = {
    Msg.FAILED_SUSPENDED: "suspended",
    Msg.FAILED_LOOPING: "looping",
    Msg.FAILED_ERROR_LIMIT: "error_limit",
    Msg.FAILED_TOO_OLD: "too_old",
    Msg.FAILED_NO_DESTINATION: "no_destination",
}

# Statuses that qualify a message for log inclusion even when no log is flagged as an error.
QUALIFYING_STATUSES = (Msg.STATUS_FAILED, Msg.STATUS_ERRORED)

BREAK_ANON_PERMISSION = "contacts.contact_break_anon"

# Header name is matched case-insensitively. The whole value, including a scheme such as "Bearer", is replaced.
_AUTHORIZATION_HEADER = re.compile(r"(?im)^([ \t]*authorization[ \t]*:[ \t]*)([^\r\n]*)")
_REDACTED_HEADER_VALUE = "********"
# Shorter header values are masked on the header line only. Copying them through the body would hide ordinary words.
_MIN_SECRET_LENGTH_TO_REDACT = 8


def failed_reason_for_api(msg) -> str | None:
    """Map the message's stored failure code to the public API string."""
    if not msg.failed_reason:
        return None
    return FAILED_REASON_API.get(msg.failed_reason)


def redact_authorization_headers(value):
    """
    Replace every Authorization header value with ********.

    The same value, and a Bearer credential inside it, is also removed from the rest of the text so the
    token cannot survive in a body or URL after the header line is masked.
    """
    if not value:
        return value

    secrets = []

    def _mask(match):
        token = match.group(2).strip()
        if token and token != _REDACTED_HEADER_VALUE:
            secrets.append(token)
            parts = token.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                secrets.append(parts[1])
        return f"{match.group(1)}{_REDACTED_HEADER_VALUE}"

    redacted = _AUTHORIZATION_HEADER.sub(_mask, value)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if len(secret) >= _MIN_SECRET_LENGTH_TO_REDACT and secret != _REDACTED_HEADER_VALUE:
            redacted = redacted.replace(secret, _REDACTED_HEADER_VALUE)
    return redacted


def load_error_logs_by_message_id(messages, user, org, using: str) -> dict:
    """
    Channel logs for one Messages API page, keyed by message id.

    Messages that qualify by status are known from the page. One query then finds which of the
    remaining messages have an error log, and one query loads every log for the qualifying ids.
    Callers treat a missing id as an empty list.
    """
    messages = list(messages or [])
    if not messages:
        return {}

    status_ids = [msg.id for msg in messages if msg.status in QUALIFYING_STATUSES]
    status_id_set = set(status_ids)
    other_ids = [msg.id for msg in messages if msg.id not in status_id_set]

    qualifying_ids = list(status_ids)
    if other_ids:
        error_ids = (
            ChannelLog.objects.using(using)
            .filter(msg_id__in=other_ids, is_error=True)
            .order_by()
            .values_list("msg_id", flat=True)
            .distinct()
        )
        qualifying_ids.extend(error_ids)

    if not qualifying_ids:
        return {}

    logs = (
        ChannelLog.objects.using(using)
        .filter(msg_id__in=qualifying_ids)
        .select_related("channel", "msg", "msg__contact_urn")
        .only(
            "id",
            "created_on",
            "description",
            "is_error",
            "method",
            "url",
            "request",
            "response",
            "response_status",
            "request_time",
            "msg_id",
            "channel_id",
            "channel__channel_type",
            "msg__contact_urn",
            "msg__contact_urn__path",
        )
        .order_by("-created_on", "-id")
    )
    reveal_urns = _can_reveal_urns(user, org)

    grouped = {msg_id: [] for msg_id in qualifying_ids}
    for log in logs:
        grouped[log.msg_id].append(_serialize_log(log, reveal_urns=reveal_urns))
    return grouped


def _can_reveal_urns(user, org) -> bool:
    if not org.is_anon:
        return True
    return user.has_org_perm(org, BREAK_ANON_PERMISSION)


def _serialize_log(log, *, reveal_urns: bool) -> dict:
    channel_type = Channel.get_type_from_code(log.channel.channel_type)
    return {
        "created_on": json.encode_datetime(log.created_on, micros=True),
        "description": log.description,
        "is_error": log.is_error,
        "method": log.method,
        "url": _display_value(log, log.url, reveal_urns=reveal_urns, redact_keys=()),
        "request": _display_value(
            log, log.request, reveal_urns=reveal_urns, redact_keys=channel_type.redact_request_keys
        ),
        "response": _display_value(
            log, log.response, reveal_urns=reveal_urns, redact_keys=channel_type.redact_response_keys
        ),
        "response_status": log.response_status,
        "elapsed_ms": log.request_time if log.request_time is not None else None,
    }


def _display_value(log, original, *, reveal_urns: bool, redact_keys):
    """Same redaction as ChannelLog._get_display_value, plus Authorization header masking."""
    if original is None:
        return None

    secret = settings.WHATSAPP_ADMIN_SYSTEM_USER_TOKEN
    if secret:
        original = redact.text(original, secret, ContactURN.ANON_MASK)

    if reveal_urns:
        return redact_authorization_headers(original)

    if not log.msg_id or not log.msg or not log.msg.contact_urn_id:
        return ContactURN.ANON_MASK

    needle = log.msg.contact_urn.path
    if not needle:
        return ContactURN.ANON_MASK

    if redact_keys:
        redacted = redact.http_trace(original, needle, ContactURN.ANON_MASK, redact_keys)
    else:
        redacted = redact.text(original, needle, ContactURN.ANON_MASK)

    if original == redacted:
        return ContactURN.ANON_MASK

    return redact_authorization_headers(redacted)
