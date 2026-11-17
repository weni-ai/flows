# Implementation Plan: Provision customer SIP credentials on TPH channel creation

**Branch**: `feat/019-tph-sip-provisioning` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/019-tph-sip-provisioning/spec.md`

## Summary

When provisioning is enabled, creating a TPH channel also creates, through the Kubernetes API, the five objects that give that channel an isolated SIP credential in KubeVoIP (credential entry, call scope, dial policy, call route, SIP user). Releasing the channel removes them, and a periodic task corrects leftovers and drift. Two internals endpoints give the integrations service the PBX connection data and a one-time password. The password never reaches Flows storage, logs or channel config. Everything is behind `TPH_SIP_PROVISIONING_ENABLED`, off by default, so the code can ship before the cluster pieces (RBAC, admission policy, fixed IPs) exist.

Technical approach, decided in [research.md](research.md): a minimal `requests` client for the Kubernetes API, one `SIPProvisioner` as the only door to the cluster, `activate`/`deactivate` hooks on `TelephonyPSTNType`, use cases behind two thin internals views, and a `nonoverlapping_task` for reconciliation.

## Technical Context

**Language/Version**: Python 3.11 (`>=3.10,<3.12`), Django 3.2, Django REST Framework

**Primary Dependencies**: `requests` (already used by 62 modules, no new dependency), `django-redis` (issue limit and task lock), Celery (reconciliation). No new package, so no `poetry.lock` change

**Storage**: PostgreSQL (`Channel.config` JSON, no migration), Redis (issue counter, task lock), Kubernetes API (SIP credential set)

**Testing**: `TembaTest` through `poetry run coverage run manage.py test`, CI groups `channels` and `api`. Kubernetes API replaced by an in-memory fake. `./code_check.py` clean

**Target Platform**: Flows web and Celery pods in the same cluster as KubeVoIP

**Project Type**: Django web service (backend only)

**Performance Goals**: claim latency increases by at most the cost of 5 cluster writes (typically under 500 ms in-cluster); worst case bounded by retry settings

**Constraints**: no secret outside the cluster Secret; at most 3 attempts per cluster call with 5 s timeout; claim must leave nothing behind on failure; no behavior change when the flag is off

**Scale/Scope**: peak 10 channel creations per minute, up to 1,000 provisioned channels in year one, one reconciliation run every 15 minutes (see spec Peak Load)

## Constitution Check

*GATE: passed before Phase 0 research, re-checked after Phase 1 design.*

| Principle | Result | Evidence |
|-----------|--------|----------|
| I. Version Control and Review | Pass | PR from `feat/019-tph-sip-provisioning`, CI green, review |
| II. Security and Secrets | **Pass with interpretation to confirm** | No secret in repo, logs or Sentry; least-privilege RBAC in `contracts/kubernetes-objects.md`. The SIP password is not stored in `channel.config` (see Complexity Tracking) |
| III. Observability | Pass | Structured logs with opaque ids; audit record on issue; no password, DID or caller in logs |
| IV. Versioned Contracts | Pass | Two additive endpoints, additive `config` keys, no migration, minor release, courier/mailroom unaffected |
| V. Specification Traceability | Pass | Inherits 004 pinned by commit; Full cycle justified in the spec |
| VI. No Silent Divergence | Pass | Scope divergence declared, amendment pending, feature disabled in production until tagged |
| VII. Commit Messages | Pass | Conventional, atomic, see tasks |
| VIII. Changelog | Pass | Entry marked security-relevant |
| IX. Never Trust the Client | Pass | Serializers validate UUIDs; authorization on the server by project and type; thin views, logic in use cases |
| X. Fail Gracefully | Pass | Explicit timeout, generic errors, no internals leaked |
| XI. Bounded Retry | Pass | 3 attempts, transient errors only, operations idempotent by name and label |
| XII. Scalability and Peak Load | Pass | Peak declared; no process state; counters in Redis |
| XIII. Diagnosable Errors | Pass | Sentry context with org, user and correlation id, no phone number |
| XIV. Tests Exercise Flows | Pass | Flow tests per user story with failure paths, see spec Test Strategy |
| XV. Explicit Over Clever | Pass | All thresholds are named constants; one provisioner is the single door to the cluster |
| XVI. Contained Changes | Pass | Only the TPH type, two internals endpoints, one task, one command and settings |

**Re-check after design**: no new violation. The single point to settle is the Principle II interpretation below.

## Project Structure

### Documentation (this feature)

```text
specs/019-tph-sip-provisioning/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
├── contracts/
│   ├── internals-sip-endpoints.md
│   └── kubernetes-objects.md
└── tasks.md            # created by /speckit-tasks
```

### Source Code (repository root)

```text
temba/channels/types/telephony/
├── type.py                      # modified: activate/deactivate call the provisioner
├── views.py                     # unchanged (FR-019)
├── constants.py                 # new: names, labels, limits, phase map
├── kubernetes_client.py         # new: minimal in-cluster client with bounded retry
├── manifests.py                 # new: pure functions that build the five objects
├── provisioning.py              # new: SIPProvisioner (provision, deprovision, issue_password, read_status)
├── connection.py                # new: builds connection data from channel config and settings
├── reconciliation.py            # new: orphan and drift handling used by the task
├── fake_kubernetes.py           # new: in-memory fake used only by tests
├── tests.py                     # modified: claim and release flows
├── tests_provisioning.py        # new
├── tests_kubernetes_client.py   # new
└── tests_reconciliation.py      # new

temba/channels/tasks.py          # modified: reconcile_tph_sip_task
temba/channels/management/commands/provision_tph_sip.py   # new
temba/api/v2/internals/channels/
├── views.py                     # modified: ChannelSIPConnectionView, ChannelSIPCredentialsView
├── serializers.py               # modified: request validation
├── usecases.py                  # modified: GetSIPConnectionUseCase, IssueSIPCredentialsUseCase
├── urls.py                      # modified: two routes
└── tests/test_sip_views.py      # new

temba/settings_common.py         # modified: TPH_SIP_* settings and one CELERY_BEAT_SCHEDULE entry
WENI-CHANGELOG.md                # modified: security-relevant entry
specs/019-tph-sip-provisioning/  # this feature
```

**Structure Decision**: Option 1, single Django project. New code stays in the TPH channel type package and the internals channels app, which is where neighbors of the same kind live (Principle: prefer extending an existing abstraction). The Kubernetes client is not placed in `temba/utils` because it has one consumer and a deliberately narrow surface; promoting it later is a separate change.

## Design Notes

### Provisioning flow (`SIPProvisioner.provision`)

1. If the flag is off, return without calling the cluster.
2. Build the five objects with `manifests.py` (pure functions, unit tested).
3. Create in the order of the data model. Treat `409` with the same channel label as success.
4. On any failure that survives retries, delete in reverse what this call created, then raise `SIPProvisioningError` (generic message, details only in logs and Sentry).
5. On success, write `sip_resource_name`, `sip_username`, `sip_extension` to `channel.config` and save only `config`.

`Channel.create` then either keeps the channel or releases it. `release` calls `deprovision`, which is safe to repeat.

### Issue flow (`SIPProvisioner.issue_password`)

1. Use case loads the channel with the authorization filters of the contract. Misses are one `404`.
2. Check provisioning exists (`409` if not), then the Redis limit (`429`).
3. Generate the password, merge-patch the Secret key. On failure, no change and `503`.
4. Clear `sip_credentials_reset_required` if set. Log the audit record. Return the connection data with the password and no-store headers.

### Reconciliation

- Lists each of the four kinds by label `weni.ai/managed-by=flows`, groups by `weni.ai/channel-uuid`.
- Deletes groups whose channel is inactive or unknown, up to `RECONCILE_MAX_DELETIONS_PER_RUN` per run.
- For active channels with `sip_resource_name` and no SIP user: recreates all five objects, sets `sip_credentials_reset_required`.

### Failure and rollback summary

| Situation | Behavior |
|-----------|----------|
| Cluster down during claim | Retries, rollback of created objects, claim error, no channel |
| Forbidden or admission denied | No retry, Sentry event, claim error |
| Cluster down during release | Release completes; reconciliation deletes later |
| Secret patch fails on issue | No password change, `503` |
| Flag turned off after use | New channels are not provisioned; existing credentials keep working; `deactivate` still revokes channels that carry `sip_resource_name`; reconciliation and the command do nothing; endpoints answer `409` for channels without provisioning |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle II says channel credentials flow through Temba channel config. The SIP password is **not** stored there | `CreateChannelSerializer` (in `weni-rp-apps`) returns the whole `config` to the integrations service at claim, and Courier reads `config`. The password is not a credential Flows uses to reach a provider: it is issued by us to the customer and consumed by KubeVoIP, whose source of truth is the cluster Secret. Keeping it out of `config` removes two exposure paths | Storing it in `config` would put it in a response and in a table read by other services. Storing it encrypted elsewhere in Flows adds key management for a value Flows never needs to read |

Resolution path: ask the reviewers to confirm this reading of Principle II in the PR. If they require it in writing, the constitution article gets a one-line clarification through the Governance amendment process in a separate change. The code does not depend on the answer.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Web pods do not mount the `flows` service account token | Claim fails with provisioning on | T-STG-1 in staging before enabling; flag off by default |
| Operator `status.phase` strings unknown | Wrong `status` shown | Safe default `pending`; fill the map in T-STG-2 |
| Dial policy does not isolate tenants | Cross-tenant calls | Do not enable in production until OQ-01 is confirmed; fallback is a DID ownership check in the gateway |
| Synchronous claim latency under a slow cluster | Web timeout | Each request has a 5 s timeout and at most 3 attempts, but five sequential calls could add up. The provisioner therefore applies one overall deadline per operation (`K8S_OVERALL_DEADLINE_SECS = 20`): when it is exceeded the operation stops, rolls back and fails. Confirm the web request timeout is above it (T-STG-1) |
| Reconciliation deletes wrongly | Customers lose service | Label-only scope, deletion cap per run, log before delete, dry-run unit tests |
| Secret grows large | Operator or API slowness | Thousands of keys fit; partition if OQ-10 says so |
