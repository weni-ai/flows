# Engineering Specification: Media URL Signing Endpoint for the Flow Editor

**Repository**: weni-ai/flows — backend

**Feature Branch**: `011-signed-media-urls`

**Created**: 2026-10-28

**Status**: Draft

**Paired spec**: weni-ai/floweditor `specs/001-signed-media-urls/spec.md` (the consumer of the endpoint specified here)

**Suggested cycle**: SDD Lite. The change is one view, one S3 helper, settings and the editor template, with no migration and no Courier or Mailroom coordination. It adds an editor-facing contract, so it MAY be promoted to SDD Full with `/speckit.plan` if review asks for it.

## Origin Without Product Spec

- Product Spec: none
- Problem: The buckets used by Flows are now private, but the flow editor only holds the canonical, unsigned S3 URLs stored in flow definitions and simulator events, and Flows exposes no endpoint the editor can use, with its Django session, to turn them into presigned URLs. Media uploaded in the editor or shown in the simulator therefore fails with `403 AccessDenied`.
- Acceptance criteria:
  - AC-1: `POST /flow/media_urls/<flow_uuid>/`, sent by a logged-in user with access to the flow's org, returns `200` with every requested URL as a key of `urls`. A URL in a signable bucket whose object key belongs to the flow's org is replaced by a presigned GET URL valid for `S3_PRESIGNED_URL_EXPIRES` seconds, and `expires_in` equals that setting.
  - AC-2: A URL that Flows must not sign is returned unchanged and is never signed: a bucket outside `signable_buckets()`, a non-S3 host (including the public `floweditor-assets.temba.io` sample media), an object key outside the org-scoped prefixes, an object key that belongs to another org, or an object key with a `.`, `..` or empty path segment (after percent-decoding).
  - AC-3: An anonymous request, a user without the `flows.flow_media_urls` permission, or a flow in another org receives `403` with a JSON body and no redirect, and nothing is signed. An unknown flow UUID receives `404`. Administrators, Editors, Marketing and Viewers of the org are allowed; Agents and Surveyors are not.
  - AC-4: A malformed JSON body, a missing or non-list `urls`, an empty list, more than 20 URLs, or a URL longer than 2048 characters receives `400` and nothing is signed. `GET` receives `405`. A `POST` without a valid CSRF token is rejected by Django's CSRF middleware.
  - AC-5: Every response produced by the endpoint's view (`200`, `400`, `403`, `404`, `405` and `500`) carries `Cache-Control: no-store` and, except for `405`, a JSON body. The CSRF rejection from Django's middleware is excluded, because it happens before the view runs and carries no URL. No original or signed URL is written to the application log or included in any Sentry event raised while the endpoint handles a request, including unhandled errors outside signing.
  - AC-6: The flow editor page renders `endpoints.media_urls = '/flow/media_urls/<flow_uuid>/'`. Once Flows also ships `@weni/flow-editor` 3.7.0, in a follow-up PR, a user can download an uploaded attachment, see simulator media and play a Say Message recording on the private bucket.
  - AC-7: An unexpected failure while signing returns `500` with a generic JSON error, without a stack trace, and is reported to Sentry once with opaque identifiers only.

## Clarifications

### Session 2026-10-29

- Q: The Marketing org role gets `flows.flow_media_urls` through the `flows.flow.*` wildcard. How should the spec treat it? → A: Allow Marketing; document it in AC-3, Scope and Security, and test that it returns `200`.
- Q: Which Sentry events from this view must have the request body (submitted URLs) removed? → A: Every event raised while handling the request. The scrubbing event processor is registered at the start of `dispatch`, and a test covers an unhandled error outside signing.
- Q: How should the 404 and the CSRF-rejection 403 fit AC-5's "every response carries `Cache-Control: no-store`"? → A: The view catches `Http404` and returns a JSON `404` with `no-store`. AC-5 explicitly excludes the CSRF middleware rejection.
- Q: Should the org ownership check refuse object keys with `.`, `..` or empty path segments? → A: Yes. Such URLs are returned unchanged, with unit cases for `..`, `.`, `//` and percent-encoded `%2E%2E`.

## Scope in This Repository

**This repository implements**:

- A new action on `FlowCRUDL`, `media_urls`, served at `POST /flow/media_urls/<flow_uuid>/` and authenticated with the Django session and CSRF.
- Validation of the request body at the boundary, with a DRF serializer.
- An org-scoped signing helper in `temba/utils/s3/s3.py` that builds on `parse_s3_url`, `signable_buckets` and `presign_url`, and refuses object keys that do not belong to the given org.
- A new permission, `flows.flow_media_urls`, granted to Administrators, Editors and Marketing (through the existing `flows.flow.*` wildcard) and to Viewers explicitly.
- A new setting, `S3_ORG_SCOPED_KEY_PREFIXES`, read from the environment in production.
- The `media_urls` key in the `endpoints` block of `templates/flows/flow_editor.haml`.
- The `@weni/flow-editor` bump from 3.6.5 to 3.7.0, in a follow-up PR opened once floweditor 3.7.0 is published. [flows#904](https://github.com/weni-ai/flows/pull/904) ships everything else.
- A `WENI-CHANGELOG.md` entry.

**Out of scope here**:

- **Every editor-side change** (the HTTP adapter, the signing cache, the Send Message, simulator and Say Message surfaces, and the fallback to the original URL) is owned by `weni-ai/floweditor` and specified in its `specs/001-signed-media-urls/spec.md`.
- **Signing at send time** in Mailroom, Courier and gocommon is already merged ([mailroom#404](https://github.com/weni-ai/mailroom/pull/404), [mailroom#403](https://github.com/weni-ai/mailroom/pull/403), [courier#243](https://github.com/weni-ai/courier/pull/243), [gocommon#2](https://github.com/weni-ai/gocommon/pull/2)). The dashboard message history, ticket history, API v2 and Mailroom events already sign through `presign_url` and `presign_attachment` ([flows#899](https://github.com/weni-ai/flows/pull/899)).
- **The simulator proxy** (`FlowCRUDL.Simulate`) keeps returning Mailroom's events unchanged. The editor signs their URLs through the new endpoint.
- **The upload response** of `UploadMediaAction` keeps returning the canonical URL, because that URL is persisted in the flow definition.
- **`S3MediaProxyView`** (`/api/v2/internals/media/download/...`) keeps its Keycloak authentication and is not reused or changed.

**Contract needed from `weni-ai/floweditor`**: release 3.7.0, which reads the optional `endpoints.media_urls` key and calls the endpoint as described under **Contracts**. The editor treats a missing key as "signing disabled", so either repository can ship first.

## Current State

- `temba/flows/views.py`:
  - `FlowCRUDL.actions` (line 187) lists the editor endpoints. `UploadMediaAction` (line 769) is an `OrgObjPermsMixin, SmartUpdateView` keyed by `slug_url_kwarg = "uuid"`. It stores uploads with `private_file_storage.save("attachments/%d/%d/steps/%s/%s" % (org_id, flow_id, uuid, name))` and returns `{"type": ..., "url": f"{settings.STORAGE_URL}/{path}"}`. That canonical URL is what ends up in Send Message attachments and Say Message `audio_url`.
  - `Revisions` (line 286, `AllowOnlyActiveFlowMixin, OrgObjPermsMixin, SmartReadView`) and its `post` (line 350) are the precedent for returning a `403` JSON response from an editor endpoint instead of the smartmin login redirect.
  - `Simulate` (line 1794) proxies to Mailroom's simulator and returns its events as they are.
  - `Editor` (line 1014) renders `templates/flows/flow_editor.haml` and sets `can_simulate`.
- `templates/flows/flow_editor.haml` (lines 247–285): the `endpoints` block of the editor config, with `attachments: '/flow/upload_media_action/{{object.uuid}}/'` and the simulator endpoints. There is no `media_urls` key today.
- `temba/orgs/views.py`, `OrgObjPermsMixin` (line 187): authorizes on the object's org. A failure goes through smartmin's dispatch, which redirects to the login page. `test_upload_media_action` asserts that redirect for a flow in another org (`assertLoginRedirect`). A user holding the permission globally (`user.has_perm`) passes for any org.
- `temba/utils/s3/s3.py`:
  - `parse_s3_url` parses virtual-hosted, path-style and `AWS_BUCKET_DOMAIN` URLs into `S3Location(bucket, key, region)` and ignores any query string.
  - `signable_buckets()` returns `AWS_STORAGE_BUCKET_NAME`, `S3_MEDIA_BUCKETS` and `S3_SIGNED_EXTRA_BUCKETS`.
  - `presign_url(url, expires=None, response_content_disposition=None)` signs only signable buckets and returns anything else unchanged. It uses a cached regional SigV4 client, so signing is a local HMAC computation with no network call.
  - None of these check which org an object key belongs to.
- `temba/settings_common.py`: `S3_PRESIGNED_URL_EXPIRES = 60 * 60` (line 91), the `PERMISSIONS` entry for `flows.flow` (line 525), and `GROUP_PERMISSIONS`. Administrators, Editors and Marketing (an org role, `OrgRole.MARKETING`) hold `flows.flow.*`; Viewers list `flows.flow_editor`, `flows.flow_revisions` and `flows.flow_simulate` explicitly (lines 990–1007). `temba/settings.py.prod` reads the bucket settings and `S3_PRESIGNED_URL_EXPIRES` from the environment (lines 185–201).
- Object key layouts that end up in editor URLs:
  - Flows uploads: `attachments/<org_id>/<flow_id>/steps/<uuid>/<file name>` in `AWS_STORAGE_BUCKET_NAME`.
  - Courier and Mailroom media: `<S3MediaPrefix>/<org_id>/<4 chars>/<4 chars>/<file name>` (`courier/backends/rapidpro/media.go`, `mailroom/core/models/orgs.go` `attachmentPath`). `S3MediaPrefix` defaults to `/media/` in both services and is configurable per deployment.
- `temba/tests/s3.py`: `S3_SIGNING_SETTINGS`, the settings override used by `PresignTest` in `temba/utils/s3/tests.py` and by the message, ticket, API and Mailroom event tests.
- `temba/api/v2/internals/media/views.py`, `S3MediaProxyView`: Keycloak-only (`InternalOIDCAuthentication`), keyed by `project_uuid` and a raw object key, with a 5-minute expiry. The editor runs on the Django session and cannot call it.
- `package.json`: `"@weni/flow-editor": "3.6.5"`.

## Technical Approach

### Components Affected

| Component | Change | Why |
|-----------|--------|-----|
| `temba/utils/s3/s3.py` | modified | Add `is_org_object_key(key, org_id)` and `presign_org_url(url, org_id)`. The org check lives next to the other signing rules so every caller gets the same boundary. |
| `temba/utils/sentry.py` | new | `scrub_events_for_current_request()` and its event processor, which remove the request body and the stack-frame variables from every Sentry event raised while the request is handled. Kept out of `views.py` because nothing in it is specific to flows or media. Tested in `temba/utils/tests.py`. |
| `temba/flows/serializers.py` | new | `MediaUrlsSerializer`, the input boundary: `urls` is a list of 1 to `MAX_MEDIA_URLS_PER_REQUEST` (20) non-blank strings of at most `MAX_MEDIA_URL_LENGTH` (2048) characters. |
| `temba/flows/views.py` | modified | Add `"media_urls"` to `FlowCRUDL.actions` and the `MediaUrls` view. |
| `temba/settings_common.py` | modified | Add `"media_urls"` to the `flows.flow` permissions, `"flows.flow_media_urls"` to Viewers, and `S3_ORG_SCOPED_KEY_PREFIXES = ["attachments", "media"]`. |
| `temba/settings.py.prod` | modified | `S3_ORG_SCOPED_KEY_PREFIXES = env.list("S3_ORG_SCOPED_KEY_PREFIXES", default=["attachments", "media"])`. |
| `templates/flows/flow_editor.haml` | modified | Add `media_urls: '/flow/media_urls/{{object.uuid}}/'` next to `attachments`. |
| `package.json`, `package-lock.json` | modified, in a follow-up PR | Bump `@weni/flow-editor` to 3.7.0 after it is published. Not part of [flows#904](https://github.com/weni-ai/flows/pull/904). |
| `temba/flows/tests.py`, `temba/utils/s3/tests.py` | modified | Flow and unit tests, see **Test Strategy**. |
| `WENI-CHANGELOG.md` | modified | Entry under the version that ships the change. |

### Flow

1. **Editor boot.** `FlowCRUDL.Editor` renders `flow_editor.haml`, whose `endpoints` block now includes `media_urls`. Editor 3.7.0 configures its signing service with it.
2. **Request.** The editor sends `POST /flow/media_urls/<flow_uuid>/` with the session cookie, `X-CSRFToken`, `X-Requested-With: XMLHttpRequest` and `{"urls": [...]}`. Django's `CsrfViewMiddleware` validates the token; the view is not `csrf_exempt`.
3. **Authorization.** `MediaUrls(AllowOnlyActiveFlowMixin, OrgObjPermsMixin, SmartReadView)`, the same base as `Revisions`, with `slug_url_kwarg = "uuid"` and `http_method_names = ["post"]`. Its `dispatch` first registers, on the current Sentry scope, the event processor that removes `request.data` (see **Observability**), then calls `self.has_permission(...)` before anything else and returns `JsonResponse({"error": "Forbidden"}, status=403)` when it fails, instead of smartmin's login redirect, because the caller is an XHR that cannot follow a redirect to an HTML page. `get_object()`, called from `has_permission`, raises `Http404` for an unknown or inactive flow UUID, because `AllowOnlyActiveFlowMixin` filters on `is_active=True`. `dispatch` catches it and returns `JsonResponse({"error": "Not found"}, status=404)`, so the editor never receives Django's HTML 404 page and the response carries `no-store`.
4. **Validation.** `json.loads(request.body)` failing, or `MediaUrlsSerializer(data=...)` being invalid, returns `400` with `{"error": "Invalid request"}`. The serializer errors are not echoed, so no submitted URL is reflected back.
5. **Signing.** For each distinct URL, the view calls `s3.presign_org_url(url, flow.org_id)`:
   - `parse_s3_url(url)` returns `None` for a non-S3 host, so the URL is returned unchanged.
   - A bucket outside `signable_buckets()` is returned unchanged.
   - `is_org_object_key(key, org_id)` is true only when the key starts with `<prefix>/<org_id>/` for a prefix in `S3_ORG_SCOPED_KEY_PREFIXES`, with the prefix stripped of slashes so `/media/` matches `media`, and when no segment of the (already percent-decoded) key is empty, `.` or `..`. Flows, Courier and Mailroom never generate such keys. Refusing them keeps the ownership check from depending on S3 and browsers not resolving dot segments. Anything else is returned unchanged.
   - Otherwise it returns `presign_url(url)`, which uses `S3_PRESIGNED_URL_EXPIRES`. Any query string in the input, such as a stale signature, is ignored by `parse_s3_url` and replaced.
6. **Response.** `200` with `{"urls": {<original>: <signed or unchanged>}, "expires_in": settings.S3_PRESIGNED_URL_EXPIRES}` and `Cache-Control: no-store`. `dispatch` sets the header on every response it returns, errors included (`400`, `403`, `404`, `405`, `500`). The CSRF rejection is produced by the middleware before `dispatch` and does not carry it.
7. **Unexpected failure.** An exception raised while signing (for example a botocore credential or parameter error) is caught in the view, reported once to Sentry as described under **Observability**, and answered with `500` and `{"error": "Internal server error"}`.

### Rejected Alternatives

- **Reuse `S3MediaProxyView`:** it authenticates with a Keycloak bearer token the editor does not have. Accepting the Django session there would mix two trust models in one internal API, and the editor would have to rebuild object keys and know the `project_uuid`.
- **Sign inside existing responses** (the upload response and `Simulate`): this misses URLs already persisted in flow definitions and Say Message recordings, so an endpoint is needed anyway. Signing the upload response would also put expiring URLs into saved definitions.
- **A redirect endpoint used directly as `src`:** following a cross-origin `302` from the browser sends `Origin: null` to S3, as documented in `S3MediaProxyView`. It also gives the editor no expiry to cache against and costs a Flows round trip for every image load and audio range request.
- **Sign any URL in a signable bucket, without the org check:** this turns the endpoint into a signing oracle for every org's media, for anyone who holds a URL from an export, a log or a shared flow. The org segment of the key is the only ownership signal available without an S3 call.
- **Check ownership with `head_object` or object tags:** adds a network call to S3 per URL, plus timeout and retry handling, for no stronger guarantee than the key layout Flows, Courier and Mailroom already enforce.
- **Hard-code the key prefixes:** Courier and Mailroom take `S3MediaPrefix` from their deployment configuration, so Flows must be able to match it without a release.

## Contracts

| Interface | Change | Version impact | Backward compatible |
|-----------|--------|----------------|---------------------|
| `POST /flow/media_urls/<flow_uuid>/` | added | Flows minor | yes. A new route; nothing existing changes. |
| Editor config `endpoints.media_urls` in `flow_editor.haml` | added | Flows minor | yes. Editor 3.6.5 ignores the key; editor 3.7.0 without it keeps today's behavior. |
| Permission `flows.flow_media_urls` | added | Flows minor | yes. Granted to Administrators, Editors, Marketing and Viewers on `migrate`. |
| Setting `S3_ORG_SCOPED_KEY_PREFIXES` | added | Flows minor | yes. Defaults to `["attachments", "media"]`. |
| `@weni/flow-editor` dependency | 3.6.5 → 3.7.0, in a follow-up PR | Flows minor | yes. See the paired spec. The endpoint and the template key work with either editor version. |
| `temba/utils/s3` (`presign_org_url`, `is_org_object_key`) | added | internal | yes. Existing functions are unchanged. |
| Courier and Mailroom versions | unchanged | none | yes. No new version is required. |

**Endpoint contract** (matches the paired floweditor spec):

- **Request:** `POST /flow/media_urls/<flow_uuid>/`, Django session, `X-CSRFToken`, `Content-Type: application/json`, body `{"urls": ["<url>", ...]}` with 1 to 20 strings of at most 2048 characters.
- **Response 200:**

  ```json
  {
    "urls": { "<original url>": "<presigned or unchanged url>" },
    "expires_in": 3600
  }
  ```

  Every distinct requested URL appears as a key. `expires_in` is `S3_PRESIGNED_URL_EXPIRES` in seconds.
- **Response 400:** `{"error": "Invalid request"}`.
- **Response 403:** `{"error": "Forbidden"}` for an anonymous user, a missing permission or another org's flow. A missing CSRF token gets Django's CSRF failure response, also `403`.
- **Response 404:** `{"error": "Not found"}` for an unknown or inactive flow.
- **Response 405:** any method other than `POST`.
- **Response 500:** `{"error": "Internal server error"}`.
- **All responses produced by the view:** `Cache-Control: no-store`. The CSRF rejection comes from Django's middleware and does not carry it.

**Consumers affected**: only the flow editor page served by Flows. The paired floweditor spec describes the endpoint as following "the `OrgObjPermsMixin` behavior of `UploadMediaAction`" for `403` and `404`; this view returns `403` and `404` JSON responses instead of that mixin's login redirect and Django's HTML 404 page, which is what the editor's contract expects.

## Data Model and Migrations

No model or schema change, and no migration file. The `flows.flow_media_urls` permission and its group assignments are created by smartmin's `post_migrate` handler from `PERMISSIONS` and `GROUP_PERMISSIONS`, so the deploy MUST run `manage.py migrate` as it does on every release. The previously deployed version keeps working against the same database: it never reads the new permission.

## Non-Functional Requirements

### Peak Load

- **Measured baseline:** the busiest hour of `POST /flow/simulate/` in production over the last 7 days (2026-10-21 to 2026-10-28, Loki `container="flows"`, cluster `production`) was **10 requests per hour**. Editor-open counts could not be extracted in the same window because the 7-day Loki query timed out; the Ireland and Mumbai log datasources were not measured.
- **Requests generated per use:** per the paired spec, the editor sends at most one batched request per simulator message with media, one per distinct attachment clicked, and one per distinct recording played, each cached for about an hour per tab.
- **Declared peak:** **600 requests per hour** on `/flow/media_urls/` during the busiest weekday hour, with bursts of up to **5 requests per second** from a single tab when a simulator response renders several media messages. That is 60 times the measured simulator peak, which covers multi-message responses, downloads and audio plays with margin.
- **Cost per request:** the `OrgObjPermsMixin` flow lookup (one indexed query by UUID, run once for the permission check and once for the view), plus up to 20 local SigV4 HMAC computations. There is no network call to S3. At the declared peak this is negligible next to the existing `/flow/revisions/` and `/flow/activity/` polling, so no rate limit, cache or extra capacity is added.
- **Statelessness:** the view keeps no state between requests. The signing client cached by `regional_client` holds only configuration and credentials, which are identical in every process.

### Observability

- **Success path:** no application log line. The access log already records method, path, status and size, and it contains no request or response body.
- **Never logged or reported:** no original URL, object key, file name or signed URL appears in a log message, a Sentry tag, an extra or a breadcrumb added by this view. Signed URLs are bearer credentials and file names can contain personal data.
- **Request-body scrubbing (AC-5):** the first thing `dispatch` does is add an event processor to the current Sentry scope (`with sentry_sdk.configure_scope() as scope: scope.add_event_processor(...)`) that removes `request.data` from the event. Because the Django integration gives each request its own scope, the processor applies to every event raised while this request is handled: the signing-failure report, and also an unhandled error in the flow lookup, the permission check or body parsing. It applies to nothing outside this view.
- **Failure report (AC-7):** inside `sentry_sdk.push_scope()` the view sets the tags `feature: media-signing` and `org_id`, the extras `flow_uuid` and `url_count`, and calls `logger.exception("media url signing failed")`. The request-scope processor removes the body from it. The Django integration attaches the user identifier.
- **Correlation:** the editor's signing request carries `sentry-trace` and `baggage` from its `browserTracingIntegration`. `sentry-sdk` 1.45 continues that trace in the Django integration even with `traces_sample_rate=0`, so a Flows error carries the same `trace_id` as the editor error that triggered it.
- **Known platform issue:** `DjangoIntegration()` at its default body capture, together with `send_default_pii=True` in `temba/settings_common.py`, attaches request bodies and user details to every event. The request-scope processor keeps submitted URLs out of every event this view raises. Platform-wide body capture and the user-details part stay under `TODO(SENTRY_PII)` and are not changed here.

### Failure Handling

- **External dependencies:** none are called. Signing is local, and the flow lookup uses PostgreSQL through Django with the existing connection settings. Principle XI does not apply: Flows propagates nothing to another service.
- **Invalid input:** rejected at the serializer with `400` before any signing (AC-4).
- **Authorization failure:** `403` JSON, or `404` JSON for an unknown flow, before the body is parsed (AC-3).
- **Signing failure:** caught, reported once, answered with a generic `500` (AC-7). The editor falls back to the original URL and does not retry automatically, as its spec states.
- **Idempotency:** the operation reads nothing but the flow and writes nothing, so repeated calls are safe. Each call returns new signatures for the same objects.
- **Expiry:** signatures expire after `S3_PRESIGNED_URL_EXPIRES`. The editor refreshes them before that; Flows keeps no record of issued URLs.

### Security and Authorization

- **Trust boundary:** the request body comes from the browser and is untrusted. The serializer enforces type, count and length. The URLs themselves are only parsed, never fetched, so there is no server-side request forgery surface.
- **Authorization:** the session user must hold `flows.flow_media_urls` in the flow's org (`OrgObjPermsMixin`). The org roles that hold it are Administrators, Editors, Marketing and Viewers, which are exactly the roles that can open the editor (`flows.flow_editor`). The org of the flow, not anything in the body, decides which object keys may be signed.
- **Ownership:** a key is signed only when it starts with `<prefix>/<flow.org_id>/` for a configured prefix, contains no empty, `.` or `..` segment, and its bucket is signable. A URL with another org's ID, a key outside the prefixes (for example archives or exports), a key that could walk out of the org's prefix such as `media/<org_id>/../<other_org_id>/...`, or an unknown bucket is returned unchanged and stays private.
- **Global permission holders:** `OrgObjPermsMixin` lets a user with the permission granted globally pass for any org. `flows.flow_media_urls` is not added to Customer Support or any other global group, so only org members can sign.
- **CSRF:** enforced by Django's middleware; the view is not `csrf_exempt`.
- **Caching:** `Cache-Control: no-store` on every response the view produces keeps signed URLs out of browser and proxy caches. The CSRF rejection, which never contains a URL, is the only response of the route without it.
- **Secrets:** none added. The existing `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` sign the URLs.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-1: own-org URLs are signed | `temba/flows/tests.py`, next to `test_upload_media_action`, under `override_settings(**S3_SIGNING_SETTINGS)`: post an `attachments/<org_id>/...` URL in `static-bucket` and a `media/<org_id>/...` URL in `media-bucket`. Assert `200`, both keys present, values carry `X-Amz-Signature` and `X-Amz-Expires=600`, and `expires_in == 600`. |
| AC-2: other URLs are returned unchanged | Same test class: another org's ID, a key under `archives/`, an unknown bucket, `https://floweditor-assets.temba.io/...` and a non-S3 host all come back identical. `temba/utils/s3/tests.py` (`PresignTest`) covers `is_org_object_key` with `/media/` and `media` prefixes, a prefix that only shares a leading substring (`media2/`), an org ID that only shares a prefix (`1` against `12`), a key with nothing after the org ID, and keys with a `..` segment, a `.` segment, an empty segment (`//`) and a percent-encoded `%2E%2E` segment in the URL (decoded by `parse_s3_url`). The view test posts a `media/<org_id>/../<org2_id>/...` URL and asserts it comes back unchanged. |
| AC-3: authorization | Anonymous, a user outside the org and a flow in `self.org2` get `403` with a JSON body and no `Location` header. An unknown UUID and an inactive flow get `404` with `{"error": "Not found"}`. Admin, editor, viewer and a user added to the org with `OrgRole.MARKETING` get `200`. Agent and surveyor get `403`. |
| AC-4: input validation | Invalid JSON, `{}`, `{"urls": "x"}`, `[]`, 21 URLs and a 2049-character URL get `400`. `GET` gets `405`. A `Client(enforce_csrf_checks=True)` post without the token gets `403`. Each case asserts that `presign_url` was not called. |
| AC-5: no caching and no URL in logs or Sentry | Every response above asserts `Cache-Control: no-store`, except the CSRF rejection, which asserts only the `403`. `assertLogs` on the view's logger during a success and a failure call shows no submitted or signed URL. With a Sentry transport stub capturing events, an exception raised from the flow lookup (patched `get_object`) produces an event with no `request.data` and no submitted URL anywhere in its payload. The AC-7 event is checked the same way. |
| AC-6: the editor gets the endpoint | The editor view test asserts the rendered page contains `media_urls: '/flow/media_urls/<flow uuid>/'`. Manual staging check of the three editor surfaces, see **Rollout**. |
| AC-7: failure handling | Patch `regional_client(...).generate_presigned_url` to raise `botocore.exceptions.NoCredentialsError`. Assert `500` with the generic body, that no traceback is in the response, and that `logger.exception` was called once with the tags and extras and without URLs. |

**Flow coverage** (Principle XIV): one test runs the complete use case. It uploads a file through `flows.flow_upload_media_action`, posts the returned canonical URL to `flows.flow_media_urls` for the same flow, and asserts that the response maps it to a presigned URL for the same bucket and key. The same test then posts it to a flow in `self.org2` with an `org2` user and asserts it is returned unchanged.

**Failure paths covered**: unauthenticated, wrong org, missing permission, unknown flow, invalid body in each shape listed under AC-4, wrong method, missing CSRF, foreign or unsignable URLs, and a signing exception.

**Stubbed at the boundary**: S3 is not reached in any test. `presign_url` signs locally with the fake keys in `S3_SIGNING_SETTINGS`; only the AC-7 test patches the botocore client to raise. Nothing inside the view or the `s3` helpers is mocked.

**Gates**: `poetry run coverage run manage.py test temba.flows temba.utils.s3`, a clean `./code_check.py`, and green `.github/workflows/ci.yml`. No `# pragma: no cover` is added.

## Rollout and Rollback

1. **Floweditor 3.7.0 is released first** or in parallel. Without `media_urls` in the config it behaves like 3.6.5.
2. **Before deploying Flows**, confirm the `S3MediaPrefix` used by Courier and Mailroom in each production deployment. If it is not `attachments` or `media`, set `S3_ORG_SCOPED_KEY_PREFIXES` in the Flows environment to include it. Otherwise inbound media in the simulator is returned unsigned and the editor falls back to the original URL.
3. **Deploy Flows** with the endpoint and the template key ([flows#904](https://github.com/weni-ai/flows/pull/904)), and run `migrate` so the permission exists. Editor 3.6.5 ignores the new key, so this deploy changes nothing visible. Then merge and deploy the follow-up PR that bumps `@weni/flow-editor` to 3.7.0, which turns signing on in the editor.
4. **Validate in staging against the private bucket:**
   - download an uploaded attachment from Send Message;
   - run the simulator with an image, a video, a document and an audio sent by the flow;
   - play a Say Message recording on an IVR flow;
   - as a Viewer, repeat the simulator check;
   - inspect a saved revision and confirm the attachments still hold canonical URLs;
   - post another org's URL to the endpoint and confirm it comes back unchanged.
5. **Rollback:** remove `media_urls` from `flow_editor.haml`, or revert the `@weni/flow-editor` bump to 3.6.5. Either one disables signing in the editor while the endpoint stays harmless. A full revert of the Flows change is also safe: nothing is persisted, and the leftover permission row is unused.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | Delivered through a PR to `main` with an approved review and green `ci.yml`. | none |
| II. Security and Secrets | No new secret or dependency. Least privilege: signing is limited to org members and org-owned keys, and no global group receives the permission. | none |
| III. Observability | No URL in any log or in any Sentry event the view raises (request-scope body scrubbing). The failure report carries the org ID, flow UUID, URL count and the editor's trace. | none |
| IV. Versioned Contracts | The new route, config key, permission and setting are listed under Contracts as backward-compatible minor additions. No Courier or Mailroom version change is required. | The route is an editor-internal Django view, not under `temba/api`, so it has no API version of its own; it is versioned through the Flows release and the paired editor release. |
| V. Specification Traceability | Opens with `## Origin Without Product Spec` in the mandated format, matching the paired floweditor spec. | none |
| VI. No Silent Divergence | Not applicable: there is no Product Spec. | none |
| VII. Commit Messages | Atomic `feat:`, `test:`, `chore:` and `docs:` commits of at most 50 characters. | none |
| VIII. Changelog Maintenance | One bullet in `WENI-CHANGELOG.md` under the shipping version: `fix: sign media URLs in the flow editor and simulator through /flow/media_urls/`. The bullet says it is security-relevant because it restricts signing to the flow's org. | none |
| IX. Never Trust the Client | `MediaUrlsSerializer` validates the body; authorization is checked server-side on the flow's org; ownership is checked per key. The view is thin; signing rules live in `temba/utils/s3`. | `temba/flows` has no `usecases/` layer, so the logic goes into the existing `s3` module rather than a new layer. |
| X. Fail Gracefully | Every failure returns a defined JSON status with no stack trace. No external call is made, so no new timeout is needed. | none |
| XI. Bounded Retry Over REST | Not triggered: Flows sends nothing to another service. | none |
| XII. Scalability and Peak Load | Stateless view. Peak declared as 600 requests per hour, bursting to 5 per second, against a measured simulator peak of 10 per hour. | none |
| XIII. Diagnosable Errors | The failure event carries the org ID, the user ID from the Django integration, and the trace ID; no URL or file name. | `send_default_pii=True` still attaches user details platform-wide; that stays under `TODO(SENTRY_PII)` and this view removes the request body from every event raised while it handles a request. |
| XIV. Tests Exercise Flows | An upload-then-sign flow test plus per-criterion view tests and `s3` unit tests, success and failure paths, with `TembaTest`. | none |
| XV. Explicit Over Clever | `MAX_MEDIA_URLS_PER_REQUEST`, `MAX_MEDIA_URL_LENGTH` and `S3_ORG_SCOPED_KEY_PREFIXES` are named. A comment on the `dispatch` override explains why it returns `403` instead of a redirect. | none |
| XVI. Contained Changes | Only the files listed under Components Affected change. `UploadMediaAction`, `Simulate` and `S3MediaProxyView` are left as they are. | none |
| Backend Standards | Black at 119 columns, isort and flake8 through `./code_check.py`. No new user-facing string, so no locale change. | none |

## Implementation Decisions

- **Scope by flow UUID**, as the editor's other endpoints do (`revisions`, `upload_media_action`). The editor needs no project UUID, and the flow's org decides ownership.
- **Ownership is org-wide, not flow-wide.** A flow can send media uploaded in another flow of the same org, for example after a copy, so the flow ID segment of `attachments/<org>/<flow>/...` is not checked.
- **Media copied from another org is not signed.** A flow imported from another org keeps URLs with the source org's ID. The editor shows the fallback for them; Mailroom still signs them at send time. Re-uploading the file in the destination org fixes the preview. This keeps the endpoint from signing for other orgs.
- **Default prefixes are `attachments` and `media`.** `attachments` covers Flows uploads, and `media` is the default `S3MediaPrefix` of Courier and Mailroom. `recordings/` is left out, because `UploadActionRecording` returns a relative path that never reaches the editor as a URL.
- **`403` JSON instead of a login redirect**, following `Revisions.post`, because the editor cannot act on a redirect to an HTML login page.
- **Viewers and Marketing can sign**, because they can open the editor and run the simulator. Marketing receives it through its `flows.flow.*` wildcard; excluding it would mean replacing that wildcard with an explicit list. Customer Support is not granted the permission (see Security).
- **Expiry follows `S3_PRESIGNED_URL_EXPIRES`** (3600 s by default) rather than the 5 minutes of `S3MediaProxyView`. The editor caches against `expires_in` and refreshes early, and a longer validity keeps a playing video from failing mid-stream.
- **Duplicate URLs in one request are signed once**, and the response map naturally holds one entry per distinct URL.

## Open Questions

None. The endpoint shape was fixed by the paired floweditor spec. The prefix configuration is a rollout check (step 2), not an open design choice.
