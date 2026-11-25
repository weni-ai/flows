# Implementation Plan: Inline media files in WhatsApp broadcast requests

**Branch**: `019-broadcast-inline-media` (no git branch created) | **Date**: 2026-11-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/019-broadcast-inline-media/spec.md`

## Summary

Both WhatsApp broadcast endpoints accept a `multipart/form-data` variant: one `payload` field holding today's JSON body, and up to 10 `files`. A new use case in `temba/msgs/usecases/broadcast_media.py` parses the payload, validates and hashes each file in one chunked pass, and detects its type with libmagic. It computes each canonical unsigned URL from org, hash and type, and appends the URLs to `msg.attachments`. The serializer then validates the complete payload. Only in `save()` does a new subclass, `WhatsappBroadcastWithMediaWriteSerializer`, check the per-org Redis dedup entry and upload missing objects through a timeout-bounded storage. It then hands off to today's `save()`. The public endpoint hooks in through `get_write_serializer_class`, so `WriteAPIMixin.post` is unchanged. The internal endpoint swaps `request.data` for the prepared payload and hashes the payload plus the file hashes for idempotency. JSON requests and the FastAPI bridge follow exactly today's code path.

## Technical Context

**Language/Version**: Python >=3.10,<3.12 (CI 3.11), Django 3.2.25, DRF 3.15.1

**Primary Dependencies**: django-storages 1.14.6 (`S3Storage`), boto3/botocore 1.42, redis-py 3.5.3, django-redis 4.12.1, python-magic 0.4.27 (declared, first use) with the system library `libmagic1` (new in `docker/Dockerfile` and CI), sentry-sdk 1.45.1. No new Python dependency.

**Storage**: S3 bucket `AWS_STORAGE_BUCKET_NAME` (via `private_file_storage`'s class) for objects. Redis `CACHES["default"]` location for dedup entries and the existing idempotency records. PostgreSQL `msgs_broadcast.metadata` unchanged. No migration.

**Testing**: `TembaTest`; `poetry run coverage run manage.py test temba.msgs.usecases temba.utils.s3 temba.api.v2 temba.fastapi_app`; `./code_check.py`.

**Target Platform**: Flows web process (gunicorn sync workers, `timeout = 120`) behind the Kubernetes ingress and, for the public route, Kong (`api_gateway_expose(alias="broadcasts")`).

**Project Type**: Django web service, REST API.

**Performance Goals**: A repeated file adds one hash pass, one libmagic call on `MEDIA_SNIFF_BYTES`, and one Redis `GET`. It adds no S3 call (SC-002, SC-003). A new file adds one S3 upload, done in parallel parts by django-storages above its multipart threshold.

**Constraints**: S3 connect 5 s, read 30 s, and `S3_UPLOAD_MAX_RETRY_ATTEMPTS` = 2 (botocore standard mode: exponential backoff with jitter) bound each S3 HTTP call. django-storages may issue many calls for one multipart `save()`, so those limits are not a cap on `save()`. `save()` runs on the request thread. Inside one `try`, before `save()` is called, a `threading.Timer` of `S3_UPLOAD_CALL_BUDGET_SECONDS` (60) is started to set a `threading.Event`, and a botocore `before-send` handler on that storage client raises `ReadTimeoutError` when the event is set. The handler is unregistered and the timer cancelled in the `finally` of that same `try`. `before-send` fires only before the next HTTP call. An attempt already on the wire still runs for at most `S3_UPLOAD_CONNECT_TIMEOUT_SECONDS` + `S3_UPLOAD_READ_TIMEOUT_SECONDS` (35 s). Before each `save()`, if elapsed time plus 60 s plus 35 s would reach `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS` (120, gunicorn's worker timeout), that upload is not started. Both cases return `503`. A `save()` that is allowed to start returns before the worker is killed. The request and the spooled temp file wait until `save()` returns. No upload thread outlives the request. Redis connect and socket timeouts are 2 s, with no Redis retry. Dedup entries expire after 7 days. At most 10 files and 100 MiB per request. The payload part is at most `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB). No presigning. No client file name in keys, logs or Sentry.

**Scale/Scope**: Public ceiling of 10 requests per second per throttle identity (`WhatsappBroadcastsEndpoint`, `v2.broadcasts`, 36,000 per hour). The internal endpoint stays unthrottled; its planning peak is 100 sequential campaign calls, one image each, upload on the first call only. Production today is about 30,000 attachments a month for one org. Two endpoints, one use case, one storage helper.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Pre-research gate: passed. The open items (type detection without a system library, S3 and Redis timeouts without changing global settings, uploading after validation with `WriteAPIMixin.post` unchanged) were resolved in research without a principle exception.

| Principle | Result |
|---|---|
| I. Version Control and Review | PR from `019-broadcast-inline-media`, review, green `ci.yml`. |
| II. Security and Secrets | No new secret; existing AWS credentials. Least privilege: only `s3:PutObject` on `attachments/*`, already used; no `HeadObject` (research R4). Dependency named: system `libmagic1` for the already declared `python-magic`; neither affects authentication or cryptography. Uploaded bytes are typed by content, stored privately, and never served by Flows. |
| III. Observability | Storage failures logged and reported with opaque identifiers only. No client file name, file bytes, object key with signature, or payload. `scrub_events_for_current_request()` (`temba/utils/sentry.py`) is registered on every multipart request. |
| IV. Versioned Contracts | Additive variant on two DRF endpoints; JSON is byte-for-byte the same path (FR-001). Flows MINOR. Courier version: none; Courier already signs the Flows bucket (courier#243). Mailroom version: none. Contract in [contracts/](./contracts/whatsapp-broadcasts-multipart.openapi.yaml). |
| V. Specification Traceability | Origin without product spec; AC-1 to AC-10 each map to a flow test below. |
| VI. No Silent Divergence | Not applicable. |
| VII. Commit Messages | Conventional, atomic: storage helper, use case, endpoints, docs, image/CI dependency, changelog. |
| VIII. Changelog | `feat:` bullet under the next unreleased version in `WENI-CHANGELOG.md`: multipart media on `whatsapp_broadcasts.json` and the internal endpoint. |
| IX. Never Trust the Client | Type from bytes, per-type and total size, count, field names and payload shape are validated in the use case before any side effect. Payload rules are validated by the existing serializer. Views only call the use case and pick the serializer. |
| X. Fail Gracefully | Explicit S3 and Redis timeouts as named constants. Connect, read, and attempt limits bound each S3 HTTP call. `save()` runs on the request thread. Before `save()`, a `threading.Timer` of `S3_UPLOAD_CALL_BUDGET_SECONDS` sets an event and a botocore `before-send` handler raises `ReadTimeoutError` on the next send. The handler is unregistered and the timer cancelled in the `finally` of that same `try`. An attempt already on the wire is bounded by the connect and read timeouts. A new `save()` is refused when elapsed time plus the budget plus one in-flight attempt would reach `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS` (120). Both return `503`. The spooled file is deleted only after `save()` has returned or raised. S3 or Redis failure returns `503` with a generic body. Invalid input returns `400` with field errors. A large `Content-Length` and `RequestDataTooBig` become `400` instead of reaching the handler as `500`. |
| XI. Bounded Retry | Each S3 HTTP call: botocore standard mode (exponential backoff with jitter), `S3_UPLOAD_MAX_RETRY_ATTEMPTS` (2), on an idempotent content-addressed `PUT`. Exhausted attempts, a `before-send` abort, and a refused start become the existing `503` (logged, internal key released). Redis: no retry; a failure returns `503` and the caller retries, with the internal key released. |
| XII. Scalability and Peak Load | Stateless. `save()` stays on the request thread, so the spooled file dies with the request and no upload thread outlives it. Shared state only in S3 and Redis. Peak as declared in the spec. |
| XIII. Diagnosable Errors | Sentry tags: `org_id`, `project_uuid`, `user_id`, `correlation_id` (`X-Request-ID` or `X-Correlation-ID`), `media_stage` (`dedup_lookup`, `upload`, `dedup_record`). These endpoints have no account entity beyond the project, so `project_uuid` is the account-level identifier. No personal data. |
| XIV. Tests Exercise Flows | At least one request-to-stored-broadcast test per acceptance criterion, on each endpoint where it applies. Unit tests for detection and limits. S3 is stubbed only at `storage.save`; Redis is real (CI service). |
| XV. Explicit Over Clever | Every limit, timeout, attempt count, per-save call budget, worker timeout, time to live, sniff size, MP4 box-walk cap, multipart overhead, and key prefix is a named constant in the use case, the s3 module, or the API glue. The upload inside `save()` is explicit in the subclass name and docstring. |
| XVI. Contained Changes | Files listed under Source Code only. `Dockerfile` and `ci.yml` change only to add `libmagic1`, which detection requires. FastAPI bridge, `upload_media`, `S3MediaProxyView`, global cache and storage settings untouched. |
| XVII. Explicit, Scoped Authorization | No permission change. `InternalWhatsappBroadcastsEndpoint` still composes `IsAuthenticated`: pre-existing, not introduced here, listed out of scope in the spec, to be fixed in its own change. |
| SDD cycle | Full: public contract change. |

Post-design re-check: passed. No unjustified violation. The only noted item is the pre-existing XVII violation, which this change does not touch.

## Project Structure

### Documentation (this feature)

```text
specs/019-broadcast-inline-media/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/whatsapp-broadcasts-multipart.openapi.yaml
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks, not this command
```

### Source Code (repository root)

```text
temba/msgs/usecases/broadcast_media.py              # new: constants, InlineMedia, PreparedBroadcastRequest,
                                                    #      read_broadcast_request, store_broadcast_media, errors
temba/msgs/usecases/__init__.py                     # export the public names
temba/msgs/usecases/tests/test_broadcast_media.py   # new: unit tests (detection, limits, hashing, dedup)
temba/utils/s3/s3.py                                # media_upload_storage() + S3 upload timeout constants
temba/utils/s3/tests.py                             # config of media_upload_storage()
temba/api/v2/broadcast_media.py                     # new: BroadcastMultiPartParser, MediaStorageUnavailable,
                                                    #      prepare_broadcast_request(request), failure reporting
temba/api/v2/serializers.py                         # WhatsappBroadcastWithMediaWriteSerializer
temba/api/v2/views.py                               # WhatsappBroadcastsEndpoint: parser_classes,
                                                    #      get_write_serializer_class, docstring, write explorer
temba/api/v2/internals/broadcasts/views.py          # InternalWhatsappBroadcastsEndpoint.post, parser_classes
temba/api/v2/internals/broadcasts/idempotency.py    # compute_media_body_hash
temba/api/v2/tests.py                               # public flow tests
temba/api/v2/internals/broadcasts/tests.py          # internal flow + idempotency tests
docker/Dockerfile                                   # RUNTIME_DEPS += libmagic1
.github/workflows/ci.yml                            # apt install += libmagic1
WENI-CHANGELOG.md
```

**Structure Decision**: The business logic goes in `temba/msgs/usecases/`, where broadcast use cases already live (`managed_trigger_group`, `named_template_broadcast`). It takes Django uploads and plain dicts, not DRF requests. DRF-specific glue (parser, `APIException`, error conversion, Sentry context) lives in `temba/api/v2/broadcast_media.py`, which both views import. The storage helper sits next to the other S3 helpers.

## Design

### Use case (`temba/msgs/usecases/broadcast_media.py`)

- `read_broadcast_request(content_type, fields, files) -> PreparedBroadcastRequest`
  - JSON or any non-multipart type: returns `is_multipart=False` with `payload` set to the given data object, untouched.
  - Multipart: runs validation steps 2 to 5 from [data-model.md](./data-model.md). It collects every error and raises `BroadcastMediaInvalid(errors)` once.
  - One pass per file over `file.chunks()` updates `hashlib.sha256()` and keeps the first `MEDIA_SNIFF_BYTES`. `detect_media_type(head, file)` calls libmagic, applies `LIBMAGIC_MIME_ALIASES`, and refines ISO BMFF audio-only files with a box-header walk capped by `MP4_MAX_BOXES_PER_LEVEL` (64). Hitting the cap leaves libmagic's type unchanged.
- `PreparedBroadcastRequest.with_attachments(org) -> dict` returns a payload copy with `msg.attachments` extended in order.
- `store_broadcast_media(org, media) -> None`
  - Runs once per distinct `sha256`, in order.
  - Calls dedup `GET`. A hit with an equal value skips the file.
  - Before each `save()`, if elapsed time plus `S3_UPLOAD_CALL_BUDGET_SECONDS` plus `S3_UPLOAD_CONNECT_TIMEOUT_SECONDS` plus `S3_UPLOAD_READ_TIMEOUT_SECONDS` would reach `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS`, it raises `BroadcastMediaUnavailable("upload")` and does not call S3.
  - Otherwise, on the request thread and inside one `try`, it starts a `threading.Timer` of `S3_UPLOAD_CALL_BUDGET_SECONDS` that sets a `threading.Event`. When the storage exposes a botocore client, it registers a `before-send` handler on `client.meta.events` that raises `botocore.exceptions.ReadTimeoutError` when the event is set. Then it sets `file.content_type = mime` and calls `media_upload_storage().save(key, file)` (the returned name is ignored; see research R4). The handler is unregistered and the timer cancelled in the `finally` of that same `try`. `before-send` does not stop an attempt that has already passed it; that attempt still ends at the connect and read timeouts. Filesystem storage has no client, so no handler is registered and the call budget does not abort that `save()`. A handler raise, and any `botocore.exceptions.BotoCoreError`, `botocore.exceptions.ClientError`, `boto3.exceptions.Boto3Error` (including `S3UploadFailedError`), or `OSError`, becomes `BroadcastMediaUnavailable("upload")` with `__cause__` kept, and the next file is not started. On success it dedups with `SET ... EX BROADCAST_MEDIA_DEDUP_TTL_SECONDS`.
  - `redis.exceptions.RedisError` from the dedup `GET` or `SET` is re-raised as `BroadcastMediaUnavailable` with stage `dedup_lookup` or `dedup_record`. The request thread is still inside `store_broadcast_media` when the temp file is closed.
- Constants: `MAX_BROADCAST_FILES`, `MAX_BROADCAST_FILES_TOTAL_BYTES`, `MAX_IMAGE_BYTES`, `MAX_STICKER_BYTES`, `MAX_VIDEO_BYTES`, `MAX_AUDIO_BYTES`, `MAX_DOCUMENT_BYTES`, `ALLOWED_BROADCAST_MEDIA`, `LIBMAGIC_MIME_ALIASES`, `MEDIA_SNIFF_BYTES = 256 * 1024`, `MP4_MAX_BOXES_PER_LEVEL = 64`, `BROADCAST_MEDIA_DEDUP_TTL_SECONDS = 7 * 24 * 60 * 60`, `BROADCAST_MEDIA_DEDUP_KEY_PREFIX = "broadcast_media"`, `BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS = 2`, `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS = 120`, `S3_UPLOAD_CALL_BUDGET_SECONDS = 60`, `PAYLOAD_FIELD = "payload"`, `FILES_FIELD = "files"`.
- The dedup client is `_dedup_redis()`, cached once per process: `redis.Redis.from_url(settings.CACHES["default"]["LOCATION"], socket_timeout=BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS)`. No retry policy is set.

### Storage helper (`temba/utils/s3/s3.py`)

`media_upload_storage()`, cached once per process, returns an instance of the configured `S3Storage` subclass with `file_overwrite=True` and `client_config` merged with `Config(connect_timeout=S3_UPLOAD_CONNECT_TIMEOUT_SECONDS, read_timeout=S3_UPLOAD_READ_TIMEOUT_SECONDS, retries={"mode": "standard", "max_attempts": S3_UPLOAD_MAX_RETRY_ATTEMPTS})`. `S3_UPLOAD_CONNECT_TIMEOUT_SECONDS = 5`, `S3_UPLOAD_READ_TIMEOUT_SECONDS = 30`, and `S3_UPLOAD_MAX_RETRY_ATTEMPTS = 2`. The existing `S3_CLIENT_MAX_RETRY_ATTEMPTS = 3`, used by the shared `client()` and `regional_client()`, is not changed. Standard mode is exponential backoff with jitter. The attempt count is 2, rather than the 3-attempt illustration in research R3. These three limits apply to each HTTP call. The use case arms the timer and the client's `before-send` handler before `save()`. The handler raises `ReadTimeoutError` on the next send after the event is set. It does not stop an attempt already on the wire; that attempt is bounded by these connect and read timeouts. With any other storage class it returns `private_file_storage` (research R3).

### API glue (`temba/api/v2/broadcast_media.py`)

- Constants: `MULTIPART_OVERHEAD_BYTES = 512 * 1024`, `MAX_BROADCAST_MULTIPART_BYTES = MAX_BROADCAST_FILES_TOTAL_BYTES + DATA_UPLOAD_MAX_MEMORY_SIZE + MULTIPART_OVERHEAD_BYTES`, `MEDIA_STORAGE_UNAVAILABLE_MESSAGE = "Media storage temporarily unavailable"`.
- `BroadcastMultiPartParser(MultiPartParser)` does two things:
  - Rejects `Content-Length > MAX_BROADCAST_MULTIPART_BYTES` with `ParseError({"files": [...]})`.
  - Converts `RequestDataTooBig` to `ParseError({"payload": ["Payload is too large."]})` and `TooManyFieldsSent` to a `400`.
- `prepare_broadcast_request(request) -> PreparedBroadcastRequest`:
  - For multipart, it registers `scrub_events_for_current_request()`, then calls the use case with `request.POST` and `request.FILES`.
  - It converts `BroadcastMediaInvalid` to `serializers.ValidationError(errors)`.
  - For JSON, it calls the use case with `request.data`, which comes back untouched.
- `MediaStorageUnavailable(APIException)` has `status_code = 503` and `default_detail = MEDIA_STORAGE_UNAVAILABLE_MESSAGE`.
- `report_media_storage_failure(request, org, error)`:
  - Inside `sentry_sdk.push_scope()`, it sets the tags from the Constitution Check (XIII) and calls `logger.exception("broadcast media storage failed")`.
  - The message has no key, URL or name.
- `correlation_identifier(request)` reads `X-Request-ID`, then `X-Correlation-ID`.

### Serializer (`temba/api/v2/serializers.py`)

`WhatsappBroadcastWithMediaWriteSerializer(WhatsappBroadcastWriteSerializer)`:

- It is used for every multipart request, with or without files.
- `errors` nests the parent's errors under `payload` (FR-013).
- `save()` calls `store_broadcast_media(org, context["inline_media"])`. On `BroadcastMediaUnavailable` it reports the failure and raises `MediaStorageUnavailable`. Then it returns `super().save()`.
- The parent class, and so the FastAPI bridge, is unchanged (FR-026).

### Public endpoint flow (`WhatsappBroadcastsEndpoint`)

1. `parser_classes = (JSONParser, FormParser, BroadcastMultiPartParser)`, the DRF defaults with only the multipart parser replaced. `write_with_transaction = False` stays.
2. `WriteAPIMixin.post` (unchanged) builds the context and calls `get_write_serializer_class(instance, data, context)`.
3. The override calls `prepared = prepare_broadcast_request(self.request)`. JSON then returns `super().get_write_serializer_class(...)`, exactly today's path. Multipart without an org raises `InvalidQueryError("Organization not found")`. Otherwise it sets `context["inline_media"] = prepared.media` and returns `WhatsappBroadcastWithMediaWriteSerializer(instance=instance, data=prepared.with_attachments(org), context=context)`.
4. `is_valid()` returns `400` on failure, with nothing uploaded. Then `save()` uploads and creates the broadcast, and `render_write_response` returns `201`. `MediaStorageUnavailable` propagates to `temba_exception_handler` and becomes `503 {"detail": ...}`. `throttle_scope` stays `v2.broadcasts`.

### Internal endpoint flow (`InternalWhatsappBroadcastsEndpoint.post`)

1. `parser_classes` is set as on the public endpoint. `throttle_classes` stays `[]`.
2. `prepared = prepare_broadcast_request(request)`. A `400` here happens before any key is claimed. Then `data = dict(prepared.payload)`.
   For multipart, `IsUserInOrg` could not see the project, which is inside `payload`, so the view gives the project of the payload to the request when it has none and checks the permissions again (`check_permissions_for_payload_project`). A user who is not of that project gets the same `403` as for JSON. The permission classes are not changed.
3. `project_uuid` is `request.project_uuid` or `data["project"]`, as today, but read from the parsed payload.
4. `body_hash` is `compute_body_hash(request)` for JSON (unchanged) or `compute_media_body_hash(prepared.payload, prepared.file_sha256s)` for multipart. The lookup is unchanged, so `hit` and `409` return before any upload.
5. `resolve_org_and_user_internal_whatsapp(drf_request=request, data=data)`, unchanged.
6. The serializer is `WhatsappBroadcastWriteSerializer(data=request.data, ...)` for JSON (unchanged). For multipart it is `WhatsappBroadcastWithMediaWriteSerializer(data=prepared.with_attachments(org), context={..., "inline_media": prepared.media})`.
7. A new `except MediaStorageUnavailable` before the generic `except Exception` releases the key and returns `Response({"error": MEDIA_STORAGE_UNAVAILABLE_MESSAGE}, 503)`. Every other path is as today.

### Docs

- The docstring gains a "Sending media files" section with the multipart shape, the order rule, the type and size table, and a `curl -F` example.
- `get_write_explorer` gains a `files` entry ("multipart requests only; the explorer sends JSON") and mentions files in the `attachments` help text.

### Orphan trade-off

An upload happens only after every boundary and serializer check passes. The remaining window is `WhatsappBroadcastWriteSerializer.save()` failing after the upload, from trigger group quota, contact resolution or Mailroom. Its `400` leaves the object and its dedup entry in place. Keys are content-addressed per org, so this is bounded: at most one object per distinct (org, content), and it is reused by the next request with the same bytes. No cleanup is added (research R1).

## Test Strategy

Bases: `TembaTest`. The public tests sit next to `test_whatsapp_broadcasts` (`APITest`) and patch `queue_broadcast` like their neighbors. The internal tests follow `TestInternalWhatsappBroadcast`, `TestInternalWhatsappBroadcastJWT` and `TestInternalWhatsappBroadcastIdempotency`.

S3 is stubbed only at the storage boundary: `patch.object(private_file_storage, "save")`, which `media_upload_storage()` returns under test settings. Redis is the real CI service. Failure tests patch the dedup client's `get` or `set` to raise `redis.exceptions.ConnectionError` or `TimeoutError`. Fixtures come from `media/test_media/`, except the audio-only MP4 ("m4a" in the table below): `snow.m4a` is a copy of `snow.mp4` and still has video, so tests use `audio_only_mp4_bytes()` from `temba/tests/media.py`, which drops the video track of `snow.mp4` in memory. Oversize files are a real header plus padding. Every flow test asserts both the HTTP response and the resulting `Broadcast` rows, plus the `save` calls.

| AC | Flow tests (request → stored broadcast) |
|---|---|
| AC-1 | Existing JSON tests on both endpoints and the idempotency suite stay unmodified. New `test_json_path_unchanged` on each endpoint asserts that `WhatsappBroadcastWriteSerializer` is used, the `201` body and `metadata` match today's JSON behavior, and that `save` is not called. The internal test also asserts the view calls `compute_body_hash`. |
| AC-2 | `test_multipart_single_image` on each endpoint: `201`, `metadata["attachments"][-1] == f"image/jpeg:{STORAGE_URL}/attachments/{org.id}/broadcasts/{sha}.jpg"`, `"X-Amz-" not in` it, `save` called with that key and `content_type == "image/jpeg"`. A variant sends the JPEG as `photo.bin` with `application/octet-stream`. |
| AC-3 | `test_multipart_order_with_existing_urls`: 2 URLs plus jpg, mp4 and m4a, giving `[U1, U2, image/jpeg…, video/mp4…, audio/mp4…]`. `test_duplicate_file_in_one_request`: one `save` call, both positions equal. `test_template_header_uses_first_file`: template payload with no URLs; the file is `attachments[0]`. |
| AC-4 | `test_same_file_twice_uploads_once`: two requests, one `save` call, the same URL in both broadcasts, a dedup key present with a time to live. `test_same_file_other_org_uploads_again`: `org2` gets its own key. |
| AC-5 | `test_multipart_rejections` (subTest per case) on each endpoint: missing, duplicated, non-JSON and array `payload`; payload failing today's rules (nested under `payload`); unknown field `file`; empty file; GIF; HTML; `allo.wav`; 6 MiB JPEG; 17 MiB MP4; one document over `MAX_DOCUMENT_BYTES`; 11 files; over 100 MiB total (via the `Content-Length` guard and via sizes). Each asserts `400`, the expected error key or position, `save` not called, and `Broadcast` count unchanged. On the internal endpoint no idempotency key is written. A payload part over `DATA_UPLOAD_MAX_MEMORY_SIZE` returns `400` on `payload`. |
| AC-6 | `test_s3_failure_returns_503` on each endpoint, with `save` raising `ClientError`, `S3UploadFailedError` and `ReadTimeoutError`: `503` with the generic body and no `Traceback`, no broadcast. The Sentry scope has `org_id`, `project_uuid`, `user_id`, `correlation_id`, and `media_stage`, and the event has no file name, bytes, key, or URL. On the internal endpoint the idempotency key is absent afterwards, and a retry with the same key returns `201`. |
| AC-7 | `test_idempotency_multipart_replay`: same key and content, giving the stored body, no second `save`, one broadcast. `test_idempotency_multipart_conflict`: same key with different bytes, and with the same files reordered, giving `409` and no `save`. `test_idempotency_multipart_json_hash_compat`: the JSON hash equals today's value. |
| AC-8 | Public: API Key, and JWT with project claims (patched decode, as in the neighbors). Internal: OIDC user with `project` in `payload`, and JWT with project claims. All give `201` with the stored attachment. Internal `payload.project` mismatching the JWT gives `403` and no `save`. |
| AC-9 | `test_dedup_cache_failure_returns_503` on each endpoint: `get` raising gives `503` with no `save`. `set` raising after a successful `save` gives `503`. Neither creates a broadcast, and on the internal endpoint the key is released. Both assert the same five Sentry tags as AC-6, with no file name, bytes, key, or URL. |
| AC-10 | `temba/fastapi_app/tests.py` and `temba/fastapi_app/broadcasts.py` stay unmodified and the existing bridge tests stay green. `test_bridge_serializer_unchanged` in `temba/api/v2/internals/broadcasts/tests.py` asserts that `post_internal_whatsapp_broadcast` still depends on `verify_jwt`, still constructs `WhatsappBroadcastWriteSerializer` with the JSON body, and that `broadcasts.py` does not reference `WhatsappBroadcastWithMediaWriteSerializer` or `BroadcastMultiPartParser`. |

Unit tests (`test_broadcast_media.py`, `temba/utils/s3/tests.py`) cover:

- the type and limit table at each boundary (limit, limit + 1)
- the alias table
- audio-only MP4 classified as audio; a level with 65 boxes stops at `MP4_MAX_BOXES_PER_LEVEL` (64) and keeps libmagic's type
- the hash equal to `hashlib.sha256` of the fixture
- `with_attachments` on a missing or non-list `msg.attachments`
- `media_upload_storage()` under `DEFAULT_FILE_STORAGE` S3: connect and read timeouts, retry mode `standard`, `max_attempts == 2`, `file_overwrite`, no network call
- `_dedup_redis()` uses `socket_timeout` and `socket_connect_timeout` of `BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS` (2) and sets no retry
- the dedup `SET` expiry equals `BROADCAST_MEDIA_DEDUP_TTL_SECONDS` (`7 * 24 * 60 * 60`)
- a fake clock where elapsed time plus `S3_UPLOAD_CALL_BUDGET_SECONDS` plus `S3_UPLOAD_CONNECT_TIMEOUT_SECONDS` plus `S3_UPLOAD_READ_TIMEOUT_SECONDS` reaches `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS` (120) makes the next file skip `save` and raise `BroadcastMediaUnavailable("upload")`
- a fake client exposes `meta.events`. `save()` performs two sends. The first send is already past `before-send` when the call-budget event is set, and that attempt returns on its own. The second send's `before-send` raises `ReadTimeoutError`. The next file is not started, the handler is unregistered, and `store_broadcast_media` raises `BroadcastMediaUnavailable("upload")`

No `# pragma: no cover` is added.

## Rollout

1. Ship `libmagic1` in the image and in CI in the same PR.
2. Before deploy, confirm the gates in [quickstart.md](./quickstart.md):
   - ingress and Kong body size of at least `MAX_BROADCAST_MULTIPART_BYTES`, with request buffering on
   - IAM `PutObject` on `attachments/*`
   - no lifecycle rule shorter than the dedup time to live
3. Deploy. JSON traffic is unaffected. Run the staging checks in the quickstart.
4. Rollback: revert the PR. Objects and dedup entries already written are harmless. Broadcasts already created keep URLs that Courier still signs.

## Complexity Tracking

No constitution violation is introduced. The system package `libmagic1` is the one infrastructure change, justified in research R2.
