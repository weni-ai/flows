# Implementation Plan: Consume project events from AmazonMQ

**Branch**: `feat/project-events-amazonmq` (not created by this command; checkout is on `main`) | **Date**: 2026-11-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/019-project-events-amazonmq/spec.md`

## Summary

`ProjectConsumer` on `flows.projects.queue` starts applying `project.updated`, `project.status.updated`, `project.type.updated` and `project.deleted` through the four existing project use cases. Each payload is validated strictly before any write, and the envelope fields that reach logs and Sentry are validated for every event type. One setting, `PROJECT_EVENTS_LEGACY_ACTIONS`, is read by both consumers and decides which one applies each action, so the cut-over and the rollback are environment changes only. Its default keeps today's behaviour. A system check stops `edaconsume` and `edaconsume-amq` from starting with an unknown value.

`delete_project` becomes idempotent and atomic. The project use cases stop logging the user's e-mail and the project name. Both consumers report failures to Sentry with opaque tags and no frame variables, then re-raise a sanitized exception, so the `weni-eda` rejection log carries no payload either. Courier and Mailroom do not change.

## Technical Context

**Language/Version**: Python >=3.10,<3.12 (CI 3.11), Django 3.2.25

**Primary Dependencies**: `weni-eda` 0.3.0 (`EDAConsumer`, `Message`, `Event`), `sentry-sdk` 1.45.1, `pytz`. No new dependency.

**Storage**: PostgreSQL `orgs_org` (existing columns). No migration.

**Testing**: `TembaTest`. Run with `poetry run coverage run manage.py test temba.projects`, plus `./code_check.py`.

**Target Platform**: The worker processes `edaconsume` (RabbitMQ, `handle_default_consumers`) and `edaconsume-amq` (AmazonMQ, `handle_amq_consumers`, TLS).

**Project Type**: Django web service with event-driven consumers.

**Performance Goals**: Sustain the declared peak of 4 messages/min for the four events and 18/min for creations, plus bursts of `project.deleted` when an organization is deleted in Connect. No per-message external call is added. One extra lookup on the unindexed `proj_uuid` per AmazonMQ event that reaches the org lookup, and one extra lookup on the unindexed `auth_user.email` per event that reaches a use case ([research R6](./research.md#r6-missing-org-org_id-and-user_id-for-sentry)).

**Constraints**:

- Envelope validation runs before anything is logged; payload validation runs before the skip check.
- Exactly one consumer applies each action for any value of the setting.
- No e-mail or project name in logs or in Sentry events from this path.
- Rejections are never requeued, so a dead-letter exchange is a rollout prerequisite.
- The behaviour of the legacy consumer for listed actions is unchanged, apart from the deletion guard and sanitized errors.

**Scale/Scope**: Two consumers, four use cases (one gains a guard; three only change log lines), two settings files, one system check. About 22 messages/min at peak across both queues.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Pre-research gate: passed. The spec's three justified departures (III, X, XIII) are carried over below. Research found two places where the spec's Observability requirement would fail in production unless the design addressed them: frame locals in Sentry, and `info` logs dropped by the root logger. Both are resolved in research, so no principle exception is added.

| Principle | Result |
|---|---|
| I. Version Control and Review | Pull request to `main`, one approval, green `.github/workflows/ci.yml`. |
| II. Security and Secrets | No secret is added. `PROJECT_EVENTS_LEGACY_ACTIONS` is non-secret configuration read from the environment. No new dependency. |
| III. Observability | Logger `temba.projects` at `INFO` in `settings_common.py` and `settings.py.prod`. Lines use `key=value` pairs with `event_id` as the correlation id. The e-mail and project name are removed from the use-case lines. Exception (from the spec): legacy messages have no correlation id, so their lines use `action` and `project_uuid`. |
| IV. Versioned Contracts | Additive: four routing keys handled on a queue that already acks unknown types. The legacy queue's deprecation goes in `WENI-CHANGELOG.md`, and its removal is Rollout step 5. Courier version: none. Mailroom version: none. Contract: [contracts/project-events.md](./contracts/project-events.md). |
| V. Specification Traceability | `## Origin Without Product Spec` with AC-1–AC-7, each mapped to a test in [quickstart.md](./quickstart.md) section 2. Coverage exclusions and the changelog are review gates RG-1 and RG-2 (quickstart sections 1 and 4). |
| VI. No Silent Divergence | Not applicable: no product spec. The sanitized re-raise ([R9](./research.md#r9-keeping-the-e-mail-out-of-sentry)) is an implementation decision that refines the spec's "re-raised" without changing the reject outcome. |
| VII. Commit Messages | Conventional Commits, atomic. |
| VIII. Changelog | `feat:` bullet and deprecation bullet under a new topmost heading for the next minor version. `3.112.1` has already shipped. |
| IX. Never Trust the Client | Every `data` field used is validated for type and value before any write, and `event_id`, `event_type` and `producer` are validated as short tokens before they are logged; the legacy `project_uuid` is only written in canonical UUID form ([R1](./research.md#r1-payload-validation-explicit-validators-not-drf-serializers)). Validation lives at the consumer boundary, and business logic stays in `temba/projects/usecases/`. Exception (from the spec): who may publish is a broker permission. |
| X. Fail Gracefully | Failures are reported and rejected, never swallowed. Deletion is atomic, so a failure leaves the org untouched ([R7](./research.md#r7-idempotent-deletion)). No external call is added: the consumers only use PostgreSQL, and the channel provider and Mailroom calls that `Org.release` already makes keep their current timeouts (out of scope, Principle XVI). Exception (from the spec): recoverability needs the infrastructure's dead-letter exchange. |
| XI. Bounded Retry Over REST | Not applicable: no REST call is added. |
| XII. Scalability and Peak Load | Peak is declared in the spec. No process state: the setting comes from the environment and is the same for every replica. |
| XIII. Diagnosable Errors | Tags `project_uuid`, `event_id`, `event_type` or `action`, `org_id`, and `user_id` (looked up by e-mail without creating a user). Frame variables are dropped and e-mails are redacted for this path. Exception (from the spec): there is no account identifier, because events do not carry one and Flows has no local mapping to the Connect account. |
| XIV. Tests Exercise Flows | Flow tests from `handle(message)` to org state and ack or reject, against the test database, covering success and failure paths ([R10](./research.md#r10-testing-through-handle-in-tembatest)). Both `# pragma: no cover` on `consume` are removed, and none is added. |
| XV. Explicit Over Clever | Event types, the action mapping, skip reasons, log event names and the check id are named constants. Validators are explicit, with no coercion. |
| XVI. Contained Changes | Limited to project consumers, three project use cases, the setting and its check, the `temba.projects` logger entries, and the changelog. Moving `EventAction` and `ProjectStatus` to a shared module is required because the new consumer needs them and the legacy module is scheduled for deletion ([R2](./research.md#r2-shared-module-for-what-outlives-the-legacy-consumer)). The `proj_uuid` index and the global Sentry options are left as follow-ups. |
| XVII. Explicit, Scoped Authorization | Not applicable: no HTTP endpoint. |
| Channel layout | Not applicable. |
| SDD cycle | Full: consumed event contract (IV) and coordination with Connect, Nexus and the broker infrastructure. |

Post-design re-check: passed. The design adds no principle exception beyond the three already justified in the spec. Two items need reviewer attention:

- The reported exception and the re-raised exception now differ. This affects the existing legacy tests that assert `ValueError` or `Org.DoesNotExist`.
- Accepted risk: `delete_project` runs inside a transaction that, with its row locks on the org and its channels, stays open during the existing channel deactivation and Mailroom calls. A slow provider delays the commit of that deletion. This is accepted at the declared peak in exchange for an atomic release ([R7](./research.md#r7-idempotent-deletion)).

## Project Structure

### Documentation (this feature)

```text
specs/019-project-events-amazonmq/
├── spec.md
├── plan.md                       # this file
├── research.md                   # R1–R12
├── data-model.md                 # payloads, context, decision tables, Org transitions
├── quickstart.md                 # validation guide
├── contracts/project-events.md   # consumed events, setting, logs, Sentry
├── checklists/requirements.md
└── tasks.md                      # /speckit-tasks, not this command
```

### Source Code (repository root)

```text
temba/projects/consumers/project_events.py            # new: EventAction, ProjectStatus (moved), is_legacy_action,
                                                      #      ProjectEventContext, ProjectEventRejected, report_exception,
                                                      #      scrub_sentry_event, find_org_id, find_user_id,
                                                      #      canonical_uuid, log event names
temba/projects/consumers/project_event_payloads.py    # new: InvalidProjectEvent, ProjectEventEnvelope,
                                                      #      four validated dataclasses
temba/projects/consumers/project_consumer.py          # four handlers, LEGACY_ACTION_BY_EVENT_TYPE, skip, missing org,
                                                      # thin consume; project.created unchanged
temba/projects/consumers/project_event_consumer.py    # skip for actions not listed, thin consume, sanitized reject,
                                                      # enums imported from project_events
temba/projects/checks.py                              # new: system check projects.E001
temba/projects/__init__.py                            # import checks (as temba/assets/__init__.py does)
temba/projects/usecases/project_delete.py             # already-released guard, transaction.atomic, log without e-mail/name
temba/projects/usecases/project_status_update.py      # log lines without e-mail/name
temba/projects/usecases/project_type_update.py        # log lines without e-mail/name
temba/settings_common.py                              # PROJECT_EVENTS_LEGACY_ACTIONS; "temba.projects" logger at INFO
temba/settings.py.prod                                # "temba.projects" logger at INFO
WENI-CHANGELOG.md                                     # feat + deprecation bullets

temba/projects/consumers/tests/test_project_consumer.py        # handle() helper; flows, skip, invalid, missing org, logs, Sentry
temba/projects/consumers/tests/test_project_event_consumer.py  # skip per setting; exception type now ProjectEventRejected
temba/projects/consumers/tests/helpers.py                      # new: handle() helper shared by the consumer tests
temba/projects/consumers/tests/test_project_events.py          # new: scrub_sentry_event, report_exception tags, is_legacy_action,
                                                               #      find_org_id, find_user_id, canonical_uuid,
                                                               #      ProjectEventRejected message
temba/projects/consumers/tests/test_project_event_payloads.py  # new: envelope and per-field validation edge cases
temba/projects/usecases/tests/test_project_delete.py           # repeated delete, atomic failure, logs
temba/projects/usecases/tests/test_project_status_update.py    # no e-mail/name in logs
temba/projects/usecases/tests/test_project_type_update.py      # no e-mail/name in logs
temba/projects/tests.py                                        # system check cases, default equals EventAction
```

`temba/projects/handle.py` and `docker/start` do not change: both queues are already registered on the right processes.

**Structure Decision**: Extend the existing `temba/projects` app and keep its consumers/use cases split. Validation sits at the consumer boundary in its own module, and the shared consumer plumbing goes in `project_events.py`, so that removing `ProjectEventConsumer` later means deleting one module and its registration.

## Design

### `ProjectConsumer.consume`

```text
context = ProjectEventContext()
try:
    _process(message, context)
except Exception as exception:
    report_exception(exception, context)          # push_scope: tags + scrub_sentry_event; capture_exception
    raise ProjectEventRejected(context, exception) from None

_process:
    event = message.event()                       # TypeError / ParseError -> rejected
    envelope = ProjectEventEnvelope.from_event(event)   # unsafe event_id / event_type / producer -> rejected
    context.event_id, context.event_type = envelope.event_id, envelope.event_type
    if event_type == CREATED: current path; log consumed; ack; return
    if event_type not in HANDLERS: log consumed; ack; return
    payload = PAYLOAD_BY_EVENT_TYPE[event_type].from_data(event.data)   # InvalidProjectEvent -> rejected
    context.project_uuid = payload.project_uuid
    log consumed
    if is_legacy_action(LEGACY_ACTION_BY_EVENT_TYPE[event_type]): log skipped; ack; return
    context.org_id = find_org_id(payload.project_uuid)
    if context.org_id is None: log org_not_found (warning); ack; return
    context.user_id = find_user_id(payload.user_email)   # read-only; None when no User has the e-mail
    HANDLERS[event_type](payload)                 # calls the use case with keyword arguments
    ack
```

### `ProjectEventConsumer.consume`

The same wrapper. `_process` keeps today's steps: `message.json()`, `_validate_message`, then `context.action` and `context.project_uuid = canonical_uuid(body["project_uuid"])` (`None` when it is not a UUID) are set and `project_event_consumed` is logged. If the action is not legacy, it logs `project_event_skipped` and acks. Otherwise it sets `context.user_id = find_user_id(body["user_email"])` and continues with today's `_apply_event` and ack. In its `except` block, it sets `context.org_id = find_org_id(context.project_uuid)` before `report_exception`.

### Named constants

- `ProjectEventType.UPDATED`, `STATUS_UPDATED`, `TYPE_UPDATED`, `DELETED`; `LEGACY_ACTION_BY_EVENT_TYPE`.
- Skip reasons `SKIP_REASON_LEGACY_CONSUMER_APPLIES = "legacy_consumer_applies"` and `SKIP_REASON_AMAZONMQ_CONSUMER_APPLIES = "amazonmq_consumer_applies"`.
- Log event names (`project_event_consumed`, `project_event_skipped`, `project_event_org_not_found`, `project_already_released`).
- Check id `projects.E001`.
- `REDACTED_EMAIL = "[email]"` and the e-mail pattern used by `scrub_sentry_event`.
- `ENVELOPE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")`, matched with `fullmatch` against `event_id`, `event_type` and `producer`.

### What this repository does not build

- The bindings and dead-letter exchange on AmazonMQ.
- Publishing from Connect or Nexus.
- Applying `date_format`, `config`, `vtex_account` or `currency`.
- An index on `Org.proj_uuid`.
- Global Sentry options.
- Removal of the legacy consumer.

## Complexity Tracking

> No constitution violations. Nothing to justify.
