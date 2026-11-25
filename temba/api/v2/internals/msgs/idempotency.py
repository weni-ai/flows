"""Idempotency-Key support for POST /api/v2/internals/messages/stream.

Same behavior as the broadcasts helper, with this endpoint's own Redis
namespace so the two never share a key. That module is imported for the body
hash only and is not modified.
"""

import logging

import redis
from redis.exceptions import RedisError

from django.conf import settings

from temba.api.v2.internals.broadcasts.idempotency import compute_body_hash
from temba.utils import json


def body_hash(request):
    """Hash the parsed body the same way the broadcasts endpoint does."""
    return compute_body_hash(request)


logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
MAX_KEY_LENGTH = 128

# A completed response is replayed for at least 24h (FR-020).
DONE_TTL_SECONDS = 86400

# An in-flight reservation belongs to one worker request. The gunicorn worker
# timeout is 120s (docker/gunicorn/gunicorn.conf.py); a reservation older than
# that belongs to a request that can no longer finish, so it must not block
# retries for the whole 24h retention of a completed response.
INFLIGHT_TTL_SECONDS = 120

REDIS_TIMEOUT_SECONDS = 2
REDIS_KEY_PREFIX = "idempotency:messages_stream"

CODE_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
CODE_IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"
CONFLICT_ERROR = "Idempotency-Key reused with different body"
IN_PROGRESS_ERROR = "Request with this Idempotency-Key is already being processed"
SERVICE_UNAVAILABLE_ERROR = "Service temporarily unavailable"

STATE_INFLIGHT = "inflight"
STATE_DONE = "done"

CLAIM_MISS = "miss"
CLAIM_HIT = "hit"
CLAIM_CONFLICT = "conflict"
CLAIM_IN_PROGRESS = "in_progress"

_client = None


def get_client():
    """Redis client with an explicit socket timeout.

    The shared cache client has no socket timeout, and redis-py blocks forever
    by default. A client owned by this module keeps that timeout off the global
    cache configuration.
    """
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.CACHES["default"]["LOCATION"],
            socket_timeout=REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        )
    return _client


def _redis_key(project_uuid, key):
    return f"{REDIS_KEY_PREFIX}:{project_uuid}:{key}"


def extract_key(request):
    """Return the key, or None when the header is absent, blank or too long.

    A blank or over-long key is treated as absent: no deduplication and no 400.
    """
    raw = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        return None
    return key


def claim(project_uuid, key, body_hash):
    """Reserve the key or report the entry already stored.

    Returns ``(CLAIM_MISS, None)`` when this caller owns the reservation,
    ``(CLAIM_HIT, ids)`` for a completed response with the same body,
    ``(CLAIM_CONFLICT, None)`` for a completed response with a different body,
    and ``(CLAIM_IN_PROGRESS, None)`` while another request holds the key.
    A conflict or in-progress result does not write. Redis errors propagate.
    """
    client = get_client()
    redis_key = _redis_key(project_uuid, key)
    marker = json.dumps({"state": STATE_INFLIGHT, "body_hash": body_hash})

    if client.set(redis_key, marker, nx=True, ex=INFLIGHT_TTL_SECONDS):
        return CLAIM_MISS, None

    raw = client.get(redis_key)
    if raw is None:
        if client.set(redis_key, marker, nx=True, ex=INFLIGHT_TTL_SECONDS):
            return CLAIM_MISS, None
        raw = client.get(redis_key)
        if raw is None:
            return CLAIM_IN_PROGRESS, None

    try:
        cached = json.loads(raw)
    except (ValueError, TypeError):
        return CLAIM_IN_PROGRESS, None

    if cached.get("state") == STATE_DONE:
        if cached.get("body_hash") == body_hash:
            return CLAIM_HIT, cached.get("ids")
        return CLAIM_CONFLICT, None

    return CLAIM_IN_PROGRESS, None


def store_success(project_uuid, key, body_hash, ids):
    """Remember a 201 so a replay returns the same ids. Refreshes the 24h TTL."""
    payload = json.dumps({"state": STATE_DONE, "body_hash": body_hash, "ids": list(ids)})
    get_client().set(_redis_key(project_uuid, key), payload, ex=DONE_TTL_SECONDS)


def release(project_uuid, key):
    """Drop the reservation of the request that claimed it. Failures are logged, not raised."""
    try:
        get_client().delete(_redis_key(project_uuid, key))
    except RedisError:
        logger.warning(
            "messages_stream idempotency release failed",
            extra={"project_uuid": str(project_uuid)},
        )
