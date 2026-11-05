# Quickstart: custom_data on WhatsApp broadcasts (Flows slice)

## Prerequisites

- Flows dev environment with Poetry
- Org with at least one contact URN and optional WhatsApp or WWC channel fixtures (channel not required for validation tests)
- Architecture contracts pinned at `006-wwc-custom-data/arch-v1` for error-string review

End-to-end delivery to webchat (`customData`) requires Mailroom, Courier, socket, and service from the architecture Impact Map — not this repo.

## 1. Unit validation helpers

```bash
poetry run coverage run manage.py test temba.msgs.tests.test_custom_data
```

Expected: depth 32 pass / 33 fail; forbidden keys at nested levels; 16384-byte boundary; `{}` normalization helper behavior.

## 2. Public API v2

```bash
poetry run coverage run manage.py test temba.api.v2.tests.APITest.test_whatsapp_broadcasts_custom_data
```

(Exact test class/method names will match `tasks.md` after `/speckit-tasks`.)

Expected: valid `custom_data` → `201` and metadata match; invalid shapes → `400` with OpenAPI strings; omit field → unchanged behavior.

## 3. Internal Django + idempotency

```bash
poetry run coverage run manage.py test temba.api.v2.internals.broadcasts.tests
```

Expected: same validation strings as public; one case reusing `Idempotency-Key` with different `custom_data` → `409`.

## 4. FastAPI internal route

```bash
poetry run coverage run manage.py test temba.fastapi_app.tests
```

Expected: `post_internal_whatsapp_broadcast` returns same `400`/`201` behavior via shared serializer.

## 5. Task payload (no `queue.py` change)

In a flow test, after `201`, run `send_async()` (or synchronous commit hook) and assert queued batch task:

- `type`: `send_whatsapp_broadcast`
- `task.msg.custom_data` equals submitted object
- `task.msg` does not retain popped `queue` when queue was only for routing

Pattern: `temba/mailroom/tests.py` `test_queue_whatsapp_broadcast`.

## 6. Repo gates

```bash
./code_check.py
poetry run coverage run manage.py test temba.api.v2 temba.api.v2.internals.broadcasts temba.fastapi_app temba.msgs
```

## Manual smoke (optional)

POST the example in [contracts/whatsapp-broadcast-custom-data.md](./contracts/whatsapp-broadcast-custom-data.md) to:

- `POST /api/v2/whatsapp_broadcasts.json` (Token auth)
- `POST /api/v2/internals/whatsapp_broadcasts` (internal auth + `project`)

Confirm `201` and response `metadata.custom_data`. POST `custom_data: null` → `400` with `custom_data must be an object`.

## Deploy note (Flows only)

Ship after webchat-service, weni-webchat-socket, and Courier; before Mailroom. Do not roll back Flows validation alone if Mailroom propagation is already live — see [spec.md](./spec.md) Rollout and Rollback.
