"""
The API side of media files sent inline with a WhatsApp broadcast (multipart/form-data): request parsing, errors and
failure reporting. What is done with the files lives in temba.msgs.usecases.broadcast_media.
"""

import logging

import sentry_sdk
from rest_framework import serializers
from rest_framework.exceptions import APIException, ParseError
from rest_framework.parsers import MultiPartParser

from django.conf import settings
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent

from temba.msgs.usecases.broadcast_media import (
    FILES_FIELD,
    MAX_BROADCAST_FILES_TOTAL_BYTES,
    MULTIPART_CONTENT_TYPE,
    PAYLOAD_FIELD,
    BroadcastMediaInvalid,
    BroadcastMediaUnavailable,
    PreparedBroadcastRequest,
    read_broadcast_request,
)
from temba.utils.sentry import remove_request_body_and_frame_vars, scrub_events_for_current_request

logger = logging.getLogger(__name__)

# what a multipart body has besides the content of its parts: boundaries and part headers
MULTIPART_OVERHEAD_BYTES = 512 * 1024

# the most a request with media can have: the files of a full request, a payload as large as Django lets a form field
# be, and the multipart framing around them
MAX_BROADCAST_MULTIPART_BYTES = (
    MAX_BROADCAST_FILES_TOTAL_BYTES + settings.DATA_UPLOAD_MAX_MEMORY_SIZE + MULTIPART_OVERHEAD_BYTES
)

MEDIA_STORAGE_UNAVAILABLE_MESSAGE = "Media storage temporarily unavailable"

# the longest correlation identifier that is reported
MAX_CORRELATION_ID_LENGTH = 128


class BroadcastMultiPartParser(MultiPartParser):
    """
    The multipart parser of the broadcast endpoints. It turns what would be a server error into a 400: a request that
    is larger than any valid one is rejected from its Content-Length, before a byte of it is read or written to disk,
    and so is a payload over Django's limit for a form field, and a form with too many fields.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        request = parser_context["request"]

        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            content_length = 0

        if content_length > MAX_BROADCAST_MULTIPART_BYTES:
            raise ParseError({FILES_FIELD: ["The request is too large."]})

        try:
            return super().parse(stream, media_type, parser_context)
        except RequestDataTooBig:
            raise ParseError({PAYLOAD_FIELD: ["Payload is too large."]})
        except TooManyFieldsSent:
            raise ParseError({PAYLOAD_FIELD: ["The request has too many fields."]})


class MediaStorageUnavailable(APIException):
    """
    The media storage failed while handling the files of a request. It says nothing about what failed.
    """

    status_code = 503
    default_detail = MEDIA_STORAGE_UNAVAILABLE_MESSAGE
    default_code = "media_storage_unavailable"


def prepare_broadcast_request(request) -> PreparedBroadcastRequest:
    """
    Reads and validates the files of a broadcast request, returning its payload and files. For a JSON request this is
    its data as it is. A multipart request is registered for scrubbing of everything Sentry reports while it is handled,
    since the body and the variables of the frames hold the files and the payload.
    """
    is_multipart = (request.content_type or "").lower().startswith(MULTIPART_CONTENT_TYPE)
    if is_multipart:
        scrub_events_for_current_request()

    try:
        if is_multipart:
            return read_broadcast_request(request.content_type, request.POST, request.FILES)
        return read_broadcast_request(request.content_type, request.data, None)
    except BroadcastMediaInvalid as e:
        raise serializers.ValidationError(e.errors)


def payload_with_media(prepared: PreparedBroadcastRequest, org) -> dict:
    """
    The payload with the canonical attachment of each file added to msg.attachments, for the serializer to validate
    """
    try:
        return prepared.with_attachments(org)
    except BroadcastMediaInvalid as e:
        raise serializers.ValidationError(e.errors)


def correlation_identifier(request) -> str:
    """
    The identifier the caller or the gateway gave the request, to find it in other systems
    """
    value = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID") or ""
    return value[:MAX_CORRELATION_ID_LENGTH]


def _redact_exception_messages(event, hint):
    """
    Sentry event processor that removes what can name a file or object: the messages of the exceptions (botocore puts
    the URL of the request in them, and the URL has the key of the object) and the breadcrumbs (the standard library
    integration records the URL of every HTTP request). Exception types and stack traces are kept.
    """
    for exception in event.get("exception", {}).get("values", []):
        exception["value"] = ""

    event.pop("breadcrumbs", None)
    return event


def report_media_storage_failure(request, org, error: BroadcastMediaUnavailable, user=None):
    """
    Reports a failure of the media storage to Sentry and the log, with identifiers that find the request and no content
    of it: not a file name, file bytes, object key, URL or payload. The user is the one the request was resolved to, or
    the one it was authenticated as.
    """
    user = user if user is not None else getattr(request, "user", None)
    cause = type(error.__cause__).__name__ if error.__cause__ else "unknown"

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("org_id", org.id)
        scope.set_tag("project_uuid", str(org.proj_uuid or ""))
        scope.set_tag("user_id", getattr(user, "id", None) or "")
        scope.set_tag("correlation_id", correlation_identifier(request))
        scope.set_tag("media_stage", error.stage)
        scope.set_tag("media_cause", cause)

        scope.add_event_processor(remove_request_body_and_frame_vars)
        scope.add_event_processor(_redact_exception_messages)

        sentry_sdk.capture_exception(error)

    # only the stage and the type of the cause: the message of the cause can have a URL
    logger.warning("broadcast media storage failed: org_id=%s stage=%s cause=%s", org.id, error.stage, cause)
