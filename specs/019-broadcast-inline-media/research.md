# Research: Inline media files in WhatsApp broadcast requests

Only decisions that had a real alternative are recorded here. Binding decisions from the spec are not reopened.

## R1. When the upload happens relative to serializer validation

- **Decision**: The use case computes each file's canonical URL from its hash, appends it to `msg.attachments`, and lets `is_valid()` run on the complete payload. The upload runs only in `save()` of a new subclass, `WhatsappBroadcastWithMediaWriteSerializer`, before `super().save()`. On the public endpoint, `get_write_serializer_class` returns that subclass, so `WriteAPIMixin.post` stays unchanged.
- **Rationale**: The URL depends only on org, hash and detected type, so validation can see the final attachments without anything being stored. Every `400` from payload rules, file rules or serializer rules therefore uploads nothing (FR-012, SC-004). `save()` is the existing place for creation side effects (trigger group, `send_async`).
- **Residual orphan**: `WhatsappBroadcastWriteSerializer.save()` can still raise after the upload (`GroupQuotaExceeded`, `ContactResolutionError`, `MailroomException`, which become a `400`). The object stays in the bucket. The key is content-addressed and the dedup entry is already written, so the orphan is bounded: at most one object per distinct (org, content), and the next request with the same content reuses it. No cleanup job.
- **Alternatives**: Uploading inside `get_write_serializer_class`, before `is_valid()`, is simpler, but it leaves an orphan on every serializer `400`. Overriding `post` on the endpoint to upload between `is_valid()` and `save()` duplicates `WriteAPIMixin.post`, which the design constraints rule out.

## R2. Detecting the real type from bytes

- **Decision**: Use `python-magic` (already declared in `pyproject.toml` at 0.4.27, not imported anywhere yet) on the first `MEDIA_SNIFF_BYTES` of each file. Add `libmagic1` to `RUNTIME_DEPS` in `docker/Dockerfile` and to the apt line in `.github/workflows/ci.yml`. Normalize libmagic aliases through a named table (`audio/x-m4a` → `audio/mp4`, `audio/x-hx-aac-adts` → `audio/aac`). An ISO BMFF container that libmagic reports as `video/mp4` or `video/3gpp` is reclassified as `audio/mp4` when no track has a `vide` handler. That check is a bounded walk over box headers (`moov` → `trak` → `mdia` → `hdlr`) that only seeks and reads headers. `magic` is imported inside the detection function, so a developer machine without libmagic can still load Django and run unrelated tests.
- **Rationale**: This reuses a declared dependency instead of a parallel sniffing pattern. libmagic covers every allowed category, including OLE2 and Office Open XML documents.
- **Known limit**: libmagic sometimes reports an older binary Office file only as generic OLE2 (`application/vnd.ms-office` or `application/CDFV2`). Those files are rejected with `400`, because the stored content type would be wrong for WhatsApp. Office Open XML files are not affected.
- **Alternatives**: A hand-written signature table has no system dependency. But telling `.doc`, `.xls` and `.ppt` apart would mean parsing the OLE2 directory, and it would be a second detection mechanism to maintain. `filetype` or `puremagic` would be a new dependency, and neither handles legacy Office better.

## R3. Explicit S3 timeouts and bounded retry

- **Decision**: Add `media_upload_storage()` to `temba/utils/s3/s3.py`, cached once per process. When `DEFAULT_FILE_STORAGE` is an `S3Storage` subclass, it builds an instance of that class with `file_overwrite=True` and merges into its `client_config` a `botocore` `Config(connect_timeout=S3_UPLOAD_CONNECT_TIMEOUT_SECONDS, read_timeout=S3_UPLOAD_READ_TIMEOUT_SECONDS, retries={"mode": "standard", "max_attempts": S3_UPLOAD_MAX_RETRY_ATTEMPTS})`. Merging keeps the signature version, addressing style and proxies that django-storages 1.14.6 sets by default. Otherwise it returns `private_file_storage` (local and test filesystem storage).
- **Rationale**: Uploads still go to `AWS_STORAGE_BUCKET_NAME` through the same storage class (binding decision 3), with timeouts scoped to this feature. The worst case with 5 s connect, 30 s read and 3 attempts is about 105 s, which is inside the gunicorn `timeout = 120`. Retrying is safe because the key is the content hash (Principle XI).
- **Alternatives**: Setting `AWS_S3_CLIENT_CONFIG` globally changes every upload in Flows (Principle XVI). Calling `put_object` on a raw boto3 client bypasses `private_file_storage`, which breaks local development on filesystem storage and duplicates the bucket and URL logic.

## R4. What happens on a dedup cache miss

- **Decision**: Upload directly with `save()`. No `HEAD` request beforehand.
- **Rationale**: A miss happens on the first send of a file, or after `BROADCAST_MEDIA_DEDUP_TTL_SECONDS` expires. Overwriting identical bytes at the same key is harmless, and skipping `HEAD` keeps the first upload one round trip shorter. A `HEAD` on a missing key also returns `403` instead of `404` when the role lacks `s3:ListBucket`. django-storages raises on that `403`, so every first upload would return `503`.
- **Alternatives**: `exists()` then `save()` avoids re-sending bytes after the time to live expires. That saves one upload per file per week at most, and it costs a round trip on every miss plus a hidden IAM dependency.

## R5. Redis timeouts for the dedup cache

- **Decision**: Add a dedicated `redis.Redis` client, cached once per process, built from `CACHES["default"]["LOCATION"]` with `socket_connect_timeout` and `socket_timeout` set to `BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS`.
- **Rationale**: `CACHES["default"]` has no socket timeouts, and changing it would affect every cache user. The idempotency store keeps using `get_redis_connection()` without timeouts, as today. That is pre-existing behavior, and FR-024 keeps it unchanged.
- **Alternatives**: Adding `SOCKET_TIMEOUT` to `CACHES["default"]["OPTIONS"]` changes every cache call in Flows, which is out of scope.

## R6. Sequential or parallel uploads

- **Decision**: Upload distinct new files one after another.
- **Rationale**: The production pattern is one image per request, and the dedup cache absorbs it after the first call. django-storages keeps one boto3 client per thread, so a thread pool would build a new client (tens of milliseconds) per worker thread for each request. For large files, django-storages already splits a single upload into parallel parts through its transfer configuration.
- **Alternatives**: A `ThreadPoolExecutor`, as in `managed_trigger_group`. Revisit it if requests with several distinct new files become common.

## R7. Enforcing the 100 MB total before the body is read

- **Decision**: Add `BroadcastMultiPartParser(MultiPartParser)`, set in `parser_classes` on both endpoints next to the default `JSONParser` and `FormParser`. It rejects a `Content-Length` above `MAX_BROADCAST_MULTIPART_BYTES` with `400` before parsing. That constant is `MAX_BROADCAST_FILES_TOTAL_BYTES` plus Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` plus `MULTIPART_OVERHEAD_BYTES`. After parsing, the use case checks the exact sum of `UploadedFile.size` against `MAX_BROADCAST_FILES_TOTAL_BYTES`.
- **Rationale**: A request with a large `Content-Length` never reaches temporary disk. The exact check after parsing makes the limit independent of multipart overhead.
- **Alternatives**: A custom upload handler that counts bytes while streaming. It needs `StopUpload` handling, whose error behavior differs between Django versions, and it gains nothing over the `Content-Length` guard.

## R8. Size of the `payload` field

- **Decision**: Accept Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB default, not overridden in Flows) as the limit for the `payload` part. The parser turns `RequestDataTooBig` into `400 {"payload": ["Payload is too large."]}`. Today that exception would reach the API exception handler as a `500`.
- **Rationale**: 1,000 recipients with typical variables take about 200 KB. The JSON variant has no such limit, because DRF reads JSON from the stream, and it stays unchanged.
- **Alternatives**: Raising `DATA_UPLOAD_MAX_MEMORY_SIZE` globally affects every form and upload in Flows. Accepting `payload` as a file part would add a second request shape to the contract.

## R9. Idempotency body hash for multipart

- **Decision**: Add `compute_media_body_hash(payload, file_sha256s)` next to `compute_body_hash` in `idempotency.py`. It hashes `{"payload": payload, "files": [sha256, ...]}` with sorted keys. JSON requests keep calling `compute_body_hash(request)`.
- **Rationale**: JSON hashes stay byte-identical, so keys stored before the deploy still replay. File order is part of the hash, which FR-018 requires.
- **Alternatives**: Changing `compute_body_hash` to accept data changes its callers and tests for no gain.

## R10. Dedup time to live

- **Decision**: `BROADCAST_MEDIA_DEDUP_TTL_SECONDS = 7 * 24 * 60 * 60`.
- **Rationale**: This covers a campaign resent over a week. At about 30,000 attachments a month, the entries take well under 1 MB of Redis. Rollout confirms that no S3 lifecycle rule expires `attachments/*/broadcasts/` sooner.
- **Alternatives**: 24 hours, like idempotency, re-uploads daily resends. No expiry leaves entries pointing at objects a future lifecycle rule might delete.
