# Engineering Spec: Inline media files in WhatsApp broadcast requests

**Feature Branch**: `019-broadcast-inline-media`

**Created**: 2026-11-16

**Status**: Draft

**Cycle**: SDD Full (it changes a public API contract under `temba/api`, Principle IV)

**Input**: User description: "Accept media files inline in WhatsApp broadcast requests. The caller sends the media file in the same broadcast request; Flows stores it and the broadcast goes out with that media. Lowest added latency is the top criterion: requiring a separate upload request first is not acceptable."

## Origin Without Product Spec

- Product Spec: none
- Problem: The Flows S3 buckets are now private. Customers running promotion broadcasts to groups used to put public Flows S3 image URLs in `msg.attachments`; they can no longer obtain a working public link, so sending images in WhatsApp broadcasts became hard. There is no way to send the media file together with the broadcast request.
- Acceptance criteria:
  - AC-1: A JSON request to either endpoint behaves exactly as today and returns `201`.
  - AC-2: A multipart request with one file returns `201`, and the stored broadcast `metadata.attachments` ends with `<detected mime>:<STORAGE_URL>/attachments/<org_id>/broadcasts/<sha256>.<ext>`, with no `X-Amz-*` parameter.
  - AC-3: A multipart request with several files and URLs already present in `payload.msg.attachments` stores the payload URLs first, then the files in the order they were received.
  - AC-4: When the same file content is sent twice for the same org, the second request does not upload it again.
  - AC-5: A missing or invalid `payload`, a file of a disallowed type, an oversize file, or more than 10 files returns `400` with field errors; nothing is uploaded and no broadcast is created.
  - AC-6: A storage failure while uploading the file returns `503` with a generic error and no stack trace; no broadcast is created, and on the internal endpoint the `Idempotency-Key` is released.
  - AC-7: On the internal endpoint, reusing an `Idempotency-Key` with different file content returns `409`; reusing it with the same payload and the same file content replays the stored response without uploading.
  - AC-8: Multipart works on both endpoints with their current authentication methods.
  - AC-9 (from binding decision 7): A failure of the deduplication cache while handling a multipart request returns `503`, creates no broadcast, and releases the internal `Idempotency-Key`.
  - AC-10 (from the out-of-scope constraint): The FastAPI bridge `POST /fastapi/internal/whatsapp_broadcasts` keeps accepting JSON and behaves as today.

## Clarifications

### Session 2026-11-16

- Q: Per-file limits and the 10-file cap allow about 1 GB in one request. What is the total request size cap? → A: 100 MB of files in total, the largest single-file limit, so one maximum-size document still fits. Over the cap returns `400` and uploads nothing.

## Scope

**In scope**:

- Public endpoint: `POST /api/v2/whatsapp_broadcasts.json` (`WhatsappBroadcastsEndpoint`, `temba/api/v2/views.py`).
- Internal endpoint: `POST /api/v2/internals/whatsapp_broadcasts` (`InternalWhatsappBroadcastsEndpoint`, `temba/api/v2/internals/broadcasts/views.py`), including its `Idempotency-Key` handling.

**Out of scope**:

- The FastAPI bridge `/fastapi/internal/whatsapp_broadcasts`. It stays JSON only and MUST keep working; it reuses `WhatsappBroadcastWriteSerializer`, so the JSON contract of that serializer MUST NOT change.
- The internal `upload_media` endpoint (`InternalBroadcastsUploadMediaEndpoint`) and its storage layout.
- `S3MediaProxyView`.
- Any change in Courier or Mailroom.
- Any authentication or permission change on the in-scope endpoints.
- `GET` on the public endpoint, other than reading broadcasts created through the new variant.

**Pre-existing issues, listed here and NOT fixed by this change**:

- `InternalWhatsappBroadcastsEndpoint` composes `IsAuthenticated` in `permission_classes`, which Principle XVII forbids. It needs its own change.
- Flows `S3_MEDIA_BUCKETS` may contain a typo: `push-sp-push-attachments-prod` versus `push-ilha-sp-push-attachments-prod`.
- The `weni-production-retail` bucket is not among the buckets Courier signs.

## Binding Decisions

These were validated before this spec and are not reopened here.

1. JSON requests keep working exactly as today.
2. A new `multipart/form-data` variant: field `payload` holds the current JSON body as a string; field `files` holds one or more files. Uploaded files are appended to `msg.attachments` in the order received, after any URLs already in `payload.msg.attachments`. Order matters: a template header uses `attachments[0]`, and carousel card N uses `attachments[N]`.
3. Files go to the existing Flows private bucket (`private_file_storage`, `AWS_STORAGE_BUCKET_NAME`) under `attachments/<org_id>/broadcasts/<sha256>.<ext>`. `msg.attachments` receives the canonical unsigned URL `<mime>:<STORAGE_URL>/<key>`. Flows MUST NOT presign: Courier presigns every attachment right before each send attempt ([weni-ai/courier#243](https://github.com/weni-ai/courier/pull/243)). Verified in production (sa-east-1): Courier's signed buckets include the Flows bucket, `STORAGE_URL` carries the region in its host, and Courier can read the bucket.
4. Content-addressed deduplication: the same content for the same org is uploaded once. A Redis entry (org + sha256 → URL) lets later requests skip the upload, because campaigns resend the same image across many calls (at most 1000 recipients per call).
5. Boundary validation: the real type is detected from the file bytes, not from the client content type; WhatsApp limits apply per type; at most 10 files. An invalid `payload` or an invalid file returns `400` with field errors, uploads nothing, and creates no broadcast.
6. Internal endpoint idempotency (`Idempotency-Key` header): the body hash covers the payload plus the sha256 of each file; the lookup happens before any upload; a storage failure releases the key.
7. A storage failure (S3 or Redis) returns `503` with a generic error and no stack trace. S3 and Redis calls have explicit timeouts.

## Contract

### Request variants

Both in-scope endpoints accept two request shapes on `POST`.

**JSON (unchanged)**: `Content-Type: application/json`, body as documented today. Nothing about this shape changes: fields, validation, errors, status codes, response body, throttling, and idempotency.

**Multipart (new)**: `Content-Type: multipart/form-data` with exactly these fields:

| Field | Occurrences | Content |
|---|---|---|
| `payload` | exactly 1 | A string holding a JSON object with the same fields and rules as the JSON body. |
| `files` | 0 to 10 | One file per occurrence. Order of occurrence is the attachment order. |

Example:

```
POST /api/v2/whatsapp_broadcasts.json
Content-Type: multipart/form-data; boundary=----X

------X
Content-Disposition: form-data; name="payload"

{"groups": ["<group uuid>"], "msg": {"text": "Black Friday", "attachments": ["image/png:https://example.com/a.png"]}}
------X
Content-Disposition: form-data; name="files"; filename="promo.jpg"
Content-Type: image/jpeg

<bytes>
------X--
```

The broadcast is created with `msg.attachments` equal to:

```
["image/png:https://example.com/a.png",
 "image/jpeg:<STORAGE_URL>/attachments/<org_id>/broadcasts/<sha256 of promo.jpg>.jpg"]
```

### Allowed file types and size limits

The type is detected from the file bytes. The client's declared content type and file name are not used to decide the type, the extension, or the stored key.

| Category | Allowed detected types | Maximum size per file |
|---|---|---|
| Image | `image/jpeg`, `image/png` | 5 MB |
| Video | `video/mp4`, `video/3gpp` | 16 MB |
| Audio | WhatsApp-supported audio types (see Assumptions) | 16 MB |
| Document | WhatsApp-supported document types (see Assumptions) | 100 MB |
| Sticker | `image/webp` | 500 KB (see Assumptions) |

The total size of all files in one multipart request MUST NOT exceed 100 MB, the largest single-file limit, so one maximum-size document still fits. A request over the cap returns `400` and uploads nothing.

### Responses

| Status | When | Body |
|---|---|---|
| `201` | Broadcast created. | Same body as the JSON variant today (`WhatsappBroadcastReadSerializer`). `metadata.attachments` holds the unsigned canonical URLs. |
| `400` | Missing, duplicated, or non-JSON-object `payload`; a payload that fails today's validation; an unknown form field; an empty, disallowed, or oversize file; more than 10 files; files totalling more than 100 MB. | Field errors keyed by `payload` or `files`. A file error identifies the file by its zero-based position in `files`, not by its file name. |
| `409` | Internal endpoint only: `Idempotency-Key` reused with a different body hash, or a request with the same key still in flight. | Same bodies as today. |
| `503` | Storage failure (S3 upload or the deduplication cache) while handling the files. | A generic error, for example `{"error": "Media storage temporarily unavailable"}`, with no stack trace or internal detail. |

Every other status (authentication, permission, project resolution, throttling) is produced exactly as today, for both variants.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Send a broadcast with an image in a single request (Priority: P1)

A customer running a promotion sends a WhatsApp broadcast to a contact group with an image header, attaching the image file directly to the broadcast request. They no longer need a public link to the image, and they do not make a separate upload request first.

**Why this priority**: This is the problem the change solves. Without it, customers cannot reliably send images in broadcasts now that the buckets are private.

**Independent Test**: Post a multipart request with a valid payload and one JPEG to the public endpoint with an API Key, and check that the broadcast is created with the stored, unsigned URL of the image as its last attachment.

**Acceptance Scenarios**:

1. **Given** an API Key of an org and a valid payload targeting a group, **When** the customer posts it as multipart with one JPEG under `files`, **Then** the response is `201` and the broadcast `metadata.attachments` ends with `image/jpeg:<STORAGE_URL>/attachments/<org_id>/broadcasts/<sha256>.jpg` with no `X-Amz-*` parameter.
2. **Given** the same file declared by the client as `application/octet-stream` with the name `photo.bin`, **When** it is posted, **Then** the stored attachment uses the detected type `image/jpeg` and the extension `.jpg`.
3. **Given** a payload with a template that has an image header and no attachment URLs, **When** it is posted with one PNG, **Then** that PNG is `attachments[0]`.
4. **Given** a JSON request identical to what customers send today, **When** it is posted, **Then** the response and the stored broadcast are exactly as today.

---

### User Story 2 - Several files and existing URLs keep their order (Priority: P1)

A customer sends a carousel broadcast where some cards use media URLs they already have and others use files attached to the request. Each card must get the media at its own position.

**Why this priority**: Template headers and carousel cards pick media by position; a wrong order sends the wrong image to every recipient.

**Independent Test**: Post a payload with two attachment URLs and three files, and check that the stored attachments are the two URLs followed by the three files in the order sent.

**Acceptance Scenarios**:

1. **Given** `payload.msg.attachments` with URLs U1 and U2 and files F1, F2, F3 in that order, **When** the request is posted, **Then** the stored attachments are `[U1, U2, F1, F2, F3]`.
2. **Given** the same content sent as F1 and as F3 in one request, **When** it is posted, **Then** both positions hold the same canonical URL and the content is uploaded at most once.

---

### User Story 3 - A campaign resends the same image without re-uploading (Priority: P1)

A campaign of 100,000 contacts is sent as 100 calls of 1,000 recipients, each carrying the same image file. Only the first call stores the image; the others reuse it.

**Why this priority**: Lowest added latency is the top criterion, and repeated campaign calls are the dominant production pattern.

**Independent Test**: Post the same file twice for the same org and check that the storage upload happens only on the first request and both broadcasts reference the same URL.

**Acceptance Scenarios**:

1. **Given** a file already stored for org A by an earlier request, **When** org A posts the same file again, **Then** no upload happens and the broadcast references the same canonical URL.
2. **Given** a file already stored for org A, **When** org B posts the same file, **Then** it is uploaded under org B's prefix and org B's broadcast references org B's URL.

---

### User Story 4 - Internal callers keep safe retries (Priority: P2)

A Weni service creates broadcasts through the internal endpoint with an `Idempotency-Key` and retries on timeouts. Retrying with the same payload and file must not create a second broadcast, and reusing a key with a different file must be rejected.

**Why this priority**: Idempotency already protects internal callers against double sends and double billing; the multipart variant must not weaken it.

**Independent Test**: Post a multipart request with an `Idempotency-Key`, post it again with the same key and content, then with the same key and different file content.

**Acceptance Scenarios**:

1. **Given** a completed multipart request with key K, **When** the same payload and file are posted with K, **Then** the stored response is replayed, no broadcast is created, and nothing is uploaded.
2. **Given** a completed multipart request with key K, **When** the same payload with a different file is posted with K, **Then** the response is `409` and nothing is uploaded.
3. **Given** a multipart request with key K whose upload fails, **When** it returns `503`, **Then** K is released and a retry with K is processed normally.

---

### User Story 5 - Invalid input and storage outages fail cleanly (Priority: P2)

A caller sends a broken request or the storage is down. The caller gets a clear, predictable error, and nothing half-done is left behind.

**Why this priority**: Prevents broadcasts going out without their media, and keeps untrusted files out of the bucket.

**Independent Test**: Post each invalid shape and check `400` with no upload and no broadcast; simulate an S3 failure and a cache failure and check `503` with no broadcast.

**Acceptance Scenarios**:

1. **Given** a multipart request without `payload`, with a `payload` that is not a JSON object, or with a `payload` that fails today's validation, **When** it is posted, **Then** the response is `400` with a `payload` error, nothing is uploaded, and no broadcast exists.
2. **Given** a file whose bytes are a GIF, an HTML page, or an executable, **When** it is posted, **Then** the response is `400` with an error on that file's position.
3. **Given** a 6 MB JPEG, a 17 MB MP4, or 11 files, **When** it is posted, **Then** the response is `400`, nothing is uploaded, and no broadcast exists.
4. **Given** S3 rejects or times out on the upload, **When** the request is posted, **Then** the response is `503` with a generic body and no stack trace, and no broadcast exists.

### Edge Cases

- A multipart request with a valid `payload` and no `files` behaves like the equivalent JSON request.
- A form field other than `payload` and `files` (for example a singular `file`) returns `400`, so a misnamed field never silently sends a broadcast without its media.
- A zero-byte file returns `400`.
- A client content type or file extension that disagrees with the bytes is ignored; the detected type decides. If the detected type is not allowed, the file is rejected even when the declared type is allowed.
- An MP4 container that holds only audio is classified as audio, not video, so the media goes out with the right WhatsApp type.
- Two concurrent requests with the same new file for the same org may both upload it. Both writes target the same key with identical bytes, so the result is the same object and the same URL.
- A cache entry that has expired, or that was never written, leads to one more upload of identical bytes to the same key; the URL is unchanged.
- An error raised while creating the broadcast after the upload (for example the existing trigger group failures) leaves the uploaded object in the bucket. It is content-addressed and reused by the next request with the same content, so it is not cleaned up.
- WhatsApp recipients of a document see the stored file name `<sha256>.<ext>`, not the original file name, because the key format is binding.
- Courier presigns the URL at each send attempt, so a broadcast queued for hours still sends a valid link.
- The `201` response and later `GET` results contain the unsigned canonical URL, exactly as for URLs sent in JSON today.
- On the internal endpoint, a multipart request resolves the project from the JWT or from `project` / `project_uuid` inside `payload`, with the same mismatch rules as today; the multipart form itself carries no project field.

## Requirements *(mandatory)*

### Functional Requirements

**Request shapes**

- **FR-001**: Both in-scope endpoints MUST keep accepting JSON requests with no change in validation, response, status codes, throttling, or idempotency.
- **FR-002**: Both endpoints MUST accept `multipart/form-data` requests with exactly one `payload` field holding a JSON object, and zero to 10 `files` fields.
- **FR-003**: The fields of the parsed `payload` MUST be validated by the same rules as the JSON body, and MUST be used for project and user resolution on the internal endpoint as the JSON body is today.
- **FR-004**: A multipart request MUST be rejected with `400` when `payload` is missing, appears more than once, is not valid JSON, or is not a JSON object, and when the form contains any field other than `payload` and `files`.

**Attachments**

- **FR-005**: The canonical URL of each file MUST be appended to `msg.attachments` in the order the files were received, after every entry already in `payload.msg.attachments`.
- **FR-006**: Each appended entry MUST be `<detected mime>:<STORAGE_URL>/attachments/<org_id>/broadcasts/<sha256>.<ext>`, where `<sha256>` is the lowercase hex SHA-256 of the file bytes and `<ext>` is derived from the detected type.
- **FR-007**: Flows MUST NOT presign the appended URLs; no appended URL may contain a query string.
- **FR-008**: Files MUST be stored in the Flows private bucket (`AWS_STORAGE_BUCKET_NAME`, through `private_file_storage`) at the key in FR-006, with the detected type as the object content type.
- **FR-009**: The original file name and the client-declared content type MUST NOT be used for the type, extension, or key, and MUST NOT be stored or logged.

**Validation**

- **FR-010**: The type of each file MUST be detected from its bytes. A file whose detected type is not in the allowed table MUST be rejected with `400`.
- **FR-011**: A file larger than its category's limit, a zero-byte file, more than 10 files, or files totalling more than 100 MB MUST be rejected with `400`.
- **FR-012**: The whole request MUST be validated before any upload: payload shape, today's payload rules (with the canonical URLs of the files already in place, since they are computed from the bytes), file count, types, and sizes. A request rejected with `400` at this stage MUST NOT upload anything and MUST NOT create a broadcast.
- **FR-013**: A `400` MUST report errors keyed by `payload` or `files`, identifying a file by its zero-based position.

**Deduplication**

- **FR-014**: Before uploading, the system MUST check a shared cache entry keyed by org and sha256. On a hit, it MUST skip the upload and reuse the URL. On a miss, it MUST upload and then record the entry.
- **FR-015**: Cache entries MUST be scoped per org, so one org's request never reveals or reuses content stored for another org.
- **FR-016**: Cache entries MUST expire after `BROADCAST_MEDIA_DEDUP_TTL_SECONDS` (7 days: `7 * 24 * 60 * 60`), the named time to live set in the plan.
- **FR-017**: Identical content appearing more than once in one request MUST be uploaded at most once.

**Idempotency (internal endpoint)**

- **FR-018**: When `Idempotency-Key` is present on a multipart request, the body hash MUST cover the parsed payload and the ordered list of file sha256 values. Reordering the files or changing any file's bytes MUST produce a different hash.
- **FR-019**: The idempotency lookup MUST happen before any upload. A replay (`hit`) MUST return the stored response, and a conflict or in-flight state MUST return `409`, all without uploading.
- **FR-020**: Every non-success path after the key is claimed, including `400` and `503`, MUST release the key, as the JSON variant already does for its failures.

**Failure handling**

- **FR-021**: An S3 failure or a deduplication cache failure while handling files MUST return `503` with a generic body, MUST NOT create a broadcast, and MUST NOT return a stack trace or internal detail.
- **FR-022**: S3 and cache calls made by this feature MUST have explicit, named timeouts. Connect timeout, read timeout, and `S3_UPLOAD_MAX_RETRY_ATTEMPTS` (2, botocore standard mode: exponential backoff with jitter) bound each S3 HTTP call, not the whole multipart upload. The content-addressed write is idempotent. Redis dedup calls MUST NOT be retried. `save()` MUST run on the request thread. Inside one `try`, before `save()` is called, a `threading.Timer` of `S3_UPLOAD_CALL_BUDGET_SECONDS` MUST be started to set a `threading.Event`, and a botocore `before-send` handler MUST be registered on that storage client's event system. The handler MUST raise `ReadTimeoutError` when the event is set. The handler MUST be unregistered and the timer cancelled in the `finally` of that same `try`. The storage client is cached per process, so a handler left registered would abort a later request. The request MUST NOT finish, and the spooled temp file MUST NOT be deleted, until `save()` has returned or raised. No upload work outlives the request. `before-send` fires only before the next HTTP call is sent. An attempt that has already passed it still runs until its connect timeout and read timeout (`S3_UPLOAD_CONNECT_TIMEOUT_SECONDS` + `S3_UPLOAD_READ_TIMEOUT_SECONDS`, 35 seconds) and is not stopped because the call budget elapsed. Before each `save()`, if the time already spent plus `S3_UPLOAD_CALL_BUDGET_SECONDS` plus those 35 seconds would reach `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS` (120, the gunicorn worker timeout), the request MUST take the `503` storage path and MUST NOT start that upload. A `save()` that is allowed to start therefore returns before the worker is killed. Exhausted HTTP retries, a `before-send` raise, and a refused start all surface as that `503`.
- **FR-023**: A storage failure MUST be reported to Sentry with the tags `org_id`, `project_uuid`, `user_id`, `correlation_id`, and `media_stage`. These endpoints have no account entity beyond the project, so `project_uuid` is the account identifier. The report MUST NOT include a file name, file bytes, an object key, a URL, or other personal data.
- **FR-024**: Error handling of JSON requests, including failures of the idempotency store, MUST stay as today; the `503` mapping applies only to the media storage path.

**Unchanged surfaces**

- **FR-025**: Authentication, permissions, and project resolution of both endpoints MUST stay as today. `WhatsappBroadcastsEndpoint` MUST keep its `v2.broadcasts` throttle, and multipart requests MUST count against that same throttle. `InternalWhatsappBroadcastsEndpoint` MUST keep `throttle_classes = []`. This change MUST NOT set or clear `throttle_scope` or `throttle_classes` on either endpoint.
- **FR-026**: The JSON contract of `WhatsappBroadcastWriteSerializer` MUST NOT change, so the FastAPI bridge keeps working unmodified.
- **FR-027**: The public endpoint documentation (docstring and API explorer) MUST describe the multipart variant, the allowed types, and the limits.

### Key Entities

- **Broadcast**: the existing WhatsApp broadcast; its `metadata` holds `msg`, whose `attachments` list now may include stored media URLs.
- **Stored media object**: a file in the Flows private bucket, identified by org and the SHA-256 of its bytes, with the detected content type.
- **Deduplication entry**: a short-lived shared cache record mapping (org, sha256) to the canonical attachment URL.
- **Idempotency record** (internal endpoint): the existing record keyed by project and `Idempotency-Key`, whose body hash now also covers the file hashes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A customer sends a broadcast with media in exactly one request, with no prior upload call and no public link.
- **SC-002**: In a campaign that resends the same file across N calls for one org, the file is stored once; the other N−1 calls perform no upload.
- **SC-003**: For a file already stored, a multipart request's 95th-percentile response time is within 10% of the equivalent JSON request plus the time to receive the file bytes. The gate for this change is one staging sample, not a percentile harness: the repeated multipart call's time is within 10% of a JSON call to the same group plus the time to receive the file.
- **SC-004**: 100% of rejected inputs (invalid payload, disallowed type, oversize, too many files) return `400`, and 0 of them leave an object in the bucket or create a broadcast.
- **SC-005**: 100% of media delivered through this variant reaches recipients through Courier's per-send signing, with no URL stored by Flows ever containing a signature.
- **SC-006**: 0 changes are needed by existing JSON callers, including the FastAPI bridge.

## Peak Load

- **Ceiling**: on `WhatsappBroadcastsEndpoint` only, the `v2.broadcasts` throttle, 36,000 requests per hour per throttle identity (10 requests per second), applies to JSON and multipart (FR-025).
- **Internal endpoint**: `InternalWhatsappBroadcastsEndpoint` stays unthrottled (`throttle_classes = []`). Its declared planning peak is the campaign pattern: 100 sequential calls for one org, each carrying one image, with the upload on the first call and cache hits after that.
- **Current production usage**: one org sends about 30,000 attachments per month from the Flows bucket, about 1,000 per day.
- **Declared planning peak (public)**: 10 multipart requests per second for one throttle identity, each carrying one image of up to 5 MB (the campaign pattern), which is up to 50 MB per second of inbound file data. With deduplication, only the first request of a campaign uploads; the rest add only hashing and one cache lookup per file.
- **Worst case per request**: 100 MB of files (the total cap), which at the public throttle ceiling bounds one throttle identity at 1 GB per second of inbound file data. This is a theoretical ceiling; the production pattern is the planning peak above.
- **Statelessness**: files larger than the in-memory threshold are spooled to a per-request temporary file. `save()` runs on the request thread. The call-budget timer and the `before-send` handler are armed before `save()` and cleared in the same `finally`. An attempt already on the wire ends at its connect and read timeouts, and a new `save()` is refused when elapsed time plus the 60 second budget plus those 35 seconds would reach the 120 second worker timeout. The request ends only after `save()` has returned and the temp file can be deleted. Nothing outlives the request except the S3 object and the shared cache entry (Principle XII).

## Test Strategy

Tests use `TembaTest`. Public endpoint tests sit next to `test_whatsapp_broadcasts` in `temba/api/v2/tests.py`; internal endpoint tests sit next to `TestInternalWhatsappBroadcast`, `TestInternalWhatsappBroadcastJWT`, and `TestInternalWhatsappBroadcastIdempotency` in `temba/api/v2/internals/broadcasts/tests.py`. Storage is stubbed at the boundary (`private_file_storage` save and the cache client); `queue_broadcast` is patched as in the neighboring tests. Run with `poetry run coverage run manage.py test temba.api`.

| Acceptance criterion | Test (flow from request to stored broadcast) |
|---|---|
| AC-1 | Existing JSON tests on both endpoints stay green without modification. A new test on each endpoint posts a JSON body and asserts that `WhatsappBroadcastWriteSerializer` is used, the `201` body and `metadata` match today's JSON behavior, and storage save is not called. On the internal endpoint the test also asserts the view calls `compute_body_hash`. |
| AC-2 | Multipart with one JPEG on each endpoint: `201`; `metadata.attachments[-1]` equals `image/jpeg:<STORAGE_URL>/attachments/<org_id>/broadcasts/<sha256>.jpg`; it contains no `X-Amz-`; the storage save was called with that key. A variant with a wrong client content type and file name asserts the detected type and extension. |
| AC-3 | Payload with two URLs plus three distinct files: stored attachments are the two URLs followed by the three files in order. A duplicated file in one request is saved once. |
| AC-4 | The same file posted twice for one org: storage save called once; both broadcasts reference the same URL. The same file for another org is saved under that org's prefix. |
| AC-5 | Missing `payload`, duplicated `payload`, non-JSON `payload`, JSON array `payload`, payload failing today's rules, unknown form field, zero-byte file, GIF, HTML, `allo.wav`, 6 MB JPEG, 17 MB MP4, one document over its category limit, 11 files, and files totalling over 100 MB: each returns `400` with the expected field key; storage save not called; no broadcast exists. On the internal endpoint no idempotency key is written. |
| AC-6 | Storage save raises a client error and, separately, a timeout: `503` with the generic body; no traceback in the response; no broadcast exists; on the internal endpoint the idempotency key is absent from the cache afterwards. On both endpoints the Sentry scope has `org_id`, `project_uuid`, `user_id`, `correlation_id`, and `media_stage`, and the event has no file name, bytes, key, or URL. |
| AC-7 | Internal: multipart with key K, then the same content with K replays the stored response with no save and no new broadcast; the same payload with different file bytes, and with the same files reordered, returns `409` with no save. |
| AC-8 | Public endpoint with API Key and with JWT; internal endpoint with OIDC and with JWT (project from the token, and from `payload` for OIDC). Each returns `201` with the stored attachment. Unauthenticated requests are rejected as today. |
| AC-9 | The cache lookup raises a connection error, and separately the cache write raises after a successful save: `503`, no broadcast, internal key released. On both endpoints the Sentry scope has the same five tags as AC-6, with no file name, bytes, key, or URL. |
| AC-10 | Existing tests in `temba/fastapi_app/tests.py` stay unmodified and green. A new test in `temba/api/v2/internals/broadcasts/tests.py` asserts that `post_internal_whatsapp_broadcast` still depends on `verify_jwt`, still constructs `WhatsappBroadcastWriteSerializer` with the JSON body, and that `temba/fastapi_app/broadcasts.py` does not reference `WhatsappBroadcastWithMediaWriteSerializer` or `BroadcastMultiPartParser`. |

Failure paths covered: every `400` shape in AC-5, S3 error and timeout, cache error on read and on write, idempotency conflict and in-flight, project mismatch inside `payload` on the internal endpoint. Unit tests cover type detection and the size table for each category, including audio in an MP4 container.

## Constitution Alignment

- **I. Version Control and Review**: Delivered through a pull request from `019-broadcast-inline-media` with review and green `.github/workflows/ci.yml`.
- **II. Security and Secrets**: No new secret. Files are written only to the existing private bucket with the existing credentials. Any new dependency for type detection (python-magic is already declared) MUST be named in the plan.
- **III. Observability**: Logs carry the org identifier and the correlation identifier; no file name, bytes, or URL is logged.
- **IV. Versioned Contracts**: Additive, backward compatible change to a public DRF endpoint: a new request variant, with JSON unchanged (FR-001). Released as a Flows MINOR version. No Courier or Mailroom version change: Courier already presigns the Flows bucket (courier#243).
- **V. Specification Traceability**: Engineering origin; opens with `## Origin Without Product Spec`; every acceptance criterion maps to a test above.
- **VI. No Silent Divergence**: Not applicable, no product spec.
- **VII. Commit Messages**: Conventional Commits, atomic.
- **VIII. Changelog Maintenance**: A `feat:` bullet in `WENI-CHANGELOG.md` under the shipping version, describing multipart media on both broadcast endpoints.
- **IX. Never Trust the Client**: Type detected from bytes, per-type size limits, file count, payload shape and rules validated at the boundary before any side effect (FR-010 to FR-013). Authorization unchanged and server-side.
- **X. Fail Gracefully and Predictably**: Explicit named timeouts on each S3 HTTP call and on Redis. Before `save()`, a named call budget arms a botocore `before-send` handler that raises `ReadTimeoutError` on the next send. An attempt already on the wire is bounded by the connect and read timeouts. A new `save()` is refused when elapsed time plus the budget plus one in-flight attempt would reach the 120 second worker timeout. Both return `503`. The handler is removed in the same `finally` as the timer is cancelled. The spooled file is deleted only after `save()` has returned or raised. Invalid input returns `400` with field errors (FR-021, FR-022).
- **XI. Bounded Retry Over REST**: Each S3 HTTP call retries with botocore standard mode (exponential backoff with jitter), at most `S3_UPLOAD_MAX_RETRY_ATTEMPTS` (2), on an idempotent content-addressed PUT. Redis is not retried. Exhausted retries, a `before-send` abort, and a refused start return `503`, which the caller can retry safely (the internal key is released).
- **XII. Scalability and Peak Load**: Stateless; shared state only in S3 and Redis. The upload does not continue after the request returns. The public throttle ceiling and the internal campaign peak are declared above.
- **XIII. Diagnosable Errors**: Storage failures are reported to Sentry with `org_id`, `project_uuid` (the account identifier), `user_id`, `correlation_id`, and `media_stage`. No file name, bytes, key, URL, or other personal data (FR-023).
- **XIV. Tests Exercise Flows**: End-to-end request tests on both endpoints for success and every failure path.
- **XV. Explicit Over Clever**: File count, per-type size limits, total size, multipart overhead, cache time to live, S3 and Redis timeouts, the S3 attempt count, the per-save call budget, the worker timeout, and the MP4 box-walk cap are named constants.
- **XVI. Contained Changes**: Only the two endpoints, the shared media storage helper they use, their tests, documentation, and changelog. The FastAPI bridge, the `upload_media` endpoint, and the pre-existing issues listed in Scope are not touched.
- **XVII. Explicit, Scoped Authorization**: No permission change. The `IsAuthenticated` composition on the internal endpoint is a pre-existing violation, listed in Scope and left for its own change.

## Assumptions

- Audio types are the ones WhatsApp Cloud API documents: `audio/aac`, `audio/amr`, `audio/mpeg`, `audio/mp4`, and `audio/ogg` (Opus).
- Document types are the ones WhatsApp documents: `text/plain`, `application/pdf`, Microsoft Word, Excel, and PowerPoint (legacy and Office Open XML formats).
- The sticker limit is 500 KB, the WhatsApp limit for animated stickers; static stickers over 100 KB may still be rejected by WhatsApp at send time, which Flows does not check.
- MB means 1,048,576 bytes.
- Codec checks (for example H.264 and AAC for video) are out of scope; WhatsApp rejects unsupported codecs at send time, as it does for URL attachments today.
- No lifecycle rule deletes `attachments/<org_id>/broadcasts/` objects within the cache time to live; if one exists, the time to live is set below it in the plan.
- The `201` body of the multipart variant is identical in shape to the JSON variant.
- The ingress in front of Flows accepts request bodies of at least 100 MB plus the payload; the plan confirms this for each production deployment.
