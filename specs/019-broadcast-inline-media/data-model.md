# Data Model: Inline media files in WhatsApp broadcast requests

No Django model, table or migration changes. The broadcast keeps storing `msg` in `Broadcast.metadata` exactly as today; the only difference is that `msg.attachments` may contain canonical URLs of files stored by this feature.

## InlineMedia (in memory, one request)

Built by the use case for each part under `files`, in received order.

| Field | Type | Rule |
|---|---|---|
| `position` | int | Zero-based index in `files`; used in error keys. |
| `file` | `UploadedFile` | Django upload (memory below 2.5 MB, temp file above). Never logged. |
| `size` | int | `UploadedFile.size`; `> 0`; at most the category limit. |
| `sha256` | str | Lowercase hex SHA-256, computed in one pass over `file.chunks()`. The first `MEDIA_SNIFF_BYTES` of the same pass feed type detection. |
| `mime` | str | Detected and normalized type; must be a key of `ALLOWED_BROADCAST_MEDIA`. |
| `extension` | str | From `ALLOWED_BROADCAST_MEDIA[mime]`; never from the client file name. |

Derived:

- `key(org_id)` = `attachments/<org_id>/broadcasts/<sha256>.<extension>`
- `attachment(org_id)` = `<mime>:<STORAGE_URL>/<key(org_id)>`

## PreparedBroadcastRequest (in memory, one request)

Returned by `read_broadcast_request(...)`.

| Field | Type | Meaning |
|---|---|---|
| `is_multipart` | bool | `request.content_type` is `multipart/form-data`. |
| `payload` | dict | JSON body (`request.data`, untouched) or the parsed `payload` field. |
| `media` | list[InlineMedia] | Empty for JSON. |

Operations:

- `with_attachments(org)` returns a copy of `payload` whose `msg.attachments` is the payload list followed by `attachment(org.id)` of each `media` item, in order. When `msg` is absent or not an object, the payload is returned unchanged and the serializer reports `msg` as today. When `msg.attachments` is present and not a list, it is a `400` on `payload`.
- `file_sha256s` is the ordered list of `sha256`, used by the idempotency hash.

## Allowed types (`ALLOWED_BROADCAST_MEDIA`)

| Detected mime | Category | Extension | Limit constant |
|---|---|---|---|
| `image/jpeg` | image | `jpg` | `MAX_IMAGE_BYTES` = 5 MiB |
| `image/png` | image | `png` | `MAX_IMAGE_BYTES` |
| `image/webp` | sticker | `webp` | `MAX_STICKER_BYTES` = 500 KiB |
| `video/mp4` | video | `mp4` | `MAX_VIDEO_BYTES` = 16 MiB |
| `video/3gpp` | video | `3gp` | `MAX_VIDEO_BYTES` |
| `audio/aac` | audio | `aac` | `MAX_AUDIO_BYTES` = 16 MiB |
| `audio/amr` | audio | `amr` | `MAX_AUDIO_BYTES` |
| `audio/mpeg` | audio | `mp3` | `MAX_AUDIO_BYTES` |
| `audio/mp4` | audio | `m4a` | `MAX_AUDIO_BYTES` |
| `audio/ogg` | audio | `ogg` | `MAX_AUDIO_BYTES` |
| `text/plain` | document | `txt` | `MAX_DOCUMENT_BYTES` = 100 MiB |
| `application/pdf` | document | `pdf` | `MAX_DOCUMENT_BYTES` |
| `application/msword` | document | `doc` | `MAX_DOCUMENT_BYTES` |
| `application/vnd.ms-excel` | document | `xls` | `MAX_DOCUMENT_BYTES` |
| `application/vnd.ms-powerpoint` | document | `ppt` | `MAX_DOCUMENT_BYTES` |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | document | `docx` | `MAX_DOCUMENT_BYTES` |
| `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | document | `xlsx` | `MAX_DOCUMENT_BYTES` |
| `application/vnd.openxmlformats-officedocument.presentationml.presentation` | document | `pptx` | `MAX_DOCUMENT_BYTES` |

`LIBMAGIC_MIME_ALIASES` maps `audio/x-m4a` → `audio/mp4` and `audio/x-hx-aac-adts` → `audio/aac` before the lookup. ISO BMFF files without a `vide` track become `audio/mp4` (research R2).

Request-level limits: `MAX_BROADCAST_FILES = 10`, `MAX_BROADCAST_FILES_TOTAL_BYTES = 100 MiB`, `MAX_BROADCAST_MULTIPART_BYTES` (research R7). `MiB` = 1,048,576 bytes.

## Validation order

Cheap checks run first, so an oversize or overlong request is rejected before any file is read:

1. `Content-Length` guard in `BroadcastMultiPartParser`.
2. Form fields: only `payload` (exactly one) and `files`.
3. `payload` is valid JSON and a JSON object.
4. File count is at most `MAX_BROADCAST_FILES`; the sum of sizes is at most `MAX_BROADCAST_FILES_TOTAL_BYTES`.
5. Per file, in order: non-empty; hash and sniff pass; detected type is allowed; size is within the category limit.
6. Serializer `is_valid()` on `with_attachments(org)`.

Steps 2 to 5 collect every error before raising, so the caller sees all invalid files at once.

## Stored media object (S3)

| Attribute | Value |
|---|---|
| Bucket | `AWS_STORAGE_BUCKET_NAME` (through `media_upload_storage()`) |
| Key | `attachments/<org_id>/broadcasts/<sha256>.<ext>` |
| `ContentType` | detected mime (set on the `UploadedFile` before `save()`) |
| ACL | bucket default (`AWS_DEFAULT_ACL = None`), private |
| Lifecycle | none created by this feature |

Written with overwrite semantics; identical bytes always map to the same key.

## Dedup cache entry (Redis)

| Attribute | Value |
|---|---|
| Key | `broadcast_media:<org_id>:<sha256>` |
| Value | the canonical attachment string `<mime>:<STORAGE_URL>/<key>` |
| TTL | `BROADCAST_MEDIA_DEDUP_TTL_SECONDS` (7 days), refreshed on each write |
| Client | dedicated client with `BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS` (research R5) |

Lifecycle per distinct `sha256` in a request: `GET`. It is a hit only when the stored value equals the attachment computed for this request; a different value (for example after the type table changes) counts as a miss. On a hit, nothing else happens. On a miss, the object is uploaded and then `SET ... EX TTL` runs. Any Redis error becomes `BroadcastMediaUnavailable`. Org is part of the key, so no lookup crosses orgs (FR-015).

## Idempotency record (Redis, internal endpoint, existing)

The record format, key, `TTL_SECONDS`, and state machine (`inflight` and `done`, then `hit`, `conflict`, or `inflight` on lookup) are unchanged. Only the `body_hash` input differs for multipart:

| Variant | `body_hash` input |
|---|---|
| JSON | `json.dumps(request.data, sort_keys=True)` (unchanged) |
| Multipart | `json.dumps({"payload": payload, "files": file_sha256s}, sort_keys=True)` |

The multipart error paths that release the key after it is claimed are: `400` from `is_valid()`, `503` from `BroadcastMediaUnavailable`, project resolution errors (as today), and any other exception (as today). A `400` from steps 1 to 5 happens before the key is claimed.
