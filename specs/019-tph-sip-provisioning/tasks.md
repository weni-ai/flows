---

description: "Task list for TPH SIP credential provisioning"
---

# Tasks: Provision customer SIP credentials on TPH channel creation

**Input**: Design documents from `/specs/019-tph-sip-provisioning/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included and mandatory. Constitution Principle XIV requires a flow test per flow with success and failure paths, and the spec has a Test Strategy table.

**Organization**: Grouped by user story. All new code is behind `TPH_SIP_PROVISIONING_ENABLED` (default off), so every phase can merge without enabling the feature.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US5 map to the user stories in `spec.md`
- Paths are relative to the repository root `flows/`

## Path Conventions

- Channel type package: `temba/channels/types/telephony/`
- Internals API: `temba/api/v2/internals/channels/`
- Tasks and commands: `temba/channels/`

---

## Phase 1: Setup

**Purpose**: Settings and constants every later phase uses.

- [x] T001 Add the `TPH_SIP_*` settings listed in `data-model.md` (flag default `false`, namespace, gateway, pool, extension, credentials Secret, extension prefix, timeout, domain, transports, IPs, RTP range, codecs, DTMF mode, issue limit) to `temba/settings_common.py`, parsing comma-separated lists into lists
- [x] T002 [P] Create `temba/channels/types/telephony/constants.py` with the named constants from `data-model.md` (password bytes, extension length, issue window, retry attempts, backoff base, overall deadline, reconcile interval and deletion cap, label keys, name prefix) and the `SIP_USER_READY_PHASES` and `SIP_USER_ERROR_PHASES` defaulting every unknown phase to `pending`
- [x] T003 [P] Add the `reconcile-tph-sip` entry (task `reconcile_tph_sip_task`, every `RECONCILE_INTERVAL_SECS`) to `CELERY_BEAT_SCHEDULE` in `temba/settings_common.py`

**Checkpoint**: settings load, defaults keep the feature off.

---

## Phase 2: Foundational (blocks every user story)

**Purpose**: The Kubernetes client, the object builders, the fake and the provisioner core. Nothing else can be tested without these.

- [x] T004 [P] Write failing tests for the client in `temba/channels/types/telephony/tests_kubernetes_client.py`: bearer token re-read on each call, TLS verify with the CA path, per-request timeout, 3 attempts with backoff on connection error, timeout, 5xx and 429, a single attempt on 4xx, overall deadline, and no response body in raised errors
- [x] T005 Implement `temba/channels/types/telephony/kubernetes_client.py` (`create`, `get`, `list_by_label`, `delete`, `merge_patch`) and a `KubernetesError` hierarchy distinguishing transient, forbidden, conflict, not found and configuration errors
- [x] T006 [P] Write failing tests for the builders in `temba/channels/types/telephony/tests_provisioning.py` that assert invariants 1 to 6 of `data-model.md` (own scope and policy, one scope in the policy, route match is digits only, SIP user references own policy and the configured Secret, only the two labels, name length and pattern)
- [x] T007 Implement `temba/channels/types/telephony/manifests.py`: `resource_name(channel)`, `normalize_did_for_route(address)`, `sip_extension(channel)` and the five object builders as pure functions
- [x] T008 [P] Implement `temba/channels/types/telephony/fake_kubernetes.py`: in-memory store keyed by kind and name with `409`, `404`, label listing, merge patch on the Secret, and switches to inject `403`, 5xx and timeout on a given call number
- [x] T009 Implement `SIPProvisioner.provision` and `SIPProvisioner.deprovision` in `temba/channels/types/telephony/provisioning.py` (flag check, creation order, `409` with matching label as success, reverse-order rollback on failure, `404` on delete as success, `SIPProvisioningError` with a generic message); inject the client so tests pass the fake

**Checkpoint**: builders and provisioner pass their unit tests against the fake. No channel hook yet.

---

## Phase 3: User Story 1 - New TPH channel gets an isolated SIP credential (Priority: P1) 🎯 MVP

**Goal**: Claim a TPH channel and have its five objects created, or nothing at all.

**Independent Test**: With the flag on and the fake client, claim a channel and assert the five objects, the non-sensitive config keys, no password anywhere, and a clean rollback when the fourth object fails.

### Tests for User Story 1

- [x] T010 [P] [US1] Claim flow test in `temba/channels/types/telephony/tests.py`: flag on creates five objects with the expected names, labels and references and writes `sip_resource_name`, `sip_username` and `sip_extension` to `channel.config` (FR-001, FR-002, FR-003, FR-006, SC-001)
- [x] T011 [P] [US1] Failure-path tests in `temba/channels/types/telephony/tests.py`: fake fails on the fourth create, first three deleted, no active channel, generic error; `409` same label succeeds; `409` other label fails; `403` makes one attempt (FR-004, FR-005, FR-017, SC-005)
- [x] T012 [P] [US1] Flag-off and form tests in `temba/channels/types/telephony/tests.py`: no client call on claim when the flag is off, claim fields unchanged, existing TPH tests still pass (FR-015, FR-019, SC-006)
- [x] T013 [P] [US1] Secret-hygiene test in `temba/channels/types/telephony/tests_provisioning.py`: after claim, the password is absent from `channel.config`, from captured logs and from every channel column (FR-006, SEC-05)

### Implementation for User Story 1

- [x] T014 [US1] Implement `TelephonyPSTNType.activate(channel)` in `temba/channels/types/telephony/type.py`: call the provisioner, save only `config` with the three non-sensitive keys, leave `async_activation` false so `Channel.create` rolls the channel back on error
- [x] T015 [US1] Add structured logging (`org_id`, `channel_uuid`, `resource_name`, `outcome`) and Sentry context (org, user, correlation id, no phone) to the provisioner failure paths in `temba/channels/types/telephony/provisioning.py`

**Checkpoint**: US1 delivers value alone. A provisioned channel exists end to end against the fake.

---

## Phase 4: User Story 3 - Removing the channel revokes the credential (Priority: P1)

**Goal**: Releasing a channel deletes everything created for it, even when the cluster is unavailable.

**Independent Test**: Release a provisioned channel with the fake and assert five deletions; release with the fake failing and assert the release still completes.

### Tests for User Story 3

- [x] T016 [P] [US3] Release flow tests in `temba/channels/types/telephony/tests.py`: five objects and the Secret key deleted in reverse order; missing objects count as deleted; release completes and logs when the cluster fails; a channel provisioned earlier is still revoked on release while the flag is off (FR-012, FR-015, SC-004)

### Implementation for User Story 3

- [x] T017 [US3] Implement `TelephonyPSTNType.deactivate(channel)` in `temba/channels/types/telephony/type.py` calling `SIPProvisioner.deprovision`; skip when the channel has no `sip_resource_name`, and do not check the flag (revocation must work with the flag off)

**Checkpoint**: create and release are symmetric.

---

## Phase 5: User Story 2 - The customer receives the connection data (Priority: P1)

**Goal**: An authorized internal caller reads the connection data and issues a one-time password.

**Independent Test**: Call the GET and POST endpoints for a provisioned channel and verify the contract, the single exposure of the password, the identical `404`, and the limit.

### Tests for User Story 2

- [x] T018 [P] [US2] Connection-data tests in `temba/channels/types/telephony/tests_provisioning.py`: `build_connection_data` returns the fields in `contracts/internals-sip-endpoints.md` from settings and config, empty lists when IPs are not configured, status mapped from the fake SIP user, and no `password` key (FR-007, FR-016)
- [x] T019 [P] [US2] Endpoint tests in `temba/api/v2/internals/channels/tests/test_sip_views.py`: GET contract and status; POST returns a password once with `Cache-Control: no-store`; two POSTs give different passwords and two patches; `credentials_reset_required` cleared (FR-007, FR-008, SC-001)
- [x] T020 [P] [US2] Authorization tests in `temba/api/v2/internals/channels/tests/test_sip_views.py`: other project, inactive, non-TPH, unknown UUID, unknown project and missing auth return the identical `404`/`401` with zero client calls; invalid UUIDs return `400`; channel without provisioning returns `409` (FR-009)
- [x] T021 [P] [US2] Limit, audit and failure tests in `temba/api/v2/internals/channels/tests/test_sip_views.py`: sixth issue within the window returns `429` with `Retry-After` and no patch; audit log record without the password; Secret patch failure returns `503` and the old password is unchanged; no error body leaks cluster text (FR-010, FR-011, SEC-08)

### Implementation for User Story 2

- [x] T022 [US2] Implement `build_connection_data` in `temba/channels/types/telephony/connection.py` using settings and the SIP user status through `SIP_USER_READY_PHASES` and `SIP_USER_ERROR_PHASES`
- [x] T023 [US2] Implement `SIPProvisioner.issue_password` and `read_status` in `temba/channels/types/telephony/provisioning.py`: `secrets.token_urlsafe(SIP_PASSWORD_BYTES)`, merge patch on the Secret key, Redis `INCR`/`EXPIRE` limit, clear the reset flag, audit log without the password
- [x] T024 [P] [US2] Add request serializers (UUID validation for `channel_uuid` and `project_uuid`) to `temba/api/v2/internals/channels/serializers.py`
- [x] T025 [US2] Add `GetSIPConnectionUseCase` and `IssueSIPCredentialsUseCase` to `temba/api/v2/internals/channels/usecases.py`: resolve the channel by uuid, org of the project, active and type TPH, the single `404` for any miss, the `409` for no provisioning
- [x] T026 [US2] Add `ChannelSIPConnectionView` and `ChannelSIPCredentialsView` to `temba/api/v2/internals/channels/views.py` with the same authentication and permission classes as `InternalChannelView`, thin handlers, no-store headers on the POST, and exception-to-status mapping (`429`, `503`)
- [x] T027 [US2] Register `channel_sip_connection` and `channel_sip_credentials` in `temba/api/v2/internals/channels/urls.py`

**Checkpoint**: the integrations service can be pointed at the endpoints on staging.

---

## Phase 6: User Story 4 - Leftovers and drift are corrected (Priority: P2)

**Goal**: A periodic task removes orphans and recreates lost SIP users.

**Independent Test**: Seed the fake with orphans and a missing SIP user, run the task, assert deletions and recreation.

### Tests for User Story 4

- [x] T028 [P] [US4] Reconciliation tests in `temba/channels/types/telephony/tests_reconciliation.py`: objects of inactive and unknown channels deleted; active channel missing its SIP user is recreated and flagged; objects without the managed-by label never touched; deletion cap stops the run and logs an error; a cluster failure on one channel does not stop the others (FR-013)

### Implementation for User Story 4

- [x] T029 [US4] Implement `temba/channels/types/telephony/reconciliation.py` (group by `weni.ai/channel-uuid`, decide delete or recreate, honor `RECONCILE_MAX_DELETIONS_PER_RUN`, log before deleting)
- [x] T030 [US4] Add `reconcile_tph_sip_task` to `temba/channels/tasks.py` as a `nonoverlapping_task` named `reconcile_tph_sip_task`, no-op when the flag is off

**Checkpoint**: failed revocations and cluster rebuilds heal themselves.

---

## Phase 7: User Story 5 - Existing channels provisioned on demand (Priority: P3)

**Goal**: An operator provisions a pre-existing TPH channel with one command.

**Independent Test**: Run the command on a channel without SIP metadata, then again.

### Tests for User Story 5

- [x] T031 [P] [US5] Command tests in `temba/channels/types/telephony/tests_provisioning.py`: provisions a legacy channel; second run changes nothing; unknown, inactive and non-TPH channels give a clear error; refuses to run when the flag is off (FR-014)

### Implementation for User Story 5

- [x] T032 [US5] Implement `temba/channels/management/commands/provision_tph_sip.py` (`--channel <uuid>`) calling the same provisioner and config update as `activate`

**Checkpoint**: all five stories done.

---

## Phase 8: Polish and cross-cutting

- [x] T033 Add the `WENI-CHANGELOG.md` entry under the next free minor version (confirm the number at merge time), as a `feat:` bullet that says it is security-relevant and that it ships disabled by default
- [x] T034 [P] Review every log call added by this feature for the password, the DID and the caller number; add a test that fails if `password` appears in captured logs during claim, issue and reconcile
- [ ] T035 Run `./code_check.py` and `poetry run coverage run manage.py test` for the `channels` and `api` groups; fix findings without touching unrelated code (partial: code_check steps pass locally; the DB-backed test groups must run in CI, no Postgres here)
- [ ] T036 Walk through [quickstart.md](quickstart.md) section 1 and record the result in the PR description
- [ ] T037 Open the pull request with: the Principle II interpretation from `plan.md` (Complexity Tracking) for reviewers, the list of cross-repository dependencies from the spec (RBAC, admission policy, integrations, frontend, product amendment), and the pending Open Questions

### Staging gates (outside this repository, not tasks to code)

| Gate | Owner | Needed before |
|------|-------|---------------|
| T-STG-1 Web pods mount the `flows` service account token and the request timeout exceeds the overall deadline | Platform | Enabling in staging |
| Role, RoleBinding and empty Secret from `contracts/kubernetes-objects.md` applied | Platform, replaces the scope in CLOUDW-4780 | Enabling in staging |
| T-STG-2 Record `status.phase` values and update `SIP_USER_READY_PHASES` and `SIP_USER_ERROR_PHASES` | Experience | Customer-facing status |
| T-STG-3 Confirm the DID format and how Courier resolves it, adjust `normalize_did_for_route` | Experience | Enabling in staging |
| T-STG-4 / OQ-01 Dial policy isolation and no outbound through a trunk | Cloud and Experience | Enabling in production |
| Admission policy (SEC-02), brute-force protection (OQ-06), fixed IPs and RTP range (OQ-04) | Cloud and Engine | Enabling in production |
| Amendment to product spec 004 tagged and the pinned version updated | Product | Enabling in production |

---

## Dependencies and Execution Order

### Phase dependencies

- **Phase 1 Setup**: none. **Phase 2 Foundational** depends on T001 and T002 and blocks all stories.
- **US1 (Phase 3)** depends on Phase 2. **US3 (Phase 4)** depends on Phase 2 and shares `type.py` with US1, so do it after T014.
- **US2 (Phase 5)** depends on Phase 2 (provisioner) and can start in parallel with US1 and US3 once T009 is done, except where it needs a provisioned channel in tests (use the fake with a pre-seeded state).
- **US4 (Phase 6)** depends on Phase 2 and on the config keys from US1.
- **US5 (Phase 7)** depends on US1 (it reuses the activate logic; extract the shared function in T014).
- **Polish** depends on every story you ship.

### Within a story

Tests first and failing, then implementation, then logging and hardening. Commit after each green step.

### Parallel opportunities

- T002 and T003 with T001's follow-up work; T004, T006 and T008 (different files) once T002 is done.
- All test tasks inside a story are `[P]` because they live in separate test functions or files.
- US2 serializers (T024) can run alongside T022 and T023.
- After Phase 2, two people can take US1/US3 and US2 in parallel.

## Implementation Strategy

1. **MVP**: Phases 1, 2, 3 and 4 (create and release, symmetric, flag off by default). This is the smallest change that can merge and be validated on staging against the real cluster once the platform pieces exist.
2. **Increment 2**: Phase 5 (connection data and password), so the integrations service can start integrating against staging.
3. **Increment 3**: Phases 6 and 7 (self-healing and legacy channels).
4. **Release**: Phase 8, then the staging gates, then production only after the production gates.

## Suggested commits (Principle VII, 50 characters or fewer, one logical change each)

1. `docs: add 019 TPH SIP provisioning spec` (spec, plan, research, data model, contracts, quickstart, tasks, checklist)
2. `feat: add TPH SIP provisioning settings`
3. `feat: add minimal Kubernetes client for TPH`
4. `feat: build per-channel KubeVoIP objects`
5. `feat: provision SIP credentials on TPH claim`
6. `feat: revoke SIP credentials on TPH release`
7. `feat: add SIP connection and password endpoints`
8. `feat: reconcile orphaned TPH SIP objects`
9. `feat: add provision_tph_sip command`
10. `docs: add SIP provisioning changelog entry`
