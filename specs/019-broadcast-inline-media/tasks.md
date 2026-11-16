# Tasks: Inline media files in WhatsApp broadcast requests

**Input**: `/specs/019-broadcast-inline-media/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Tests**: Requested. In every slice, the test task comes before its implementation task and fails until the implementation lands.

**Commits**: One task = one commit, Conventional Commits, at most 50 characters (shown as `Commit:`). Tasks without a commit say so.

**Gates for every task**: `./code_check.py` is clean, the task's tests run, no `# pragma: no cover`, no change outside the spec scope (FastAPI bridge, `upload_media`, `S3MediaProxyView`, permissions and global settings stay untouched).

## Format: `[ID] [P?] [Story] Description`

Stories (from spec.md): US1 single image, US2 order, US3 dedup, US4 internal idempotency, US5 invalid input and outages. `[P]` = a separate test class that can be written before its implementation task. Tasks that edit the same file are sequential.

Fixtures: `media/test_media/steve.marten.jpg`, `snow.mp4`, `allo.wav`. `snow.m4a` is a byte-identical copy of `snow.mp4` and still has a video track, so the audio-only file is `audio_only_mp4_bytes()` in `temba/tests/media.py`, which drops the video track of `snow.mp4` in memory and keeps its `ftyp` box. Wherever a task below says "m4a" it means that file. S3 is stubbed only at `private_file_storage.save`; Redis is real.

---

## Phase 1: Setup

- [X] T001 Add `libmagic1` to `RUNTIME_DEPS` in `docker/Dockerfile` and to the `apt install` line in `.github/workflows/ci.yml`. Commit: `chore: install libmagic1 in image and CI`

---

## Phase 2: Shared use case (blocks every endpoint task)

**Goal**: `temba/msgs/usecases/broadcast_media.py` and the storage helper work in isolation (research R1 to R6, R10; data-model.md).

**Independent test**: `poetry run coverage run manage.py test temba.msgs.usecases temba.utils.s3`

- [X] T002 [P] Test `media_upload_storage()` in `temba/utils/s3/tests.py`: under an S3 `DEFAULT_FILE_STORAGE` it sets connect and read timeouts, retry mode `standard`, `max_attempts == 2`, `file_overwrite=True`, and makes no network call; under filesystem storage it returns `private_file_storage`. Commit: `test: cover media upload storage timeouts`
- [X] T003 Implement `media_upload_storage()` in `temba/utils/s3/s3.py` with `S3_UPLOAD_CONNECT_TIMEOUT_SECONDS = 5`, `S3_UPLOAD_READ_TIMEOUT_SECONDS = 30`, and `S3_UPLOAD_MAX_RETRY_ATTEMPTS = 2`, merging `retries={"mode": "standard", "max_attempts": S3_UPLOAD_MAX_RETRY_ATTEMPTS}` into `client_config`. Standard mode is exponential backoff with jitter. Commit: `feat: add timeout-bound media upload storage`
- [X] T004 [P] Test type detection and limits in new `temba/msgs/usecases/tests/test_broadcast_media.py`: each allowed type from the data-model table via fixtures or minimal headers, `LIBMAGIC_MIME_ALIASES`, GIF/HTML/WAV rejected, limit and limit+1 per category, extension from the detected type and not the client name. Commit: `test: cover broadcast media type and limits`
- [X] T005 Implement the named constants, including `MP4_MAX_BOXES_PER_LEVEL = 64`, `ALLOWED_BROADCAST_MEDIA`, `LIBMAGIC_MIME_ALIASES` and `detect_media_type()` (lazy `import magic`) in new `temba/msgs/usecases/broadcast_media.py`. Commit: `feat: detect broadcast media type from bytes`
- [X] T006 [P] Test audio-only ISO BMFF classified as `audio/mp4` (`audio_only_mp4_bytes()`, since `snow.m4a` still has video), `snow.mp4` stays `video/mp4`, and a level with 65 boxes stops at `MP4_MAX_BOXES_PER_LEVEL` (64) and keeps libmagic's type, in `temba/msgs/usecases/tests/test_broadcast_media.py`. Commit: `test: cover audio-only MP4 detection`
- [X] T007 Implement the bounded box-header walk (`moov` → `trak` → `mdia` → `hdlr`) in `temba/msgs/usecases/broadcast_media.py`. Hitting `MP4_MAX_BOXES_PER_LEVEL` leaves libmagic's type unchanged. Commit: `feat: classify audio-only MP4 as audio`
- [X] T008 [P] Test `read_broadcast_request` and `with_attachments` in `temba/msgs/usecases/tests/test_broadcast_media.py`: JSON passthrough untouched; missing, duplicated, non-JSON and array `payload`; unknown field; empty file; more than 10 files; total over 100 MiB; all errors collected at once with positions as keys; sha256 equals `hashlib` of the fixture; canonical URL format; attachments appended after existing URLs in order; missing or non-list `msg.attachments`. Commit: `test: cover broadcast request preparation`
- [X] T009 Implement `InlineMedia`, `PreparedBroadcastRequest`, `BroadcastMediaInvalid` and `read_broadcast_request` (one chunked pass for hash and sniff) in `temba/msgs/usecases/broadcast_media.py`; export public names in `temba/msgs/usecases/__init__.py`. Commit: `feat: prepare broadcast request with files`
- [X] T010 [P] Test `store_broadcast_media` in `temba/msgs/usecases/tests/test_broadcast_media.py`: miss uploads with key and `content_type` then records the entry with `SET` expiry equal to `BROADCAST_MEDIA_DEDUP_TTL_SECONDS` (`7 * 24 * 60 * 60`); hit skips upload; stored value that differs counts as a miss; the same hash twice in one call uploads once; another org uploads again; `ClientError`, `S3UploadFailedError`, read timeout, `OSError` and Redis `get`/`set` errors raise `BroadcastMediaUnavailable` once with the right stage. `_dedup_redis()` uses `socket_timeout` and `socket_connect_timeout` equal to `BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS` (2) and sets no retry. A fake clock where elapsed time plus `S3_UPLOAD_CALL_BUDGET_SECONDS` plus `S3_UPLOAD_CONNECT_TIMEOUT_SECONDS` plus `S3_UPLOAD_READ_TIMEOUT_SECONDS` reaches `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS` (120) makes the next file skip `save` and raise `BroadcastMediaUnavailable("upload")`. The storage double exposes `client.meta.events`. `save()` performs two sends. The first send is already past `before-send` when the call-budget event is set, and that attempt returns on its own. The second send's `before-send` raises `botocore.exceptions.ReadTimeoutError`. The next file is not started, the handler is no longer registered, and `store_broadcast_media` raises `BroadcastMediaUnavailable("upload")`. Commit: `test: cover broadcast media storage dedup`
- [X] T011 Implement `store_broadcast_media`, `BroadcastMediaUnavailable`, `BROADCAST_MEDIA_DEDUP_TTL_SECONDS = 7 * 24 * 60 * 60`, `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS = 120`, and `S3_UPLOAD_CALL_BUDGET_SECONDS = 60` in `temba/msgs/usecases/broadcast_media.py`, plus the cached `_dedup_redis()`. The client uses `socket_timeout=BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS` and `socket_connect_timeout=BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS` and sets no retry. Before each `save()`, if elapsed time plus `S3_UPLOAD_CALL_BUDGET_SECONDS` plus `S3_UPLOAD_CONNECT_TIMEOUT_SECONDS` plus `S3_UPLOAD_READ_TIMEOUT_SECONDS` would reach `BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS`, raise `BroadcastMediaUnavailable("upload")` and do not call S3. Otherwise, on the request thread and inside one `try`, start a `threading.Timer` of `S3_UPLOAD_CALL_BUDGET_SECONDS` that sets a `threading.Event`. When the storage exposes a botocore client, register a `before-send` handler on `client.meta.events` that raises `botocore.exceptions.ReadTimeoutError` when the event is set. Then call `save()`. Unregister that handler and cancel the timer in the `finally` of that same `try`. `before-send` does not stop an attempt that has already passed it; that attempt still ends at the connect and read timeouts. A handler raise or a storage error becomes `BroadcastMediaUnavailable("upload")` and does not start another file. The spooled temp file stays open until `save()` has returned or raised. Commit: `feat: store broadcast media with dedup`

**Checkpoint**: the use case passes in isolation; no endpoint behavior has changed.

---

## Phase 3: Public endpoint `POST /api/v2/whatsapp_broadcasts.json` (US1, US2, US3, US5)

**Goal**: AC-1 to AC-6, AC-8 (public), AC-9 on `WhatsappBroadcastsEndpoint`, with `WriteAPIMixin.post` and `write_with_transaction = False` unchanged.

**Independent test**: `poetry run coverage run manage.py test temba.api.v2.tests` (new test classes next to `test_whatsapp_broadcasts`).

- [X] T012 [P] Test the API glue in `temba/api/v2/tests.py`: `Content-Length` above `MAX_BROADCAST_MULTIPART_BYTES` returns `400` on `files`; a `payload` part over `DATA_UPLOAD_MAX_MEMORY_SIZE` returns `400` on `payload`; `MediaStorageUnavailable` renders `503` with the generic `detail` and no traceback. Commit: `test: cover multipart parser size guards`
- [X] T013 Implement `BroadcastMultiPartParser`, `MediaStorageUnavailable`, `prepare_broadcast_request`, `report_media_storage_failure` and `correlation_identifier` in new `temba/api/v2/broadcast_media.py`. Define `MULTIPART_OVERHEAD_BYTES = 512 * 1024`, `MAX_BROADCAST_MULTIPART_BYTES = MAX_BROADCAST_FILES_TOTAL_BYTES + DATA_UPLOAD_MAX_MEMORY_SIZE + MULTIPART_OVERHEAD_BYTES`, and `MEDIA_STORAGE_UNAVAILABLE_MESSAGE = "Media storage temporarily unavailable"`. Sentry tags are `org_id`, `project_uuid`, `user_id`, `correlation_id`, and `media_stage`; call `scrub_events_for_current_request()`; logs carry no file name, key, URL, or payload. Commit: `feat: add multipart glue for broadcasts API`
- [X] T014 [P] [US1] Flow tests in `temba/api/v2/tests.py`: a JSON request uses `WhatsappBroadcastWriteSerializer`, the `201` body and `metadata` match today's JSON behavior, and `private_file_storage.save` is not called (AC-1); multipart with `steve.marten.jpg` returns `201`, `metadata["attachments"][-1]` is `image/jpeg:<STORAGE_URL>/attachments/<org_id>/broadcasts/<sha>.jpg` with no `X-Amz-`, `save` called with that key and `content_type == "image/jpeg"`; client type `application/octet-stream` and name `photo.bin` still stored as `image/jpeg`/`.jpg`; template header picks the file as `attachments[0]`; multipart with no files behaves like JSON (AC-2). Commit: `test: public broadcast with inline image`
- [X] T015 [P] [US1] Flow tests in `temba/api/v2/tests.py`: multipart accepted with API Key and with JWT carrying project claims, unauthenticated request rejected as today (AC-8, public). Commit: `test: public multipart auth variants`
- [X] T016 [P] [US2] Flow test in `temba/api/v2/tests.py`: two payload URLs plus jpg, mp4, m4a give `[U1, U2, jpeg, mp4, audio/mp4]`; the same file twice in one request gives equal entries and one `save` (AC-3). Commit: `test: public broadcast attachment order`
- [X] T017 [P] [US3] Flow tests in `temba/api/v2/tests.py`: the same file twice for one org calls `save` once and both broadcasts share the URL with a dedup entry present; another org uploads under its own prefix (AC-4). Commit: `test: public broadcast media dedup`
- [X] T018 [P] [US5] Flow tests in `temba/api/v2/tests.py`. `400` subTests, each asserting the `payload` or `files[<position>]` key, `save` not called, and `Broadcast` count unchanged: missing, duplicated, non-JSON, and array `payload`; payload failing today's rules nested under `payload`; unknown field; zero-byte file; GIF; HTML; `allo.wav`; 6 MB JPEG; 17 MB MP4; one document over `MAX_DOCUMENT_BYTES`; 11 files; files totalling over 100 MB (AC-5). `save` raising `ClientError`, `S3UploadFailedError`, and read timeout returns `503` with no broadcast (AC-6). Redis `get` and `set` failures return `503` with no broadcast (AC-9). S3 and Redis failures assert Sentry tags `org_id`, `project_uuid`, `user_id`, `correlation_id`, and `media_stage`, and no file name, bytes, key, or URL on the event. Commit: `test: public broadcast media failures`
- [X] T019 [US1] Add `WhatsappBroadcastWithMediaWriteSerializer` in `temba/api/v2/serializers.py`: nests errors under `payload`. `save()` runs `store_broadcast_media` and, on `BroadcastMediaUnavailable`, calls `report_media_storage_failure` before raising `MediaStorageUnavailable`, then returns `super().save()` only on success. Commit: `feat: add serializer for inline media`
- [X] T020 [US1] Wire `WhatsappBroadcastsEndpoint` in `temba/api/v2/views.py`: `parser_classes = (JSONParser, FormParser, BroadcastMultiPartParser)` and `get_write_serializer_class` override that returns the unchanged parent result for JSON and the new serializer for multipart. Do not set or clear `throttle_scope` or `throttle_classes`; `throttle_scope` stays `v2.broadcasts`. T014 to T018 pass. Commit: `feat: accept multipart on WhatsApp broadcasts`

**Checkpoint**: public multipart works end to end; MVP slice (US1).

---

## Phase 4: Internal endpoint `POST /api/v2/internals/whatsapp_broadcasts` with idempotency (US4, US2, US3, US5)

**Goal**: AC-1 to AC-9 on `InternalWhatsappBroadcastsEndpoint`; JSON hash and FastAPI bridge unchanged.

**Independent test**: `poetry run coverage run manage.py test temba.api.v2.internals.broadcasts temba.fastapi_app`

- [X] T021 [P] [US4] Test `compute_media_body_hash` in `temba/api/v2/internals/broadcasts/tests.py` (`TestIdempotencyHelpers`): key order independent, changes with file bytes, changes with file order, and JSON `compute_body_hash` output is unchanged. Commit: `test: cover media idempotency body hash`
- [X] T022 [US4] Implement `compute_media_body_hash(payload, file_sha256s)` in `temba/api/v2/internals/broadcasts/idempotency.py`. Commit: `feat: hash payload and files for idempotency`
- [X] T023 [P] [US1] Flow tests in `temba/api/v2/internals/broadcasts/tests.py`: a JSON request uses `WhatsappBroadcastWriteSerializer`, the `201` body and `metadata` match today's JSON behavior, `private_file_storage.save` is not called, and the view calls `compute_body_hash` (AC-1); multipart image returns `201`, `metadata["attachments"][-1]` is the canonical URL, and that URL has no `X-Amz-`, and `save` is called with `content_type == "image/jpeg"` (AC-2); two payload URLs plus jpg, mp4, and m4a are stored as `[U1, U2, image/jpeg, video/mp4, audio/mp4]`, and the same bytes sent twice produce equal entries and one `save` (AC-3); same file twice across requests uploads once (AC-4); OIDC user with `project` inside `payload`, and JWT with project claims, both `201`; `payload.project` mismatching the JWT returns `403` with no `save` (AC-8). Commit: `test: internal broadcast with inline media`
- [X] T024 [P] [US4] Flow tests (in the new `TestInternalWhatsappBroadcastMediaIdempotency`, so the existing idempotency tests keep their setup): same key and same content replays the stored response with no second `save` and one broadcast; same key with different bytes returns `409` with no `save`; same files reordered returns `409`; in-flight key returns `409`; key claimed before and released after a `503` so a retry returns `201` (AC-6, AC-7). Commit: `test: internal multipart idempotency`
- [X] T025 [P] [US5] Flow tests in `temba/api/v2/internals/broadcasts/tests.py`. The same `400` subTests as T018 each happen before any key is claimed (no idempotency key in Redis) and assert `save` not called and `Broadcast` count unchanged (AC-5). A `400` from serializer validation releases the key. S3 failure and Redis dedup failures return `503` with `{"error": ...}`, no broadcast, and the key released (AC-6, AC-9). Those `503`s assert Sentry tags `org_id`, `project_uuid`, `user_id`, `correlation_id`, and `media_stage`, and no file name, bytes, key, or URL on the event. Commit: `test: internal broadcast media failures`
- [X] T026 [US4] Wire `InternalWhatsappBroadcastsEndpoint.post` in `temba/api/v2/internals/broadcasts/views.py`: `parser_classes`, `prepare_broadcast_request` before the idempotency lookup, `data` and `project_uuid` from the prepared payload, `compute_media_body_hash` for multipart, the new serializer with `inline_media` context, and `except MediaStorageUnavailable` that releases the key and returns `503`. JSON path stays as today and still calls `compute_body_hash`. Do not set or clear `throttle_scope` or `throttle_classes`; `throttle_classes` stays `[]`. `IsUserInOrg` reads the project from the body, which a multipart body has inside `payload`, so for multipart the view gives the payload's project to the request when it has none and calls `check_permissions` again (`check_permissions_for_payload_project`); the permission classes themselves are unchanged. T023 to T025 pass. Commit: `feat: accept multipart on internal broadcasts`
- [X] T027 [P] [US1] Add `test_bridge_serializer_unchanged` in `temba/api/v2/internals/broadcasts/tests.py`. Do not edit `temba/fastapi_app/tests.py` or `temba/fastapi_app/broadcasts.py`. Assert `post_internal_whatsapp_broadcast` still depends on `verify_jwt` and still constructs `WhatsappBroadcastWriteSerializer` with the JSON body, and that `broadcasts.py` does not reference `WhatsappBroadcastWithMediaWriteSerializer` or `BroadcastMultiPartParser`. The existing `temba.fastapi_app` tests pass unmodified (AC-10). Commit: `test: keep FastAPI bridge on JSON serializer`

**Checkpoint**: both endpoints accept multipart with idempotency; every AC from AC-1 to AC-10 has a passing flow test.

---

## Phase 5: Contract and docstring

**Goal**: FR-027; the OpenAPI fragment in `contracts/` matches the behavior.

- [X] T028 [P] Test in `temba/api/v2/tests.py` that `WhatsappBroadcastsEndpoint.get_write_explorer()` has a `files` entry and that the docstring mentions `multipart/form-data`, the 10-file limit and the order rule. Commit: `test: assert explorer lists media files`
- [X] T029 Update the `WhatsappBroadcastsEndpoint` docstring (new "Sending media files" section with the type and size table and a `curl -F` example) and `get_write_explorer` (`files` field, `attachments` help text) in `temba/api/v2/views.py`. Commit: `docs: describe multipart media in API docs`
- [X] T030 Compare `specs/019-broadcast-inline-media/contracts/whatsapp-broadcasts-multipart.openapi.yaml` with the implemented statuses, error keys and the `503` bodies of both endpoints. Fix the YAML where the code differs; if nothing differs, make no commit. Commit: `docs: align multipart contract with behavior`

---

## Phase 6: Changelog and final verification

- [X] T031 Add a new top section `3.113.0` to `WENI-CHANGELOG.md` with one bullet: `feat: accept media files inline (multipart) on WhatsApp broadcasts, public and internal endpoints`. Commit: `docs: add changelog for inline broadcast media`
- [ ] T032 Run `poetry run coverage run manage.py test temba.msgs.usecases temba.utils.s3 temba.api temba.fastapi_app` and `./code_check.py`; run the staging checks and rollout gates in `quickstart.md` before production. The dedup check (SC-003) is one sample: the repeated multipart call's time is within 10% of a JSON call to the same group plus the time to receive the file. No percentile harness. Fix failures in the owning task's files. No commit if nothing changes.
  - Status: the automated part is done (see below). The staging checks and rollout gates of `quickstart.md` are NOT done: they need a staging environment, and the ingress, Kong, IAM and lifecycle gates need the infrastructure.

---

## Dependencies

- T001 first (detection needs libmagic in CI).
- Phase 2 blocks Phases 3 and 4. Inside it, each test task precedes its implementation: T002 → T003, T004 → T005 → T006 → T007, T008 → T009, T010 → T011. T004 → T006 → T008 → T010 is sequential because those tests share `temba/msgs/usecases/tests/test_broadcast_media.py`. T005 → T009 → T011 is sequential because they share the use-case module. T002 is a different test file and can be written beside T004.
- Phase 3 needs T011. T012 → T013. T012 → T014 → T015 → T016 → T017 → T018 → T019 → T020 because T012 and T014 to T018 share `temba/api/v2/tests.py`. T013 before T019.
- Phase 4 needs T013 and T019 (shared glue and serializer). T021 → T022. T021 → T023 → T024 → T025 → T027 → T026 because those tests share `temba/api/v2/internals/broadcasts/tests.py`. T022 before T026.
- Phase 5 needs T020. Phase 6 is last.

## Parallel examples

- Phase 2: T002 can be written beside T004. T004, T006, T008, and T010 are separate classes in one file, written in that order.
- Phase 3: T014 to T018 are separate classes in `temba/api/v2/tests.py`, written in that order.
- Phase 4: T021, T023, T024, T025, and T027 are separate classes in `temba/api/v2/internals/broadcasts/tests.py`, written in that order.

## Implementation strategy

1. MVP: T001 to T020 delivers US1, US2, US3 and US5 on the public endpoint, which is the customer-facing problem.
2. Increment: T021 to T027 adds the internal endpoint with idempotency (US4).
3. Close: T028 to T032 documents, records the changelog and verifies.

## Scope check

Every task maps to a spec FR or AC. Nothing here touches the FastAPI bridge code or its existing tests, `upload_media`, `S3MediaProxyView`, Courier, Mailroom, authentication, permissions, `throttle_scope`, `throttle_classes`, or the pre-existing issues listed out of scope. The only infrastructure edits are `libmagic1` (T001), required by detection.
