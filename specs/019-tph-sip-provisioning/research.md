# Research: Provision customer SIP credentials on TPH channel creation

**Spec**: [spec.md](spec.md) | **Date**: 2026-11-17

Each entry records a decision, why, and what was rejected. Facts about this repository were checked in the code on `main` at `8a3266429`. Facts about KubeVoIP come from the operator CRDs in `kubernetes-manifests/kubevoip-operator/base/platform-crds-v0.6.9.yaml` and the manifests in `kubernetes-manifests-platform/kubevoip`.

## R1. HTTP client for the Kubernetes API (OQ-11)

- **Decision**: a minimal client in `temba/channels/types/telephony/kubernetes_client.py`, on `requests`, with five operations: `create`, `get`, `list_by_label`, `delete`, `merge_patch`.
- **Rationale**: `requests` is already imported by 62 modules of Flows and installed, so no dependency is added (Principle II asks that a dependency touching authentication be named; there is none). The surface is five calls on a stable API, and the in-cluster authentication is a token file plus a CA file.
- **Alternatives rejected**: the official `kubernetes` Python package (large, brings a new authentication stack and a transitive dependency tree for five calls); `httpx` (installed, but Flows channel code uses `requests`); shelling out to `kubectl` (no binary in the image, no timeout control).

## R2. In-cluster authentication

- **Decision**: host from `KUBERNETES_SERVICE_HOST` and `KUBERNETES_SERVICE_PORT`; bearer token read from `/var/run/secrets/kubernetes.io/serviceaccount/token` on every request; CA bundle `/var/run/secrets/kubernetes.io/serviceaccount/ca.crt` passed as `verify`. Paths are constants.
- **Rationale**: projected service account tokens rotate, so reading the file per request avoids using an expired token. TLS verification stays on (FR-017).
- **Risk**: the `flows` service account must be mounted in the web and Celery pods that run claim and tasks. The ServiceAccount exists (`serviceaccount-flows.yaml`) and the Celery deployments set `serviceAccountName: flows`; the web `rollout.yaml` must be confirmed during staging validation (task T-STG-1).
- **Local and test**: when the token file does not exist the client raises a clear configuration error. Tests never reach this path because they inject the fake client.

## R3. Retry policy (Principle XI)

- **Decision**: at most 3 attempts, exponential backoff starting at 0.2 s, only for connection error, timeout, HTTP 5xx and 429. No retry for 4xx. Timeout per request from `TPH_SIP_K8S_TIMEOUT_SECS` (default 5).
- **Rationale**: every operation is idempotent by name and label (R4), so retry is safe. The claim is synchronous in a web request, so the worst case (3 attempts of 5 s plus backoff on each of 5 calls) is bounded and checked against the web timeout in the plan risks.
- **Rejected**: `urllib3.Retry` on a session adapter, because it also retries non-idempotent methods unless configured, and hides which attempts happened from the logs.

## R4. Names, labels and idempotency

- **Decision**: every object is named `tph-<channel uuid without hyphens>` (36 characters). Labels: `weni.ai/managed-by: flows` and `weni.ai/channel-uuid: <uuid>`. `authUsername` equals the resource name.
- **Rationale**: the SIP user `authUsername` pattern is `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$` up to 40 characters; the name fits and does not reveal the project or number. Labels allow listing by selector for reconciliation and revocation. On `409`, the client reads the object and compares the `weni.ai/channel-uuid` label: same channel is success, other channel is failure (FR-005).
- **Rejected**: names derived from the DID (leaks the number, changes if the DID is edited); one object name per kind prefix (`sipuser-...`) which would add nothing the kind does not already say.
- **GitOps tracking (FR-018)**: objects carry only the two labels above, not `app.kubernetes.io/instance`, not the kustomize `commonLabels` (`team`, `track`). The ApplicationSet has automated sync disabled today, and labels keep it safe if that changes.

## R5. Credential store

- **Decision**: one Secret, `voice-mode-tph-credentials` (name from `TPH_SIP_CREDENTIALS_SECRET`), created empty by the platform team. Flows only `get`s and merge-patches it: `{"data": {"tph-<id>": "<base64 password>"}}` to set and `{"data": {"tph-<id>": null}}` to remove.
- **Rationale**: SEC-01. A Secret per channel would need `create` and `delete` on Secrets, which RBAC cannot narrow by name for `create`. With a single named Secret the grant is `get` and `patch` with `resourceNames`. The 1 MiB Secret limit holds thousands of 36-character keys with 32-character values (OQ-10).
- **Failure**: a `404` on patch means the Secret was not created. The provisioner raises a configuration error (no retry) and the claim fails with the generic error.
- **Caveat**: the SIP user `passwordSecretRef.key` must accept this key name. Key names allow letters, digits, `-`, `_`, `.`.

## R6. Password generation and the first password

- **Decision**: `secrets.token_urlsafe(24)` (32 characters), constant `SIP_PASSWORD_BYTES = 24`. At provisioning, a password nobody sees is written so the SIP user has a valid reference. The issue endpoint rotates it and returns the new one.
- **Rationale**: the claim goes through `CreateChannelSerializer` in `weni-rp-apps`, which returns the channel `config` to the integrations service; delivering the password there is not an option and would put it in a response that is logged by intermediaries. A separate, explicit, authorized call is the only place the password is shown (FR-006, SEC-06).
- **Rejected**: returning the password in the claim response; storing it encrypted in Flows to allow showing it again (widens the attack surface and needs a key management decision, OQ-05).

## R7. Per-channel issue limit

- **Decision**: Redis counter with `INCR` and `EXPIRE` on key `tph-sip-credentials:<channel uuid>`, window `SIP_CREDENTIALS_WINDOW_SECS = 3600`, limit `SIP_CREDENTIALS_MAX_ISSUES = 5` (settings-overridable). Over the limit returns `429`.
- **Rationale**: Flows web is stateless (Principle XII), and Redis is the shared store it already uses via `django_redis.get_redis_connection`. The limit stops a leaked internal token from rotating a customer's password in a loop and causing an outage.
- **Rejected**: counting rows in a database table (needs a migration for little value); per-process memory (breaks under multiple pods).

## R8. SIP user extension

- **Decision**: `TPH_SIP_EXTENSION_PREFIX` (default `9`) followed by `channel.id` left-padded with zeros to a total of `SIP_EXTENSION_LENGTH = 12` digits.
- **Rationale**: the CRD requires digits only, up to 20. It must be unique on the gateway. The channel's database id is unique and stable. The extension is not shown to the customer.
- **Risk**: confirm with the cloud team that the gateway does not need the extension to be globally unique across other `SIPUser` objects (`6001`, `151486001`); the prefix keeps TPH extensions out of those ranges.

## R9. DID in the route match (OQ-03)

- **Decision**: the call route `match.calledNumber` is the channel address with every non-digit removed (`+5511912345678` becomes `5511912345678`). The helper `normalize_did_for_route(address)` is the single place where this rule lives. The connection data returns that same value as `did`, the number the PBX must dial.
- **Rationale**: PBXs and carriers commonly send the number without `+`. The Asterisk dialplan already extracts the DID from `To` and sends it to `/telephony/sessions`; how Courier resolves that value against the channel address is outside this repository and must be checked in staging.
- **Open**: if the PBX sends a national or different prefix form, the route can have its match widened per channel in a later change, without touching other channels.

## R10. Connection data from configuration

- **Decision**: all connection data except the user name, the DID and the status comes from settings: `TPH_SIP_DOMAIN`, `TPH_SIP_TRANSPORTS` (comma separated `protocol:port`), `TPH_SIP_SIGNALING_IPS`, `TPH_SIP_MEDIA_IPS`, `TPH_SIP_RTP_PORT_RANGE`, `TPH_SIP_CODECS`, `TPH_SIP_DTMF_MODE`. IP lists default to empty.
- **Rationale**: reading `Service` or `SIPGateway` objects would require extra RBAC (SEC-01) and a load balancer address without a fixed IP is not something to promise to a customer (OQ-04).

## R11. Provisioning status mapping

- **Decision**: read `status.phase` of the SIP user and map through a constant table: a documented "ready" value maps to `ready`, a documented error value maps to `error`, absence or any other value maps to `pending`.
- **Unknown**: the CRD schema preserves unknown status fields, and the exact phase strings the operator writes are not in the CRDs. They must be read from a SIP user in staging (task T-STG-2) and written into the mapping constant. Until then unknown values map to `pending`, which is the safe default for the customer screen.

## R12. Endpoint names, authentication and authorization

- **Decision**: flat paths, matching the neighbors in `temba/api/v2/internals/channels/urls.py`: `GET /api/v2/internals/channel_sip_connection` and `POST /api/v2/internals/channel_sip_credentials`, with `channel_uuid` and `project_uuid` as parameters (query for GET, JSON body for POST). Authentication and permission classes are the same as `InternalChannelView` (`WeniAuthentication`, `InternalOIDCAuthentication`; `CanCommunicateInternally | (IsAuthenticated & IsUserInOrg)`).
- **Rationale**: `InternalChannelView` is the internals endpoint the integrations service already calls with these credentials. The existing neighbors do not use per-channel URLs. This differs from the earlier draft in `docs/plans`, which proposed `/channels/<uuid>/telephony/...`; the contract is the one in `contracts/`.
- **Authorization**: the use case loads the channel by `uuid` and `org=<org of project_uuid>`, `is_active=True`, `channel_type="TPH"`. Any miss is the same `404` (FR-009). The project administrator check for the end user is done by the integrations service before calling; Flows additionally verifies the channel belongs to the project, so a stolen internal token cannot cross projects by guessing UUIDs without also knowing the project.
- **Throttling**: no DRF throttle (the neighbors disable it); the per-channel Redis limit of R7 applies to issue only.

## R13. Activation and release hooks

- **Decision**: implement `TelephonyPSTNType.activate(channel)` and `deactivate(channel)`. Keep `async_activation = False`.
- **Rationale**: `Channel.create` calls `activate` synchronously and, on any exception, calls `channel.release(user)` and re-raises (`temba/channels/models.py`). That gives the claim its rollback for free. `Channel.release` calls `deactivate` and logs exceptions without aborting. `release` therefore also triggers a best-effort deprovision after a failed `activate`, which makes cleanup idempotent twice over.
- **Config write**: `activate` updates `channel.config` with the non-sensitive SIP metadata and saves `config` only.

## R14. Reconciliation task

- **Decision**: `reconcile_tph_sip_task` in `temba/channels/tasks.py`, a `nonoverlapping_task` scheduled every 900 seconds in `CELERY_BEAT_SCHEDULE`. Listing is by label selector, one request per kind.
- **Rationale**: FR-013 requires that a failed revocation is corrected. A lock avoids two runs deleting the same objects. The task runs only when the flag is on (FR-015); revocation on release does not depend on it.
- **Safety**: only objects with `weni.ai/managed-by: flows` are examined. A cap `RECONCILE_MAX_DELETIONS_PER_RUN` (default 50) stops a bug (for example, an empty channel table in the wrong database) from deleting every customer credential; hitting the cap logs an error and stops.

## R15. Management command

- **Decision**: `temba/channels/management/commands/provision_tph_sip.py --channel <uuid>`. It calls the same `SIPProvisioner.provision` and skips channels that already have `sip_resource_name`.
- **Rationale**: channels created before this feature must not be changed automatically (consistent with `012-tph-voice-config`).

## R16. Logging, metrics and Sentry

- **Decision**: module loggers (`logging.getLogger(__name__)`) with structured extras: `org_id`, `channel_uuid`, `user_id`, `resource_name`, `outcome`. Never the password, the DID or the caller. Failures captured to Sentry carry the same opaque identifiers (Principle XIII). Outcomes are reported as structured log events. `django-prometheus` is a dependency, but no module under `temba/channels` or `temba/utils` defines custom counters today, so adding a metrics pattern is out of scope here (Principle XVI); the log events carry an `outcome` field that can feed log-based alerts.
- **Audit**: issue emits one `info` record `tph sip: password issued`.

## R17. Release and versioning

- **Decision**: additive minor release. Version number is the next free minor in `WENI-CHANGELOG.md` at merge time (3.113.0 already exists as a staging tag on 2026-11-17, so confirm before editing the changelog). The entry is marked as a security-relevant change. No migration. The Courier and Mailroom versions required are the current ones; they ignore unknown `config` keys.

## R18. Reconciliation must not race a claim in progress

- **Problem**: the claim runs inside the request transaction (`ATOMIC_REQUESTS`), so its cluster objects exist before the channel row is visible to other connections. A reconciliation run in that window would see "objects without an active channel" and delete a channel that is being created.
- **Decision**: the reconciliation skips any channel group whose newest object is younger than `RECONCILE_MIN_AGE_SECS` (600). The age comes from the cluster `creationTimestamp`, not from the database or the local clock of an object. An unreadable timestamp counts as young. Objects of an active TPH channel that is not marked provisioned are never deleted, since they may belong to a claim whose config save failed.
- **Password on recreation**: when only the SIP user is missing and its password key still exists in the Secret, the password the customer already holds still works, so no reset is requested. A reset is flagged only when the key had to be created again (for example after a cluster rebuild).

## R19. A provisioning failure during the claim

- **Decision**: `Channel.create` already releases the channel and re-raises. The claim view wraps the creation in a savepoint and turns `SIPProvisioningError` into a form error on `phone_number` ("We could not set up the SIP connection... try again in a few minutes"). The customer sees a retryable message instead of a 500, nothing from the cluster is shown, and no inactive channel row is left behind.

## Items to confirm in staging (not blockers for coding)

| ID | Confirm | Where it lands |
|----|---------|----------------|
| T-STG-1 | The web pods that run the claim mount the `flows` service account token | RBAC task and quickstart |
| T-STG-2 | Exact `status.phase` strings of a healthy and a failing SIP user | `SIP_USER_READY_PHASES` and `SIP_USER_ERROR_PHASES` constant |
| T-STG-3 | DID format the PBX sends and how Courier resolves it | `normalize_did_for_route` |
| T-STG-4 | Dial policy isolation and no outbound through a trunk (OQ-01) | Manual staging checks in the spec |
