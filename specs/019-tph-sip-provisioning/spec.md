# Feature Specification: Provision customer SIP credentials on TPH channel creation

**Feature Branch**: `feat/019-tph-sip-provisioning`

**Created**: 2026-11-17

**Status**: Draft

**Cycle**: SDD Full (adds behavior to a channel type, adds public internals endpoints, adds channel-config keys consumed outside Flows, and needs coordination with other repositories)

**Input**: User description: "When a TPH (PSTN telephony) channel is created, create the matching SIP credential for that customer in our Asterisk/KubeVoIP infrastructure through the Kubernetes API, and return to the customer the data needed to point their PBX at our infrastructure (domain, user, password, IPs, codecs). Security comes first."

## Inheritance from Product Spec

- Product Spec: Voice Mode for Telephony — https://github.com/weni-ai/vtex-cx-engine-specs/blob/b977cb60859d2238eb57f0b6ea3ad173aff4a6f4/specs/004-voice-mode-telephony/spec.md
- Pinned version: `b977cb60859d2238eb57f0b6ea3ad173aff4a6f4`
- Architecture doc: none (a cross-repository architecture document is tracked as OQ-12)
- Inherited binding decisions: BD-010 (PSTN is channel type TPH, the DID is the channel address and resolves channel and tenant), FR-035 (a call is attributed by the dialed number in the SIP `To`/Request-URI and the caller ID in `From`)
- Scope of this spec: the Flows slice only. On TPH channel creation, provision an isolated SIP credential for that channel in KubeVoIP, expose the PBX connection data to an authorized internal caller, and revoke everything when the channel is released.
- Divergences: the product spec lists "Telephony number provisioning, carrier/VoIP-provider contracts, and SIP trunk procurement" as out of scope and says number provisioning and trunking are "handled outside this spec". This feature brings customer PBX connection into the platform. Amendment in `vtex-cx-engine-specs`: **pending, no link yet** (see Divergences). Until the amendment is tagged, the feature ships disabled in production behind `TPH_SIP_PROVISIONING_ENABLED=false`.

## Context

Voice Mode already answers calls that arrive at the Asterisk pool through KubeVoIP (`SIPGateway voice-mode`, Kamailio and Asterisk, manifests in `kubernetes-manifests-platform/kubevoip`). Today the only ways in are the NVoip trunk and two hand-written test `SIPUser` objects. A customer who wants their own number answered by the voice agent needs someone to write YAML and hand over a credential out of band. The cloud team does not allow per-customer changes in their repository, and the KubeVoIP manifests have moved to the Engine team's repository (CLOUDW-4779), which makes the Kubernetes API the right way to create per-customer objects.

The KubeVoIP operator reconciles any `SIPUser` in the `kubevoip` namespace, whether it came from Git or from the API. What is missing is a component that creates those objects safely at channel creation, and the permission for Flows to do so (CLOUDW-4780, not started).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A new TPH channel gets its own isolated SIP credential (Priority: P1)

An org admin creates a PSTN telephony channel with name, country and DID, as today. When the channel is created, the platform also creates, in the voice infrastructure, a SIP user and the call-routing objects that belong only to that channel. The admin does not fill in any new field.

**Why this priority**: Without the per-channel credential and its isolation, there is nothing to hand to the customer, and a shared credential would let one customer reach another customer's number.

**Independent Test**: Create a TPH channel with the provisioning flag on and a fake Kubernetes client. Assert that the five expected objects were created with the channel's identifiers, that the call route matches only that channel's DID, that the SIP user does not reference the shared internal dial policy, and that no password is stored on the channel.

**Acceptance Scenarios**:

1. **Given** provisioning is enabled, **When** an admin creates a TPH channel with a valid DID, **Then** a SIP user, a call scope, a dial policy, a call route and a credential entry exist for that channel, all named from the channel UUID and labeled as managed by Flows.
2. **Given** the channel was created, **When** inspecting the channel configuration, **Then** it contains only non-sensitive SIP metadata (user name, extension, resource name) and no password.
3. **Given** provisioning is enabled but the cluster refuses one of the objects, **When** the admin submits the claim, **Then** objects already created are removed, no channel remains, and the admin sees a generic error.
4. **Given** provisioning is disabled, **When** an admin creates a TPH channel, **Then** the channel is created exactly as today and no cluster call is made.

---

### User Story 2 - The customer receives the data needed to connect their PBX (Priority: P1)

After the channel exists, an authorized internal caller (the integrations service acting for a project administrator) can read the connection data for the channel: SIP domain, transports and ports, user name, the DID the PBX must send, signaling and media IPs, media port range, codecs and DTMF mode, plus the provisioning status. To obtain a password it asks the platform to issue one, and the password is returned only in that response.

**Why this priority**: Provisioning is useless to the customer unless the connection data and the password reach them.

**Independent Test**: Call the connection endpoint for a provisioned channel and assert the response has no password. Call the issue endpoint and assert the password appears once, is not in the channel config, logs or database, and that a second issue returns a different password.

**Acceptance Scenarios**:

1. **Given** a provisioned TPH channel, **When** an authorized caller requests the connection data, **Then** it receives the domain, transports, user name, DID, IPs, media port range, codecs and DTMF mode, and a status of `pending`, `ready` or `error`, and no password.
2. **Given** a provisioned TPH channel, **When** an authorized caller requests a password, **Then** it receives a newly generated password once, with a response that must not be cached.
3. **Given** a password was issued, **When** another one is requested, **Then** the previous password stops being valid and a different one is returned.
4. **Given** a channel of another project, an inactive channel, or a channel of another type, **When** a caller requests either endpoint, **Then** the response is the same `404` in all three cases and no cluster call is made.
5. **Given** the issue limit per channel and hour was reached, **When** another password is requested, **Then** the response is `429` and nothing changes in the cluster.

---

### User Story 3 - Removing the channel revokes the credential (Priority: P1)

When a TPH channel is released, the credential and every routing object created for it are removed from the cluster, so a removed customer can no longer register or call.

**Why this priority**: An orphan credential is a standing way into the voice infrastructure.

**Independent Test**: Release a provisioned channel with the fake client and assert all five objects are deleted. Make the cluster fail during release and assert the release still completes and a later reconciliation deletes the leftovers.

**Acceptance Scenarios**:

1. **Given** a provisioned channel, **When** it is released, **Then** the SIP user, call route, dial policy, call scope and credential entry are deleted.
2. **Given** the cluster is unreachable during release, **When** the channel is released, **Then** the release completes, the failure is logged, and a later reconciliation removes the leftover objects.
3. **Given** some objects were already gone, **When** the channel is released, **Then** the missing ones are treated as already deleted.

---

### User Story 4 - Leftovers and drift are corrected automatically (Priority: P2)

A periodic task compares cluster objects managed by Flows with the channels in the database. It removes objects of inactive or unknown channels. It recreates the objects of an active channel whose SIP user disappeared (for example after a cluster rebuild) and flags the channel so the customer is asked to issue a new password.

**Why this priority**: Without it, a failed revocation or a rebuilt cluster silently leaves credentials orphaned or customers without service.

**Independent Test**: Seed the fake client with objects of an inactive channel and of an active channel missing its SIP user, run the task, and assert the first set is deleted and the second is recreated and flagged.

**Acceptance Scenarios**:

1. **Given** objects labeled for a channel that is inactive or does not exist, **When** the task runs, **Then** they are deleted.
2. **Given** an active provisioned channel whose SIP user is missing, **When** the task runs, **Then** its objects are recreated with a new unusable-until-issued password and the channel is flagged as needing a new password.
3. **Given** objects without the Flows-managed label, **When** the task runs, **Then** they are never touched.

---

### User Story 5 - Existing TPH channels can be provisioned on demand (Priority: P3)

An operator can provision a TPH channel that was created before this feature, one at a time, with a management command.

**Why this priority**: Channels created earlier have no credential; the feature must not rewrite them automatically.

**Independent Test**: Run the command against a TPH channel without SIP metadata and assert it is provisioned; run it again and assert nothing changes.

**Acceptance Scenarios**:

1. **Given** a TPH channel created before this feature, **When** the command runs for that channel, **Then** it is provisioned like a new one.
2. **Given** a channel that is already provisioned, **When** the command runs again, **Then** it makes no change.

---

### Edge Cases

- The cluster is slow or unavailable while the claim runs: the claim fails with a generic error after bounded retries and leaves no channel and no objects behind.
- An object with the expected name already exists: if it carries the same channel label it counts as success; if it belongs to another channel the claim fails.
- The cluster rejects an object by policy (forbidden or admission denied): no retry, an error is reported to Sentry, the claim fails.
- A password is issued but the credential store update fails: the old password stays valid, the new one is not returned, and the response is `503`.
- The operator is slow to reconcile the SIP user: the connection endpoint reports `pending`, not an error.
- Two issue requests for the same channel arrive at the same time: each produces a valid, distinct password, and only the last one stays valid.
- A caller guesses channel UUIDs: unknown, other-project, inactive and wrong-type channels are indistinguishable.
- The DID is sent by a PBX in a different format than the channel address: matching depends on OQ-03 and the route normalization defined in the plan.
- Provisioning was disabled when the channel was created and is enabled later: the connection endpoints answer `409` for that channel until it is provisioned by the command.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When provisioning is enabled, creating a TPH channel MUST create, in the voice infrastructure, a credential entry, a call scope, a dial policy, a call route and a SIP user for that channel, all named from the channel UUID and labeled as managed by Flows.
- **FR-002**: The call route of a channel MUST match only that channel's DID (no wildcard) and MUST deliver only to the existing Asterisk pool extension that starts the voice session.
- **FR-003**: The SIP user of a channel MUST reference only that channel's dial policy, which MUST list only that channel's call scope. It MUST NOT reference the shared internal dial policy or any scope that leads to a SIP trunk.
- **FR-004**: If provisioning fails after retries, the system MUST remove any object it created and MUST leave no TPH channel behind.
- **FR-005**: Creating an object that already exists with the same channel label MUST count as success. The same name with a different channel label MUST fail.
- **FR-006**: The channel configuration MUST receive only non-sensitive SIP metadata. A password MUST NOT be stored in channel configuration, the database, cache, logs, Sentry events or published events.
- **FR-007**: The system MUST expose an internal read endpoint that returns the connection data for a TPH channel without a password, plus the provisioning status (`pending`, `ready` or `error`) read from the SIP user.
- **FR-008**: The system MUST expose an internal write endpoint that generates a new password, stores it only in the credential entry, and returns it once. The response MUST forbid caching. Issuing again MUST invalidate the previous password.
- **FR-009**: Both endpoints MUST authenticate the caller, MUST verify that the channel is an active TPH channel of the project given in the request, and MUST answer an identical `404` for unknown, other-project, inactive and wrong-type channels without calling the cluster.
- **FR-010**: The issue endpoint MUST enforce a per-channel limit of password issues per hour and answer `429` beyond it.
- **FR-011**: Every password issue MUST write an audit log entry with organization, user, channel and resource identifiers, never the password.
- **FR-012**: Releasing a TPH channel MUST delete the objects created for it. A missing object counts as deleted, and a cluster failure MUST NOT prevent the release.
- **FR-013**: A periodic task MUST delete Flows-managed objects of inactive or unknown channels and MUST recreate the objects of active provisioned channels whose SIP user is missing, flagging the channel for a new password. It MUST NOT touch objects that lack the Flows-managed label, MUST NOT delete objects younger than ten minutes (a claim may still be running), and MUST cap the deletions of one run.
- **FR-014**: A management command MUST provision a single existing TPH channel on demand and MUST be idempotent.
- **FR-015**: Provisioning on channel creation MUST be controlled by `TPH_SIP_PROVISIONING_ENABLED`, off by default. When off, TPH channel creation behaves exactly as before and makes no cluster call. Revocation does not depend on the flag: releasing a channel that already carries SIP metadata MUST still delete its objects, so turning the flag off as a rollback never leaves a credential that cannot be revoked. The reconciliation task and the management command run only when the flag is on.
- **FR-016**: Connection data (domain, transports, IPs, media range, codecs, DTMF mode) MUST come from configuration, not from reading cluster objects at request time.
- **FR-017**: Cluster calls MUST use the service account token and CA bundle mounted in the pod, verify TLS, set an explicit timeout, and retry at most a fixed number of times, only on connection error, timeout, HTTP 5xx or 429.
- **FR-018**: Objects created by Flows MUST NOT carry the labels or annotations that make the GitOps controller track them.
- **FR-019**: The TPH claim form MUST keep exactly its current fields (name, country, DID).

### Security Requirements

- **SEC-01 (least privilege)**: The permission granted to the Flows service account in the `kubevoip` namespace MUST be limited to the SIP user, call scope, dial policy and call route resources, and to `get` and `patch` on the single credential Secret by name. It MUST NOT include creating, listing or deleting Secrets, any resource of the gateway, trunk, pool, relay or network profile kinds, any other namespace, or any cluster-wide role. This is a requirement on the platform repository change that accompanies this feature.
- **SEC-02 (cluster-side guard)**: A cluster admission policy SHOULD reject Flows-created objects that reference the shared internal dial policy, use a wildcard route, point outside the voice Asterisk pool, or reference a Secret other than the credential Secret. RBAC alone does not restrict the content of a created object.
- **SEC-03 (tenant isolation)**: A credential of one channel MUST NOT be able to originate a call that reaches the number or agent of another channel.
- **SEC-04 (no outbound to the telephone network)**: A customer credential MUST NOT be able to originate calls through a trunk.
- **SEC-05 (password quality)**: Passwords MUST be generated with a cryptographically secure source and have a minimum length defined as a named constant.
- **SEC-06 (single exposure)**: A password MUST be visible only in the response of the issue endpoint.
- **SEC-07 (brute force)**: The gateway SHOULD limit repeated failed authentication per source. Enabling the feature in production is conditional on confirming this (OQ-06).
- **SEC-08 (error hygiene)**: Errors returned to callers MUST NOT include cluster response bodies, manifests, tokens or stack traces.

### Key Entities

- **TPH channel**: The existing PSTN telephony channel. Its address is the DID. After this feature a provisioned instance also carries non-sensitive SIP metadata.
- **SIP credential set**: The five cluster objects that belong to one channel: credential entry, call scope, dial policy, call route and SIP user. They are created, listed and deleted together and identified by labels carrying the channel UUID.
- **Connection data**: The values the customer's PBX needs: domain, transports and ports, user name, password (only at issue time), DID, signaling IPs, media IPs and port range, codecs, DTMF mode, and status.
- **Provisioning status**: `pending` (objects exist, the operator has not finished), `ready`, or `error`, derived from the SIP user's status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of TPH channels created with provisioning enabled have a SIP credential set, and 0% have a password stored anywhere in Flows.
- **SC-002**: A customer PBX configured with the returned data can register and place a call to the channel's DID that the voice agent answers, in staging.
- **SC-003**: A credential of channel A cannot reach the DID of channel B and cannot place an outbound call through a trunk, verified in staging with a real PBX.
- **SC-004**: After a channel is released, 0 objects labeled for it remain in the cluster within one reconciliation interval.
- **SC-005**: A failed provisioning leaves 0 channels and 0 cluster objects behind.
- **SC-006**: With provisioning disabled, TPH claim behavior and responses are identical to the previous release, and a release of a channel provisioned earlier still removes its objects.
- **SC-007**: The service account used by Flows is denied, in staging, every action outside the permission described in SEC-01.

## Peak Load

Channel creation is an infrequent admin action. Declared peak: 10 TPH channel creations per minute during batch onboarding, each making 5 cluster writes (about 50 calls per minute). Password issues: at most 10 per minute across all channels, and no more than the per-channel hourly limit. Reconciliation: one run every 15 minutes, listing 4 resource kinds by label. Expected scale: up to 1,000 provisioned channels in the first year (4,000 custom resources and 1,000 entries in one Secret), to be confirmed with the cloud team (OQ-10). Flows processes stay stateless: provisioning state lives in PostgreSQL (channel config) and in the cluster, never in process memory.

## Test Strategy

All tests use `TembaTest`, follow the existing TPH tests in `temba/channels/types/telephony/tests.py` and the internals tests in `temba/api/v2/internals/channels/tests/`, and run with `poetry run coverage run manage.py test`. The Kubernetes API is replaced by an in-memory fake that records requests and can simulate `201`, `404`, `409`, `403`, 5xx and timeouts. No automated test talks to a real cluster.

| Requirement / criterion | Test (flow from input to effect) |
|---|---|
| FR-001, FR-002, FR-003, SC-001 | Claim a TPH channel with the flag on: assert the five manifests sent to the fake (names, labels, references, route matches only the DID, SIP user references only the channel's dial policy) and the non-sensitive metadata in the channel config |
| FR-004, SC-005 | Fake fails on the fourth object: assert the first three are deleted, the claim returns an error and no active channel exists |
| FR-005 | `409` with the same channel label succeeds; `409` with another channel label fails |
| FR-017 | 5xx twice then success passes; 5xx always makes exactly the maximum attempts and fails; `403` makes one attempt |
| FR-006, SEC-05, SEC-06 | After claim and issue: password absent from `channel.config`, from captured logs and from every channel column; two issues return different passwords and produce two patches |
| FR-007 | Connection endpoint for a provisioned channel returns the expected fields and no `password`; status maps from the fake SIP user status |
| FR-008, FR-010, FR-011 | Issue returns the password once with a no-store header; the limit returns `429` without a cluster call; an audit log record exists without the password |
| FR-009 | Other project, inactive channel, non-TPH channel, unknown UUID and missing auth return identical `404`/`401` and make no cluster call |
| FR-012, SC-004 | Release deletes the five objects; release with a failing fake still completes; missing objects count as deleted |
| FR-013 | Reconciliation deletes objects of inactive and unknown channels, recreates a missing SIP user for an active channel and flags it, and ignores unlabeled objects |
| FR-014 | Command provisions a legacy channel and is a no-op on a second run |
| FR-015, FR-019, SC-006 | Flag off: claim makes no cluster call, the form fields are unchanged, and endpoints answer `409` for channels without provisioning. A channel provisioned earlier is still revoked on release while the flag is off, and the reconciliation task and command do nothing |
| SEC-08 | A cluster failure never leaks a body, token or stack trace in the response |

**Manual staging checks (required before enabling in production, with the cloud team)**: register and call from a test PBX and hear the agent; dial another channel's DID with the same credential and be refused; dial an external number and be refused; ask the cluster whether the Flows service account may perform each action outside SEC-01 and get "no"; create a SIP user with the shared dial policy as the Flows service account and be rejected by the admission policy; repeat a wrong password and be rate limited.

**Failure paths covered**: cluster unavailable, cluster forbids, object already exists, partial creation rollback, credential store update failure, unauthorized caller, rate limit, release with cluster down, reconciliation with leftovers and drift.

## Assumptions

- Flows runs in the same cluster as KubeVoIP and its pods use the `flows` service account, which already exists in `kubernetes-manifests-platform`.
- The RBAC for that service account (CLOUDW-4780) and the cluster-side policy (SEC-02) will be delivered as platform changes; until then the feature runs only against the fake and stays disabled.
- The `kubevoip.com/v1alpha1` schemas are those of the installed operator CRDs: SIP user fields `gatewayRef`, `dialPolicyRef`, `extension` (digits, up to 20), `authUsername` (lowercase letters, digits and hyphen, up to 40), `callerId`, `passwordSecretRef`.
- Each channel has exactly one DID and one credential (OQ-13).
- A password is shown once and rotated to be seen again (OQ-05). Storing it encrypted in Flows is rejected for this version.
- The DID the PBX sends is normalized so it matches the channel address; the exact rule is decided in the plan after OQ-03 is confirmed.
- Channel creation through the integrations service already surfaces claim errors to the frontend, so no change is needed in how errors from `activate` reach it.
- Existing TPH channels are not modified automatically (consistent with `012-tph-voice-config`).

## Out of Scope

- The integrations service endpoints and the frontend screen that show the data to the customer (other repositories, tracked in Related Work).
- Trunk-by-IP provisioning for PBXs that do not register (OQ-09).
- SRTP/media encryption options (OQ-07).
- Changes to the voice gateway, Courier, Mailroom or Nexus.
- Raising the media port range, fixed IPs for the load balancers and brute-force protection in the SIP proxy (cloud/platform work, tracked as dependencies).

## Related Work

| Repository / item | Change | Complexity | Owner |
|---|---|---|---|
| `flows` (this spec) | Provisioner, TPH activate/deactivate, two internals endpoints, reconciliation task, management command, settings, tests, changelog | High | Experience |
| `kubernetes-manifests-platform` | Role and RoleBinding for the `flows` service account in `kubevoip` (CLOUDW-4780, scope narrower than the card), `TPH_SIP_*` variables, optional Elastic IPs and larger RTP range (CLOUDW-4646) | Low to Medium | Experience with Cloud review |
| Cluster admission policy (SEC-02) | Validating policy for objects created by the Flows service account | Medium | Cloud |
| `weni-integrations-engine` | Proxy the two endpoints, check the user's project permission | Medium | Integrations |
| Integrations frontend | Post-creation screen with connection data, copy buttons, one-time password and "generate new password" | Medium | Integrations |
| `vtex-cx-engine-specs` | Amendment to 004 bringing customer PBX connection into scope | Low | Product trio |
| `weni-webchat-socket` | None if isolation is confirmed at the cluster level (OQ-01); otherwise validate DID ownership on session registration | None or Medium | Experience |

## Divergences

- **Scope of provisioning and trunk connection**: 004 puts number provisioning and trunking out of scope. Amendment in `vtex-cx-engine-specs`: **pending, no link yet** (owner: 004 product trio). Until it is tagged, production runs with `TPH_SIP_PROVISIONING_ENABLED=false`. After the tag, update the pinned version.
- BD-010 and FR-035 are not changed: the channel is still resolved by DID and the contact by caller ID.

## Open Questions

| ID | Question | Owner | Default assumed in this spec | Blocks |
|----|----------|-------|------------------------------|--------|
| OQ-01 | Does a KubeVoIP dial policy really restrict a SIP user to the call routes of the scopes it lists, and does a SIP user with no trunk scope fail to originate outbound calls? | Cloud, KubeVoIP docs | Yes. If not, SEC-03 and SEC-04 need a gateway-side DID ownership check | Production enablement |
| OQ-02 | Where does the Flows RBAC live and can the platform GitOps project apply a Role in `kubevoip`? | Cloud | The platform repository, next to Flows. CLOUDW-4780 scope must be narrowed to match SEC-01 | Staging tests |
| OQ-03 | In what format does a PBX send the DID in `To` (`+55...`, `55...`, national)? | Experience with a real PBX | Digits only, normalized in the dialplan and in the route match | Route match value |
| OQ-04 | Can the gateway and media load balancers get fixed IPs, and can the RTP range grow beyond 36 ports (CLOUDW-4646)? | Cloud / Engine (the folder is now Engine's) | Connection data returns the domain; IP lists are configuration and may be empty | Production enablement |
| OQ-05 | Is one-time password display acceptable to product? | Product | Yes, with rotation | None |
| OQ-06 | Does the SIP proxy limit repeated failed authentication per source? | Cloud | Not confirmed; required before production | Production enablement |
| OQ-07 | Offer SRTP to customers using TLS? | Cloud, Product | Out of the first version | None |
| OQ-08 | Which codecs and DTMF mode does the generated endpoint accept? | Cloud | G.711 (PCMA, PCMU) and RFC 4733, configurable text only | Screen text only |
| OQ-09 | Offer IP-authenticated trunks for PBXs that do not register? | Product | Second version, own spec | None |
| OQ-10 | Operator and proxy limits with thousands of SIP users and one large Secret | Cloud | Fine for the pilot; partition the Secret by range if needed | None for pilot |
| OQ-11 | Minimal HTTP client or the official `kubernetes` package? | Experience | Minimal client on the HTTP library already used by Flows (decided in the plan) | None |
| OQ-12 | Produce a cross-repository architecture document with OpenAPI contracts before implementation? | Experience | Recommended; the endpoint contract in this feature's `contracts/` folder is the seed | None |
| OQ-13 | May one channel have several DIDs or several credentials? | Product | One DID and one credential per channel | None |
| OQ-14 | Do the test SIP user `6001` and the NVoip trunk stay on the shared internal policy in production? | Cloud, Experience | Unaffected by this spec; the `6001` credential reaches any DID and should leave production | None |
