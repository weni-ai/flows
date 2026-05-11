"""
Idempotency-Key support for the internal WhatsApp broadcasts endpoint.

The header is optional: callers that omit it keep the legacy behavior.
When the header is present, this module deduplicates ``(project_uuid, key)``
requests for 24h via Redis so that retries of the same logical submission
do not dispatch the broadcast (or bill the customer) twice.
"""

import hashlib

from django_redis import get_redis_connection

from temba.utils import json

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
MAX_KEY_LENGTH = 200
TTL_SECONDS = 86400  # 24 hours

STATE_INFLIGHT = "inflight"
STATE_DONE = "done"

LOOKUP_MISS = "miss"
LOOKUP_HIT = "hit"
LOOKUP_CONFLICT = "conflict"
LOOKUP_INFLIGHT = "inflight"


def _redis_key(project_uuid, key: str) -> str:
    return f"idempotency:whatsapp_broadcasts:{project_uuid}:{key}"


def extract_idempotency_key(request) -> str | None:
    """
    Reads the ``Idempotency-Key`` header from the request.

    Returns ``None`` when the header is absent, blank, or longer than
    ``MAX_KEY_LENGTH``. Those cases fall back to the legacy flow with
    no dedupe guarantee instead of erroring out.
    """
    raw = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if not raw:
        return None

    key = raw.strip()
    if not key:
        return None
    if len(key) > MAX_KEY_LENGTH:
        return None

    return key


def compute_body_hash(request) -> str:
    """
    Hashes the raw request body so we can detect when the same key is reused
    with a different payload.
    """
    return hashlib.sha256(request.body or b"").hexdigest()


def idempotency_lookup(project_uuid, key: str, body_hash: str) -> tuple[str, dict | None]:
    """
    Atomically claims the idempotency slot or reports the existing entry.

    Returns one of:
    - ``("miss", None)``: this caller owns the slot and must call
      ``idempotency_store_success`` on success or ``idempotency_release`` on
      any non-success path.
    - ``("hit", cached)``: the slot already has a completed response whose
      body hash matches; the caller should replay it.
    - ``("conflict", None)``: the slot has a completed response but with a
      different body hash; the caller should return 409.
    - ``("inflight", None)``: another request is currently processing this
      key; the caller should return 409.
    """
    r = get_redis_connection()
    redis_key = _redis_key(project_uuid, key)

    marker = json.dumps({"state": STATE_INFLIGHT, "body_hash": body_hash})

    # SET ... NX EX 86400 -- atomic claim of the slot.
    claimed = r.set(redis_key, marker, nx=True, ex=TTL_SECONDS)
    if claimed:
        return LOOKUP_MISS, None

    raw = r.get(redis_key)
    if raw is None:
        # Entry expired between SETNX and GET; reclaim.
        claimed = r.set(redis_key, marker, nx=True, ex=TTL_SECONDS)
        if claimed:
            return LOOKUP_MISS, None
        raw = r.get(redis_key)
        if raw is None:
            return LOOKUP_INFLIGHT, None

    try:
        cached = json.loads(raw)
    except (ValueError, TypeError):
        return LOOKUP_INFLIGHT, None

    state = cached.get("state")
    if state == STATE_DONE:
        if cached.get("body_hash") == body_hash:
            return LOOKUP_HIT, cached
        return LOOKUP_CONFLICT, None

    return LOOKUP_INFLIGHT, None


def idempotency_store_success(project_uuid, key: str, body_hash: str, status_code: int, body) -> None:
    """
    Persists the successful response so subsequent replays return identical
    output. Overwrites the in-flight marker and refreshes the TTL to 24h.
    """
    r = get_redis_connection()
    redis_key = _redis_key(project_uuid, key)

    payload = json.dumps(
        {
            "state": STATE_DONE,
            "status": status_code,
            "body": body,
            "body_hash": body_hash,
        }
    )
    r.set(redis_key, payload, ex=TTL_SECONDS)


def idempotency_release(project_uuid, key: str) -> None:
    """
    Drops the in-flight marker so the caller can retry with a corrected body
    under the same key. Called on any non-success path (validation errors,
    org/user resolution failures, unexpected exceptions).
    """
    r = get_redis_connection()
    r.delete(_redis_key(project_uuid, key))
