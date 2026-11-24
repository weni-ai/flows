"""Request logging and Sentry scrubbing for the internal stream endpoint."""

import logging

import sentry_sdk

logger = logging.getLogger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"
MAX_CORRELATION_ID_LENGTH = 128

OUTCOME_CREATED = "created"
OUTCOME_REPLAYED = "replayed"
OUTCOME_CONFLICT = "conflict"
OUTCOME_REJECTED_VALIDATION = "rejected_validation"
OUTCOME_REJECTED_AUTH = "rejected_auth"
OUTCOME_REJECTED_TENANT = "rejected_tenant"
OUTCOME_PROJECT_NOT_FOUND = "project_not_found"
OUTCOME_ERROR = "error"

REASON_DEDUPE_UNAVAILABLE = "dedupe_unavailable"
REASON_UNEXPECTED = "unexpected"

QUERY_BREADCRUMB_CATEGORY = "query"


def extract_correlation_id(request):
    """Opaque turn id. Used as sent when it is 1..128 characters; ignored otherwise."""
    raw = request.headers.get(CORRELATION_ID_HEADER)
    if not isinstance(raw, str):
        return None
    if not raw or len(raw) > MAX_CORRELATION_ID_LENGTH:
        return None
    return raw


def _strip_frame_vars(container):
    for value in (container or {}).get("values") or []:
        frames = (value.get("stacktrace") or {}).get("frames") or []
        for frame in frames:
            frame.pop("vars", None)


def scrub_stream_event(event, hint):
    """Drop message content that the Django Sentry integration attaches by default.

    The request body, local variables and SQL parameters carry text, button
    labels, list items and CTA URLs. This processor runs only on the scope of
    this endpoint.
    """
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)

    _strip_frame_vars(event.get("exception"))
    _strip_frame_vars(event.get("threads"))

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        crumbs = breadcrumbs.get("values") or []
    elif isinstance(breadcrumbs, list):
        crumbs = breadcrumbs
    else:
        crumbs = []
    for crumb in crumbs:
        if crumb.get("category") == QUERY_BREADCRUMB_CATEGORY:
            crumb.pop("data", None)

    for span in event.get("spans") or []:
        data = span.get("data")
        if isinstance(data, dict):
            data.pop("db.params", None)

    return event


def bind_request_scope(*, project_uuid, channel_uuid, correlation_id):
    with sentry_sdk.configure_scope() as scope:
        # The module JWT carries neither an account nor a user (Principle XIII).
        scope.set_tag("caller", "module_jwt")
        scope.set_tag("account_id", "none")
        scope.set_tag("user_id", "none")
        if project_uuid:
            scope.set_tag("project_uuid", project_uuid)
        if channel_uuid:
            scope.set_tag("channel_uuid", channel_uuid)
        if correlation_id:
            scope.set_tag("correlation_id", correlation_id)
        scope.add_event_processor(scrub_stream_event)


def log_outcome(
    outcome,
    *,
    status,
    project_uuid=None,
    channel_uuid=None,
    correlation_id=None,
    idempotency_key_present=False,
    reason=None,
):
    logger.info(
        "messages_stream outcome",
        extra={
            "outcome": outcome,
            "status": status,
            "project_uuid": project_uuid,
            "channel_uuid": channel_uuid,
            "correlation_id": correlation_id,
            "idempotency_key_present": idempotency_key_present,
            "reason": reason,
        },
    )
