# Engineering Specification: Serve Private Media to the Zendesk File Callback

**Repository**: weni-ai/flows — backend (code change in weni-ai/rapidpro-apps, `weni/s3`)

**Feature Branch**: `015-zendesk-media-callback`

**Created**: 2026-11-06

**Status**: Draft

**Incident**: Slack `C0806AJEFCN` thread `p1793115368086179` ("Link do arquivos gerados pela plataforma está dando erro de acesso no Bucket"). Most affected customer: Adcos, during Cyber Week.

**Suggested cycle**: SDD Lite. The change is one view and one service in `rapidpro-apps`, plus a dependency bump and changelog entry in Flows. There is no migration, no public contract change and no Courier or Mailroom change. It MAY be promoted to SDD Full with `/speckit.plan` if review asks for it.

## Origin Without Product Spec

- Product Spec: none
- Problem: The Courier media bucket is now private, but `POST /api/v2/file/<path>`, the URL Zendesk calls to download each attachment of a ticket comment, still fetches the object with an unsigned GET. S3 answers `403 AccessDenied`, and the view returns that XML to Zendesk as an `HTTP 200` file. Zendesk cannot render it, so agents see only the file name and never the image, audio, video or document the contact sent.
- Acceptance criteria:
  - AC-1: `POST /api/v2/file/<path>` for an object that exists at `media/<path>` in the Courier media bucket returns `200`, with the object's bytes as the body and the `Content-Type` and `Content-Length` S3 reports. The request Flows sends to S3 is presigned (`X-Amz-Signature` present) and has an explicit connect and read timeout.
  - AC-2: When S3 reports the object does not exist (`404`), the endpoint returns `404` with an empty body. When S3 returns `403` or any other non-success status, or when the request fails to connect, times out or cannot be signed, the endpoint returns `502` with an empty body. Flows never answers `200` with a body that is not the object, and never sends an unsigned request to S3.
  - AC-3: A path with an empty, `.` or `..` segment returns `404` without any S3 request. A path outside `[\w\-./]+` keeps returning `404` from URL resolution.
  - AC-4: Every request is checked against the `metadata` Zendesk posts. The check passes only when the body holds a `metadata` string that parses to a `ticketer` UUID and a `secret`, an active Zendesk ticketer with that UUID exists, its `secret` config matches (constant-time comparison), and the first path segment is that ticketer's org ID. In this release a failed check is **logged and the file is still served** (observe mode). Blocking a failed check with `403` is a follow-up release (see **Out of scope**).
  - AC-5: Each failure writes one structured error log line with the object key, the org ID taken from the path and the upstream status or exception class. No signed URL, AWS credential, ticketer secret or raw `metadata` appears in a log line or a Sentry event. A successful download writes no application log line.
  - AC-6: `GET` on the route keeps returning `405`.
  - AC-7: Flows ships the new `weni-rp-apps` version with a `WENI-CHANGELOG.md` entry. In staging, a new image, `.oga` audio and PDF sent by a contact in a conversation forwarded to a Zendesk ticket appear in Zendesk as attachments agents can open. In production, `curl -X POST https://flows.weni.ai/api/v2/file/22878/a10e/5dfe/a10e5dfe-6071-4b70-9a0f-6d65afaf0e05.jpg` returns `200` with `image/jpeg`.

## Clarifications

### Session 2026-11-06

- Q: Should the callback validate the `metadata` Zendesk posts, and should a failed check block the download? → A: Validate in two phases. This release checks every request and only logs failures, so a `metadata` format different from the expected one cannot break downloads during the incident. A follow-up release blocks failed checks with `403` once the logs show legitimate Zendesk calls pass.

## Scope in This Repository

**This change implements**:

- In `weni-ai/rapidpro-apps`, `weni/s3`:
  - A service, `weni/s3/services.py`, that validates the path, builds the canonical object URL from `COURIER_S3_ENDPOINT`, presigns it through `temba.utils.s3`, fetches it with explicit timeouts and returns either a stream with its headers or a typed failure.
  - A callback authorization check in observe mode (AC-4), in the same service module, with the ticketer lookup isolated in `weni/s3/repositories.py`.
  - `WeniFileCallbackView.post`, reduced to calling the service and mapping its result to a response (AC-1 to AC-4, AC-6). The route, its name (`file_callback`) and its `csrf_exempt` dispatch stay as they are.
  - Tests in `weni/s3/tests.py`. None exist today.
  - A release of `weni-rp-apps` (2.13.1 → 2.13.2).
- In `weni-ai/flows`:
  - The `weni-rp-apps` bump in `pyproject.toml` and `poetry.lock`.
  - A `WENI-CHANGELOG.md` entry (AC-7).

**Out of scope here**:

- **Blocking failed authorization (phase 2).** A follow-up release returns `403` with an empty body, before any S3 request, when the AC-4 check fails. It ships only after at least one week of production logs shows no `zendesk file callback authorization failed` line for legitimate Zendesk downloads, or after each reason seen has been explained and fixed. It gets its own spec or an amendment to this one.
- **Mailroom.** `services/tickets/zendesk/service.go` keeps sending `https://<S3MediaPrefixZendesk>/api/v2/file/<key>`. Mailroom 1.105.2 and 1.105.3 already moved Weni Chats, generic, Rocket.Chat, Freshchat and webhooks to durable `/mr/media/<token>` links ([mailroom#407](https://github.com/weni-ai/mailroom/pull/407), [mailroom#410](https://github.com/weni-ai/mailroom/pull/410)). See **Rejected Alternatives** for why Zendesk is not moved to them here.
- **The Zendesk manifest and the URL format** sent in `file_urls` are unchanged.
- **Attachments that Zendesk has already failed to import.** Zendesk does not retry a failed download, so those comments keep showing only the file name. Only messages forwarded after the deploy are fixed.
- **Upstream `temba.tickets.types.zendesk.views.FileCallbackView`** (`/tickets/types/zendesk/file/<path>`, which reads `attachments/` from Flows storage) is not used by Weni's Mailroom and is not changed.
- **Media outside the Courier media bucket.** Mailroom strips only `S3MediaPrefix` from the attachment URL and drops the host, so the callback can only resolve keys in the bucket of `COURIER_S3_ENDPOINT`. That is true today and stays true.

## Current State

- `mailroom/services/tickets/zendesk/service.go`:
  - `convertAttachments` (lines 391–411) strips the scheme, host and `S3MediaPrefix` (`/media/`) from each attachment URL and sends `https://<S3MediaPrefixZendesk>/api/v2/file/<org_id>/<4 chars>/<4 chars>/<file name>` in `file_urls`.
  - `Forward` (lines 221–252): when a message has no text, it uses the file name of the first attachment as the comment text. That is the text agents see now that the download fails.
- Zendesk Channel framework ([pull endpoint docs, "file urls"](https://developer.zendesk.com/documentation/channel_framework/understanding-the-channel-framework/pull_endpoint/)): file URLs must be HTTPS and on the same subdomain as the manifest. Zendesk downloads each one with a `POST` whose JSON body carries the integration instance metadata under the key `metadata`. A failed download is not fatal and is not retried. Zendesk imposes a timeout on the whole conversion, including downloads, but does not document a number.
- `flows/temba/tickets/types/zendesk/views.py`:
  - `ManifestView` (line 153) advertises `https://<domain>/...` URLs, so files must be served from the Flows domain.
  - `ConfigureView` (line 300) stores `metadata = json.dumps({"ticketer": <uuid>, "secret": <secret>})` in Zendesk. That string is what Zendesk sends back in the file `POST`.
  - `FileCallbackView` (lines 305–318) is `csrf_exempt` and has no authentication.
- `flows/temba/tickets/types/zendesk/type.py`: `ZendeskType.CONFIG_SECRET = "secret"` (line 16), the per-ticketer secret.
- `rapidpro-apps/weni/s3`:
  - `apps.py`: `ready()` appends `urls.urlpatterns` to `temba.api.v2.urls` through `weni.utils.app_config.update_urlpatterns`, which is how the route ends up at `/api/v2/file/<path>`.
  - `urls.py`: `^file/(?P<path>[\w\-./]+)$` → `WeniFileCallbackView`, name `file_callback`.
  - `views.py` (lines 10–19): `WeniFileCallbackView(FileCallbackView).post` asserts `".." not in path` (removed under `python -O`), calls `requests.get(f"{settings.COURIER_S3_ENDPOINT}/media/{path}")` with no signature and no timeout, reads the whole body into memory, and returns it with the upstream `Content-Type` and a hard-coded `200`.
  - The module has had no change since 2022 and has no tests.
- `flows/temba/utils/s3/s3.py`: `parse_s3_url` (line 58), `signable_buckets()` (line 79, `AWS_STORAGE_BUCKET_NAME` + `S3_MEDIA_BUCKETS` + `S3_SIGNED_EXTRA_BUCKETS`) and `presign_url` (line 83), which signs with a cached regional SigV4 client and returns the URL **unchanged** when the bucket is not signable.
- `flows/temba/settings.py.prod` (lines 182–202): `COURIER_S3_ENDPOINT`, `S3_MEDIA_BUCKETS`, `S3_SIGNED_EXTRA_BUCKETS`, `S3_PRESIGNED_URL_EXPIRES`. In production `COURIER_S3_ENDPOINT` is the virtual-hosted URL of the media bucket, `https://push-ilha-sp-push-media-prod.s3.sa-east-1.amazonaws.com`.
- `flows/temba/tests/s3.py`: `S3_SIGNING_SETTINGS`, the fake-credential override used by the signing tests.
- **Reproduced on 2026-11-06:** an unsigned `GET` on the object returns `403` with `<Code>AccessDenied</Code>`. `POST https://flows.weni.ai/api/v2/file/22878/a10e/5dfe/a10e5dfe-6071-4b70-9a0f-6d65afaf0e05.jpg` returns `200 application/xml` with that same error body. `GET` on the route returns `405`.
- **Test execution gap:** Flows CI (`.github/workflows/ci.yml`) runs only `temba.*` labels, and `rapidpro-apps` CI (`build-rapidpro-apps-pypi.yaml`) only publishes the package. `weni/*` tests run only when invoked by hand from a Flows checkout with `rapidpro-apps` installed, using the `TembaTest` base that `weni/ticketer_queues/tests.py` already uses.

## Technical Approach

### Components Affected

| Component | Change | Why |
|-----------|--------|-----|
| `rapidpro-apps/weni/s3/services.py` | new | `fetch_courier_media(path) -> CourierMedia`, raising `MediaNotFound` or `MediaUnavailable`. It holds path validation, URL building, signing and the S3 request, so the view stays thin (Principle IX). |
| `rapidpro-apps/weni/s3/services.py` (same module) | new | `check_zendesk_callback(body, content_type, path) -> CallbackAuthResult`, returning `ok` or a reason code. It never raises on malformed input. |
| `rapidpro-apps/weni/s3/repositories.py` | new | `get_active_zendesk_ticketer(uuid) -> Ticketer | None`, the only database access of the module: one lookup by the unique `uuid`, filtered on `ticketer_type="zendesk"` and `is_active=True`. |
| `rapidpro-apps/weni/s3/views.py` | modified | `post` runs the authorization check (logging only), then calls the fetch service and maps its result: a `StreamingHttpResponse` for success, `404` for `MediaNotFound`, `502` for `MediaUnavailable`. It drops the `assert`, the unsigned `requests.get` and the in-memory read. |
| `rapidpro-apps/weni/s3/tests.py` | new | View and service tests, see **Test Strategy**. |
| `rapidpro-apps/pyproject.toml`, `CHANGELOG.md` | modified | Release 2.13.2 with a `fix` entry. |
| `flows/pyproject.toml`, `poetry.lock` | modified | `weni-rp-apps = "2.13.2"`. |
| `flows/WENI-CHANGELOG.md` | modified | Entry under the version that ships the bump. |

### Flow

1. **Request.** Zendesk sends `POST https://<flows domain>/api/v2/file/<path>` with the JSON body `{"metadata": "<string>"}`. URL resolution rejects anything outside `[\w\-./]+` with `404`.
2. **Path validation.** The service splits `path` on `/` and raises `MediaNotFound` when any segment is empty, `.` or `..` (AC-3). Nothing is fetched and no authorization check runs.
3. **Authorization, observe mode (AC-4).** `check_zendesk_callback` evaluates, in order, and stops at the first failure:
   - `missing_metadata`: the body is not a JSON object with a string `metadata`.
   - `invalid_metadata`: `metadata` does not parse to an object with string `ticketer` and `secret`, or `ticketer` is not a UUID.
   - `unknown_ticketer`: `get_active_zendesk_ticketer` finds nothing.
   - `secret_mismatch`: `hmac.compare_digest(ticketer.config["secret"], secret)` is false.
   - `org_mismatch`: the first path segment is not `str(ticketer.org_id)`.
   On failure the view logs one `warning` (see **Observability**) and **continues** to step 4. The view carries a comment saying the result is only logged until phase 2. Phase 2 replaces that log-and-continue branch with a `403` return.
4. **URL building.** The canonical URL is `f"{COURIER_S3_ENDPOINT.rstrip('/')}/{COURIER_MEDIA_KEY_PREFIX}{path}"`, with `COURIER_MEDIA_KEY_PREFIX = "media/"`, the same key prefix the view uses today. `parse_s3_url` must resolve it to a bucket in `signable_buckets()`. Otherwise the service logs `courier media bucket is not signable` and raises `MediaUnavailable`. This check comes before signing because `presign_url` silently returns an unsigned URL for a bucket it does not sign, and that would reproduce the bug.
5. **Signing.** `presign_url(canonical_url, expires=MEDIA_FETCH_URL_EXPIRES)` with `MEDIA_FETCH_URL_EXPIRES = 60` seconds. The URL is used once, server-side, so it never needs to outlive the request. A botocore exception while signing is logged and raised as `MediaUnavailable`.
6. **Fetch.** `requests.get(signed_url, stream=True, timeout=(MEDIA_FETCH_CONNECT_TIMEOUT, MEDIA_FETCH_READ_TIMEOUT))` with `5` and `30` seconds. The read timeout bounds the wait between bytes, not the whole transfer, which keeps a large video from failing while still releasing the worker when S3 stalls.
7. **Status mapping.**
   - `200`: return `CourierMedia(stream, content_type, content_length)`. `content_type` falls back to `application/octet-stream` when S3 sends none.
   - `404`: `MediaNotFound`.
   - `403` and any other status: `MediaUnavailable`, logged with the status. A `403` can also mean a missing key when the Flows role lacks `s3:ListBucket`, so it is not mapped to `404`.
   - `requests.Timeout` or `requests.ConnectionError`: `MediaUnavailable`, logged with the exception class.
   The upstream response is closed on every failure path.
8. **Response.** The view returns `StreamingHttpResponse(media.stream, content_type=media.content_type)` with `Content-Length` when known, reading the upstream body in `MEDIA_STREAM_CHUNK_SIZE = 64 * 1024` byte chunks and closing it when the stream ends. Failures return `HttpResponse(status=404)` or `HttpResponse(status=502)` with no body.

### Rejected Alternatives

- **Move Zendesk to Mailroom's durable `/mr/media/<token>` links** (`convertAttachments` calling `presign.DurableURL`, plus a `POST` route next to the `GET` and `HEAD` ones in `web/media/media.go`). This needs a Mailroom release, a `MediaLinkSecret` in every deployment, and proof that Mailroom's `Domain` is the manifest's subdomain, which Zendesk requires. It also cannot help any URL already queued with the `/api/v2/file/` format. It remains a valid follow-up to retire this view.
- **Redirect (`302`) to a presigned URL.** Zendesk downloads with `POST`. A `302` turns into a `GET` in most clients, but whether Zendesk follows redirects to another host is undocumented, and the presigned URL would be on the bucket's domain, not the manifest's.
- **`boto3.get_object` through `regional_client`.** This also works, but the cached client has no connect or read timeout configured, and changing it would affect every caller of `temba.utils.s3`. A presigned URL with `requests` keeps the explicit timeouts local to this call, and the tests can assert that the request was signed.
- **Read the body into memory, as today.** WhatsApp media goes up to 100 MB for documents, and holding that in a web worker costs memory for nothing, because Django can stream it.

## Contracts

| Interface | Change | Version impact | Backward compatible |
|-----------|--------|----------------|---------------------|
| `POST /api/v2/file/<path>` | fixed: success returns the object, missing object returns `404`, upstream failure returns `502` | `weni-rp-apps` patch | yes. Zendesk treats a non-`2xx` download as a failed file, which is what a `200` with an XML body already was in practice. |
| `GET /api/v2/file/<path>` | unchanged (`405`) | none | yes |
| Zendesk `file_urls` format and manifest | unchanged | none | yes |
| `weni-rp-apps` dependency | 2.13.1 → 2.13.2 | Flows patch | yes |
| Settings | none added. Reads the existing `COURIER_S3_ENDPOINT`, `S3_MEDIA_BUCKETS`, `S3_SIGNED_EXTRA_BUCKETS` and AWS settings | none | yes |
| Courier and Mailroom versions | unchanged | none | yes |

## Data Model and Migrations

No model or schema change, and no migration.

## Non-Functional Requirements

### Peak Load

- **Measurement:** not available when this spec was written. Grafana returned `401` for the Loki datasource. Rollout step 1 measures the busiest hour of `POST /api/v2/file/` before deploy.
- **Requests generated per use:** one `POST` per attachment of each contact message forwarded to a Zendesk ticket, with up to 10 per message (the Channel framework limit). There are no retries.
- **Declared peak (estimate, to be confirmed in rollout):** **5 requests per second** sustained during the busiest hour, with bursts of **20 concurrent downloads** when a contact sends an album. Files are mostly images and voice notes under 5 MB, with documents and videos up to the WhatsApp limits.
- **Cost per request:** one indexed PostgreSQL lookup of the ticketer by `uuid`, one local SigV4 signature and one streamed S3 `GET` in the same region. Each download holds a web worker for its transfer time, as it does today. Streaming removes today's full in-memory copy. If the measured peak exceeds the declared one by more than 2×, worker headroom must be reviewed before deploy.
- **Statelessness:** the service keeps nothing between requests. The regional signing client cached by `temba.utils.s3` holds only configuration and credentials.

### Observability

- **Success path:** no application log line. The access log already records method, path, status and size.
- **Failure path (AC-5):** one `logger.error` (or `logger.exception` for a signing error) on the `weni.s3` logger, with `extra` fields `key` (the S3 object key), `org_id` (first path segment), and `upstream_status` or `error` (exception class name). Object keys are generated by Courier as `<org_id>/<4>/<4>/<uuid>_<uuid>.<ext>` and carry no personal data.
- **Authorization failure (AC-4):** one `logger.warning("zendesk file callback authorization failed")` with `extra` fields `reason` (one of the codes in **Flow** step 3), `org_id` from the path, `ticketer_uuid` when it parsed, and `request_content_type`. The content type is logged so that a body Zendesk sends in another encoding can be identified from the logs, before phase 2.
- **Never logged or reported:** the signed URL, AWS credentials, the request body, the `metadata` string and the ticketer secret.
- **Correlation:** Zendesk sends no trace header. The Sentry Django integration attaches the request ID and path to the event, and `org_id` is set as a Sentry tag so failures can be filtered per project.

### Failure Handling

- **External dependency:** S3 only, with a `5` s connect and `30` s read timeout (Principle X).
- **Retry:** none inside the request. Zendesk owns the download, does not retry, and a retry inside Flows would spend the conversion time Zendesk shares across all files of the comment. Principle XI does not apply: Flows serves a read and propagates nothing.
- **Idempotency:** the endpoint only reads, so repeated calls are safe.
- **Configuration errors** (bucket not signable, missing credentials) return `502` and log once per request, so a bad deploy shows up as a spike of `502` instead of silent `200` XML.

### Security and Authorization

- **Trust boundary:** the path and body come from the internet. The path is validated by the URL regex and by segment checks before any use, and the object key is always under `media/` in the one bucket named by `COURIER_S3_ENDPOINT`, so a caller cannot reach another bucket or prefix. The host is never taken from the request, so there is no server-side request forgery surface.
- **Exposure change:** before the bucket became private, any object was readable by anyone with its URL. After the bucket became private, this route stayed open but returned errors. With this fix, the route again serves any `media/` object to anyone who knows its key. Keys contain two random UUIDs, so they cannot be guessed, but they do leak through logs, exports and webhooks.
- **Authorization (AC-4):** Principle XVII requires an endpoint reachable without a user to use a dedicated check that replaces user identity. The only signal Zendesk sends is `metadata`, which holds the ticketer UUID and its secret, so the check binds each download to an active Zendesk ticketer of the org that owns the key. The secret is compared with `hmac.compare_digest`. A failed check reveals nothing different to the caller in phase 1, because the response is the same.
- **Why observe mode first:** the `metadata` format comes from `ConfigureView` and the Zendesk docs, but no production request body has been inspected, and old installations may hold a different string. Blocking immediately could turn the incident fix into a total outage of Zendesk attachments. Exposure during phase 1 is the same as before the bucket became private.
- **Secrets:** none added. Signing uses the existing AWS credentials, or the pod role when they are empty.

## Test Strategy

Tests live in `rapidpro-apps/weni/s3/tests.py`, use `TembaTest`, and run under `override_settings(**S3_SIGNING_SETTINGS, COURIER_S3_ENDPOINT="https://media-bucket.s3.sa-east-1.amazonaws.com")`. S3 is stubbed only at the HTTP boundary, by patching `requests.get` in `weni.s3.services`. Signing runs for real with the fake keys.

| Acceptance criterion | How it is proven |
|----------------------|------------------|
| AC-1: object served | Post to `/api/v2/file/<org_id>/ab12/cd34/<uuid>.jpg` with the stub answering `200`, `image/jpeg`, a known body and `Content-Length`. Assert `200`, the same bytes, `Content-Type` and `Content-Length`. Assert the stubbed URL is for `media-bucket`, key `media/<org_id>/ab12/cd34/<uuid>.jpg`, carries `X-Amz-Signature`, and was called with `stream=True` and `timeout=(5, 30)`. A second case without `Content-Type` from S3 returns `application/octet-stream`. |
| AC-2: failures | Stub `404` → `404` with an empty body. Stub `403` and `500` → `502`. `requests.Timeout` and `requests.ConnectionError` → `502`. Patch `presign_url` to raise `NoCredentialsError` → `502`. Set `COURIER_S3_ENDPOINT` to a bucket outside `signable_buckets()` → `502`, and `requests.get` is not called. Each case asserts the response body is empty and the upstream response was closed. |
| AC-3: path validation | Paths with `//`, `/./`, `/../` and a trailing `/` → `404`, and `requests.get` is not called. A path with `%` is rejected by URL resolution (`404`). |
| AC-4: authorization (observe mode) | With a Zendesk ticketer created in `self.org` (`secret` config set) and the stub answering `200`: the body `{"metadata": json.dumps({"ticketer": <uuid>, "secret": <secret>})}` gives `200` and no warning. Each failure reason gives `200` with the object **and** one warning with that `reason`: no body, a body without `metadata`, `metadata` that is not JSON, a non-UUID `ticketer`, an unknown UUID, an inactive ticketer, a non-Zendesk ticketer with the same UUID, a wrong secret, and a path whose first segment is `self.org2.id`. No warning contains the secret or the `metadata` string. A unit test of `check_zendesk_callback` asserts each reason code directly. |
| AC-5: logs | `assertLogs("weni.s3", "ERROR")` on each AC-2 case shows one record with `key` and `org_id`, and no record contains `X-Amz-Signature`, the fake AWS secret or the posted `metadata`. `assertNoLogs` on the AC-1 case. |
| AC-6: method | `GET` → `405`. |
| AC-7: release | Covered by the rollout steps below. It is manual, because it needs a Zendesk account and the real bucket. |

**Flow coverage** (Principle XIV): one test runs the full use case. It creates a Zendesk ticketer with `TembaTest`'s org, builds the attachment URL the way Mailroom does (Courier URL with `media/` stripped), posts to the resolved callback URL with the `metadata` body Flows stored for that ticketer, and asserts the object bytes come back.

**Failure paths covered:** missing object, denied object, other upstream status, timeout, connection error, signing error, unsignable bucket, invalid path, wrong method.

**Gates:** neither CI runs `weni/*` tests (see **Current State**). The PR description in `rapidpro-apps` MUST include the output of `poetry run python manage.py test weni.s3` from a Flows checkout with the branch installed (`pip install -e ../rapidpro-apps`). The Flows PR runs the usual green `ci.yml` and `./code_check.py`. `rapidpro-apps` code MUST pass its `.flake8` and `pre-commit` config. No `# pragma: no cover` is added.

## Rollout and Rollback

1. **Before deploy, in production:**
   - Confirm that `S3_MEDIA_BUCKETS` or `S3_SIGNED_EXTRA_BUCKETS` in the Flows environment contains `push-ilha-sp-push-media-prod`, and that the Flows role has `s3:GetObject` on `media/*` of that bucket. Without both, every download returns `502`, which is still better than today's `200` XML but does not fix the incident.
   - Confirm `S3MediaPrefixZendesk` in Mailroom is the Flows domain (`flows.weni.ai` and the other regional domains).
   - Measure the busiest hour of `POST /api/v2/file/` in the Flows access logs and compare it with the declared peak.
2. **Release `weni-rp-apps` 2.13.2**, then bump it in Flows and deploy to staging.
3. **Validate in staging** with a Zendesk sandbox ticketer: send an image, an `.oga` voice note, a PDF and a video from WhatsApp into a conversation that opens a Zendesk ticket, and confirm all four open in Zendesk. Post a non-existent key and confirm `404`.
4. **Deploy to production** and run the AC-7 `curl`. Ask support (Bruno) to confirm with Adcos on a new message.
5. **Watch the authorization warnings** for at least one week. Group `zendesk file callback authorization failed` by `reason` and `request_content_type`. Legitimate traffic with no warnings, or with every reason explained, is the entry condition for phase 2.
6. **Rollback:** pin `weni-rp-apps` back to 2.13.1 and redeploy Flows. Nothing is persisted, so the rollback is safe, and it returns to today's behaviour.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | PRs to `main` in both repositories with approved review. | `rapidpro-apps` has no test CI; the PR must attach the manual test run (see **Test Strategy**). |
| II. Security and Secrets | No new secret or dependency. `requests` and `boto3` are already locked in Flows. | none |
| III. Observability | Structured failure logs with key and org ID; no signed URL, credential, secret or body in logs or Sentry. | none |
| IV. Versioned Contracts | The route keeps its path, method and success shape. Only the error statuses become correct. Listed under Contracts as a patch. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`. | none |
| VI. No Silent Divergence | Not applicable: no Product Spec. | none |
| VII. Commit Messages | `fix:`, `test:`, `chore:` commits of at most 50 characters. | none |
| VIII. Changelog Maintenance | Flows: `chore: update weni-rp-apps to 2.13.2 (fix: serve private media to the Zendesk file callback)`. `rapidpro-apps` `CHANGELOG.md`: `[2.13.2] fix: sign Zendesk file callback downloads`. | none |
| IX. Never Trust the Client | Path validated before use; bucket and prefix fixed by configuration. View delegates to `weni/s3/services.py`. | `rapidpro-apps` has no `usecases/` layer; the service module plays that role. |
| X. Fail Gracefully | Explicit timeouts; every failure has a defined empty `404` or `502`; no stack trace returned. | none |
| XI. Bounded Retry Over REST | Not triggered: a read served to Zendesk, which owns the download. | none |
| XII. Scalability and Peak Load | Stateless; peak declared as an estimate and measured in rollout step 1. | The peak is an estimate because log access was unavailable. |
| XIII. Diagnosable Errors | Failure events carry `org_id` and the request context from the Django integration. | Zendesk sends no user or trace identifier, so none can be attached. |
| XIV. Tests Exercise Flows | One end-to-end callback test plus per-criterion view tests, success and failure paths, with `TembaTest`. | Run by hand, see **Gates**. |
| XV. Explicit Over Clever | `COURIER_MEDIA_KEY_PREFIX`, `MEDIA_FETCH_URL_EXPIRES`, `MEDIA_FETCH_CONNECT_TIMEOUT`, `MEDIA_FETCH_READ_TIMEOUT` and `MEDIA_STREAM_CHUNK_SIZE` are named constants. A comment explains why the bucket is checked before `presign_url`. | none |
| XVI. Contained Changes | Only `weni/s3` and the Flows bump change. Mailroom, the upstream `FileCallbackView` and `temba.utils.s3` are untouched. | none |
| XVII. Explicit, Scoped Authorization | The route is open by necessity: Zendesk calls it without a user. Its dedicated check is the Zendesk `metadata` (ticketer UUID, secret, org of the key), implemented in `check_zendesk_callback`. | In this release the check only logs (observe mode) and does not deny. Justification: an unverified `metadata` format could block every Zendesk attachment during an active incident. Phase 2 makes it deny by default, see **Out of scope**. |

## Implementation Decisions

- **Keep the URL, method and route name.** Every message forwarded since 2022 uses this format, and the fix must work without touching Mailroom or the Zendesk installation.
- **`502`, not `500`, for upstream failures.** The failure is in S3 or its credentials, not in Flows' own logic, and the distinct status separates the two in dashboards.
- **`403` from S3 is not turned into `404`.** Without `s3:ListBucket`, S3 answers `403` for a missing key too, so `403` cannot be told apart from a permission problem. Reporting it as `502` keeps permission problems visible.
- **Presign for 60 seconds.** The signed URL is used once, server-side, immediately after it is built.

- **Path validation runs before authorization**, so a malformed path never reaches the database.

## Open Questions

None. Callback authorization was settled in the 2026-11-06 clarification. The bucket permissions and the peak load are rollout checks (step 1), not design choices.
