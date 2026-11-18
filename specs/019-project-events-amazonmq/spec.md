# Engineering Specification: Consume project events from AmazonMQ

**Repository**: weni-ai/flows — backend

**Feature Branch**: `feat/project-events-amazonmq`

**Created**: 2026-11-17

**Status**: Draft

**Input**: User description: "Create a spec for the Flows consumers of the project events migration, based on `eda-migracao-projetos.md`."

**Suggested cycle**: SDD Full. The change alters an event contract consumed by a RabbitMQ/AmazonMQ consumer (Principle IV) and needs coordination with Connect and with the broker infrastructure.

## Origin Without Product Spec

- Product Spec: none
- Problem: Flows receives project updates, status changes, type changes and deletions only from the RabbitMQ queue `flows.project-events`, where the event is identified by an `action` field. Connect (and later Nexus) will publish these events to AmazonMQ `projects.topic` with routing key equal to `event_type`, and the RabbitMQ publication can only be switched off once Flows consumes them from `flows.projects.queue`.
- Acceptance criteria:
  - AC-1: `ProjectConsumer` on `flows.projects.queue` applies `project.updated`, `project.status.updated`, `project.type.updated` and `project.deleted` to the org with the same effect `ProjectEventConsumer` has for `updated`, `status_updated`, `project_type_update` and `deleted`.
  - AC-2: A setting `PROJECT_EVENTS_LEGACY_ACTIONS` decides, for each of the four actions, which consumer applies it. An action in the list is applied by `ProjectEventConsumer` and acknowledged without effect by `ProjectConsumer`; an action not in the list is applied by `ProjectConsumer` and acknowledged without effect by `ProjectEventConsumer`. The default lists the four actions, so the default behaviour is today's behaviour.
  - AC-3: An AmazonMQ project event with an invalid `data.uuid`, a missing `user_email`, a missing or invalid `status`, a non-boolean `is_multi_agents` or an unknown `timezone` is rejected without changing any org. An envelope whose `event_id`, `event_type` or `producer` is not a short token (FR-012) is rejected for every event type.
  - AC-4: A second `project.deleted` (or a legacy `deleted`) for an org that is already released does not release it again, so `released_on` and the deletion window do not move.
  - AC-5: A valid AmazonMQ event for a project that has no org in Flows is logged and acknowledged.
  - AC-6: No log line and no Sentry event written by the project event path contains a user e-mail or the project name.
  - AC-7: `project.created` keeps its current behaviour apart from the envelope validation of FR-012, and other unknown event types on `flows.projects.queue` are still acknowledged and ignored.

Review gates (checked in code review and by the commands in [quickstart.md](./quickstart.md), not acceptance criteria of the behaviour):

- RG-1: Neither consumer's `consume` keeps `# pragma: no cover`, and the new paths add no coverage exclusion.
- RG-2: `WENI-CHANGELOG.md` gains a `feat:` bullet for the new events and a bullet announcing the deprecation of `flows.project-events`.

Reference: the cross-service design and decisions are recorded in `eda-migracao-projetos.md` (team discussion document, not versioned). The publisher side is `weni-engine/specs/005-project-events-amazonmq`.

## Scope in This Repository

**This repository implements**:

- Handlers for `project.updated`, `project.status.updated`, `project.type.updated` and `project.deleted` in `temba/projects/consumers/project_consumer.py`, with explicit payload validation.
- Validation of the envelope fields that reach logs and Sentry (`event_id`, `event_type`, `producer`) for every event type on `flows.projects.queue`.
- The setting `PROJECT_EVENTS_LEGACY_ACTIONS` and the skip logic in both consumers, so each action is applied by exactly one consumer.
- A guard in `delete_project` so an already released org is not released again.
- Removal of the user e-mail from the log lines of the project use cases.
- `TembaTest` coverage, and removal of `# pragma: no cover` on both `consume` methods.
- `WENI-CHANGELOG.md` bullets.

**Out of scope here**:

- Publishing the events (Connect spec 005; Nexus for `project.type.updated`).
- Creating the bindings and the dead-letter exchange on AmazonMQ, which belong to the broker infrastructure.
- Removing `ProjectEventConsumer` and `flows.project-events`, which happens in a later change after the legacy publication is switched off.
- Applying `project.updated` fields Flows does not apply today (`date_format`, `config`, `vtex_account`, `currency`).
- Courier and Mailroom: no release is needed.

## Current State

- `temba/projects/handle.py` — `handle_consumers` registers `flows.project-events` → `ProjectEventConsumer` on RabbitMQ (process `edaconsume`, `temba.event_driven.handle.handle_default_consumers`). `handle_amq_consumers` registers `flows.projects.queue` → `ProjectConsumer` on AmazonMQ (process `edaconsume-amq` in `docker/start`, `AMQConnectionParamsFactory`).
- `temba/projects/consumers/project_event_consumer.py` — `ProjectEventConsumer` requires `project_uuid`, `action` and `user_email`, validates `action` (`EventAction`) and `status` (`ProjectStatus`), and calls `delete_project`, `update_project_config`, `update_project_status` and `update_project_type`. `is_multi_agents` is coerced with `bool()` rather than validated. Exceptions are sent to Sentry with `capture_exception` and re-raised. `consume` has `# pragma: no cover`.
- `temba/projects/consumers/project_consumer.py` — `ProjectConsumer` parses the envelope with `message.event()`, handles `project.created` (`ProjectEventType.CREATED`), and acks every other event type without effect. `consume` has `# pragma: no cover`.
- `weni-eda` `EDAConsumer.handle` rejects with `requeue=False` on any exception, so a rejected message is dropped unless the queue has a dead-letter exchange.
- Use cases in `temba/projects/usecases/`:
  - `delete_project(project_uuid, user_email)` returns `None` when the org is missing, then calls `Org.release(user)` without checking `is_active`. `Org.release` sets `released_on` to now every time, so a repeated deletion moves the date the org data is purged.
  - `update_project_config(project_uuid, user_email, name, description, language, timezone_location)` raises `Org.DoesNotExist` when the org is missing; `pytz.timezone` raises on an unknown zone. It always rewrites `config["description"]`, `timezone` and `modified_on` when given, so a repeat writes the same values again.
  - `update_project_status` and `update_project_type` return `None` when the org is missing and write only when the value changes.
  - All four resolve `user_email` to a `User` with `get_or_create_user_by_email` for `modified_by` and `Org.release(user)`.
  - `delete_project`, `update_project_status` and `update_project_type` log `by <user_email>` (Principle III forbids it).
- Settings in `temba/settings_common.py` are read with `os.environ.get` and parsed inline (for example `USE_EDA`).
- Tests: `temba/projects/consumers/tests/test_project_consumer.py` (builds envelopes with `Event.build` and calls `consume` directly), `test_project_event_consumer.py`, and `temba/projects/usecases/tests/`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Project changes reach Flows through AmazonMQ (Priority: P1)

When a project is renamed, suspended, reactivated, deleted or changes type in Connect or Nexus, the Flows org reflects it from the AmazonMQ event, so the RabbitMQ publication can be retired.

**Why this priority**: This is the migration. Without it the legacy publication cannot be switched off.

**Independent Test**: With `PROJECT_EVENTS_LEGACY_ACTIONS` empty, consume each of the four AmazonMQ events and check the org fields and the ack.

**Acceptance Scenarios**:

1. **Given** an org, **When** `project.updated` arrives with `name`, `description`, `language` and `timezone`, **Then** those fields change, `modified_by` is the user of `user_email`, and fields sent as `null` are unchanged.
2. **Given** an active org, **When** `project.status.updated` with `INACTIVE` arrives, **Then** the org is suspended; **When** `ACTIVE` or `IN_TEST` arrives, **Then** it is unsuspended.
3. **Given** an org, **When** `project.type.updated` with `is_multi_agents: true` arrives, **Then** `config["is_multi_agents"]` is true.
4. **Given** an active org, **When** `project.deleted` arrives, **Then** the org is released by the user of `user_email`.

---

### User Story 2 - Exactly one consumer applies each action during the transition (Priority: P1)

While Connect publishes to both brokers, each change arrives twice: once on `flows.project-events` and once on `flows.projects.queue`, with no relative ordering. Applying both copies can leave an older name or status last, and releases a deleted org twice.

**Why this priority**: A second release moves the purge date of the org data, and an out-of-order status can suspend an org that is active, which stops its flows.

**Independent Test**: For each value of `PROJECT_EVENTS_LEGACY_ACTIONS`, consume the legacy message and the AmazonMQ event for the same change and check that only the expected consumer calls the use case.

**Acceptance Scenarios**:

1. **Given** the default setting, **When** both copies of a status change arrive, **Then** `ProjectEventConsumer` applies it and `ProjectConsumer` acks its copy without calling the use case.
2. **Given** `PROJECT_EVENTS_LEGACY_ACTIONS=project_type_update`, **When** both copies of a deletion arrive, **Then** `ProjectConsumer` applies it and `ProjectEventConsumer` acks its copy; a type change is still applied by `ProjectEventConsumer`.
3. **Given** an empty setting, **When** a legacy message arrives, **Then** it is acked without effect and logged as skipped.

---

### User Story 3 - Invalid or repeated events never damage an org (Priority: P2)

An operator investigating a rejected event finds it in Sentry and in the logs, with the project and event identifiers, and the org is unchanged. A repeated deletion changes nothing.

**Why this priority**: Principle IX; and AmazonMQ delivers at least once.

**Independent Test**: Consume invalid events and a repeated deletion and check the org.

**Acceptance Scenarios**:

1. **Given** an event whose `data.uuid` is missing or not a UUID, or whose `user_email` is missing, **When** it is consumed, **Then** it is rejected and no org changes.
2. **Given** `project.status.updated` without `status` or with an unknown value, or `project.type.updated` whose `is_multi_agents` is not a boolean, **When** it is consumed, **Then** it is rejected.
3. **Given** `project.updated` with an unknown `timezone`, **When** it is consumed, **Then** it is rejected and no field of the org changes.
4. **Given** an org already released, **When** `project.deleted` arrives again, **Then** the org is not released again and the message is acked.
5. **Given** a valid event for a project with no org in Flows, **When** it is consumed, **Then** it is acked and a warning is logged with `project_uuid` and `event_id`.
6. **Given** an envelope (of any event type, including `project.created`) whose `event_id` contains a space or a line break, or whose `producer` is not a string or `null`, **When** it is consumed, **Then** it is rejected and nothing from it is written to a log line.

---

### Edge Cases

- The same event (same `event_id`) delivered twice: status and type only write on change; `project.updated` writes the same values again, which leaves the org in the same state; deletion is guarded (AC-4).
- A change to the setting needs a restart of both consumer processes (`edaconsume` and `edaconsume-amq`). A change that the legacy consumer applied just before the restart can be applied again by `ProjectConsumer` after it; the edge case above makes that harmless.
- `project.updated` with every applied field `null` (for example a change only to `config` in Connect): only `modified_by` and `modified_on` are written, as the legacy consumer does today.
- `project.status.updated` with `ACTIVE` for a released org: it unsuspends but does not reactivate it, as today (`is_active` is reserved for release).
- An unknown `event_type` on `flows.projects.queue`: still acked and ignored, as today.
- A value of `PROJECT_EVENTS_LEGACY_ACTIONS` that is not one of the four actions: the process refuses to start.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `ProjectConsumer` MUST route `project.updated`, `project.status.updated`, `project.type.updated` and `project.deleted` to `update_project_config`, `update_project_status`, `update_project_type` and `delete_project`.
- **FR-002**: `ProjectConsumer` MUST validate, before calling a use case: `data.uuid` a valid UUID; `user_email` a non-empty string; `status` one of `ProjectStatus`; `is_multi_agents` a boolean; `timezone`, when present, a known time zone; `name`, `description` and `language` strings or `null`. Invalid events MUST raise, be reported to Sentry and be rejected.
- **FR-003**: The service MUST read a list setting `PROJECT_EVENTS_LEGACY_ACTIONS` from the environment (comma-separated), defaulting to `updated,status_updated,project_type_update,deleted`, and MUST fail at start-up if any value is not one of those four.
- **FR-004**: `ProjectConsumer` MUST ack, without calling a use case, an event whose legacy action is in `PROJECT_EVENTS_LEGACY_ACTIONS`, using the mapping `project.updated`→`updated`, `project.status.updated`→`status_updated`, `project.type.updated`→`project_type_update`, `project.deleted`→`deleted`. Validation (FR-002) MUST run first.
- **FR-005**: `ProjectEventConsumer` MUST ack, without calling a use case, a message whose `action` is not in `PROJECT_EVENTS_LEGACY_ACTIONS`. Its behaviour for listed actions MUST stay unchanged.
- **FR-006**: Both consumers MUST log a skipped message as `project_event_skipped` with `event_type` or `action`, `project_uuid`, `event_id` (AmazonMQ only) and the reason.
- **FR-007**: `delete_project` MUST return the org without calling `Org.release` when the org is already inactive, and log that it was already released.
- **FR-008**: A valid AmazonMQ event for a project with no org MUST be acked and logged at `warning`, including `project.updated`, whose use case raises `Org.DoesNotExist` today.
- **FR-009**: The project use cases MUST NOT write the user e-mail to logs.
- **FR-010**: `project.created` handling and the ack of other unknown event types MUST NOT change, apart from the envelope validation of FR-012.
- **FR-011**: `WENI-CHANGELOG.md` MUST gain, under the next version, a `feat:` bullet for consuming the four events from AmazonMQ and the setting, and a bullet deprecating `flows.project-events`.
- **FR-012**: Both consumers MUST validate every externally supplied value they write to a log line, a Sentry tag or the rejection message. On `flows.projects.queue`, `event_id` and `event_type` MUST be strings, and `producer` a string or `null`, that fully match `[A-Za-z0-9._:-]{1,64}`; otherwise the message is rejected before anything is logged, for every event type including `project.created`. On `flows.project-events`, `project_uuid` is written to logs, tags and the rejection message only in canonical form when it parses as a UUID, and is omitted otherwise; the legacy validation and outcome do not change.

### Key Entities

- **Project event (AmazonMQ)**: a `weni-eda` envelope `{event_id, event_type, producer, timestamp, data}` on `flows.projects.queue`; `data.uuid` is `Org.proj_uuid`.
- **Legacy project message (RabbitMQ)**: a flat body with `project_uuid`, `action` and `user_email`, on `flows.project-events`.
- **Org**: `temba.orgs.models.Org`; the events change `name`, `language`, `timezone`, `config` (`description`, `is_multi_agents`), `is_suspended`, `is_active` and `released_on`, plus `modified_by` / `modified_on`.
- **Legacy action list**: the value of `PROJECT_EVENTS_LEGACY_ACTIONS`, the single switch that decides which consumer applies each action.

### Event Contracts Consumed

| `event_type` (routing key) | `data` fields used | Required | Legacy action |
|----------------------------|--------------------|----------|---------------|
| `project.updated` | `uuid`, `user_email`, `name`, `description`, `language`, `timezone` | `uuid`, `user_email` | `updated` |
| `project.status.updated` | `uuid`, `user_email`, `status` | `uuid`, `user_email`, `status` | `status_updated` |
| `project.type.updated` | `uuid`, `user_email`, `is_multi_agents` | `uuid`, `user_email`, `is_multi_agents` | `project_type_update` |
| `project.deleted` | `uuid`, `user_email` | `uuid`, `user_email` | `deleted` |

Bindings the infrastructure must add to `flows.projects.queue` on `projects.topic`: `project.updated`, `project.status.updated`, `project.type.updated`, `project.deleted` (in addition to `project.created`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the legacy action list empty, 100% of the four project events produce the same org state as the equivalent legacy message.
- **SC-002**: For each of the four actions, both when it is in the legacy action list and when it is not, the project change is applied by exactly one consumer in 100% of the dual-delivery test cases.
- **SC-003**: 0 org changes from AmazonMQ events that fail validation, and 0 repeated releases of an already released org.
- **SC-004**: 0 log lines and 0 Sentry events from the project event path containing an e-mail address or a project name.
- **SC-005**: After the switch in production, `flows.project-events` receives no message for 7 consecutive days before it is removed (queue publish rate in Grafana).

## Assumptions

- Connect publishes the envelope and fields described in `weni-engine/specs/005-project-events-amazonmq`, including `user_email` in updated, status and deleted.
- Nexus publishes `project.type.updated` with `data.uuid`, `data.user_email` and `data.is_multi_agents`. Flows keeps requiring `user_email`, as the legacy consumer does, because it resolves the user for `modified_by`. If Nexus cannot send it, the requirement is revisited with the Nexus team before step 4 of Rollout.
- The infrastructure adds the bindings and a dead-letter exchange to `flows.projects.queue` before the legacy action list is changed.
- The two consumer processes receive the same value of `PROJECT_EVENTS_LEGACY_ACTIONS` at the same deploy.

## Non-Functional Requirements

### Peak Load

Measured over 30 days (2026-10-18 to 2026-11-17) on RabbitMQ queues that have no consumer and therefore count every message published. `flows.update-project` (bound to `update-projects.topic`) peaked at 4 messages/min (11/h) for updates, status changes, type changes and deletions together. `flows.projects` (bound to the creation exchange) peaked at 18/min (83/h). Deleting an organization in Connect publishes one `project.deleted` per project in a burst, and each one runs `Org.release`, the heaviest handler (it releases channels). The change adds no per-message external call.

### Observability

- Every consumed project event logs `project_event_consumed` with `event_id`, `event_type`, `project_uuid` and `producer` as structured fields. `event_id` is the correlation identifier; legacy messages have none, so their lines carry `action` and `project_uuid`.
- Before `capture_exception`, both consumers set the Sentry scope tags `project_uuid`, `event_id` (AmazonMQ only), `org_id` when the org exists, and `user_id` when a `User` with the event's e-mail already exists. The `user_id` lookup never creates a user.
- No e-mail, project name or other personal data in logs or Sentry events.

### Failure Handling

- Validation failures and use-case exceptions are reported to Sentry and re-raised, so `EDAConsumer` rejects without requeue. They are recoverable only if `flows.projects.queue` has a dead-letter exchange; that is a rollout prerequisite.
- No external call is added. The consumers themselves only use PostgreSQL, with the existing connection settings. `delete_project` already reaches channel provider APIs (`channel_type.deactivate`) and Mailroom (`mailroom.queue_interrupt`) through `Org.release`; their timeouts are existing behaviour and stay out of scope (Principle XVI).
- Accepted risk: `delete_project` runs `Org.release` inside one transaction, so the transaction and its row locks on the org and its channels stay open while those existing external calls run. A slow provider API delays the commit of one deletion; at the declared peak this is accepted in exchange for an atomic release.
- Idempotency: status and type write only on change; deletion is guarded by FR-007; a repeated update writes the same values.

## Test Strategy

Tests use `TembaTest` (Principle XIV), in `temba/projects/consumers/tests/` and `temba/projects/usecases/tests/`, building envelopes with `Event.build` as `test_project_consumer.py` already does. Consumers are exercised through `handle(message)` with a mocked channel, so ack and reject are asserted, and the use cases run against the test database (not mocked) for the flow tests. Run with `poetry run coverage run manage.py test temba.projects`.

| Criterion | Test |
|-----------|------|
| AC-1, SC-001 | `test_project_consumer.py`: one flow test per event with `override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])`, asserting the org fields, `modified_by` and `basic_ack`. |
| AC-2, SC-002 | `test_project_consumer.py` and `test_project_event_consumer.py`: all four actions with the default list and with `[]` (each action in both states), plus `["project_type_update"]` as the mixed case, asserting which consumer applies the change and that the other acks its copy. A settings test for an unknown value. |
| AC-3, SC-003 | `test_project_consumer.py`: invalid UUID, missing `user_email`, invalid `status`, non-boolean `is_multi_agents`, unknown `timezone`, and envelopes with an unsafe `event_id`, `event_type` or `producer` (including on `project.created`); each asserts `basic_reject(requeue=False)`, `capture_exception`, and an unchanged org. |
| AC-4, SC-003 | `temba/projects/usecases/tests/`: `delete_project` twice; `released_on` is unchanged after the second call. Plus a consumer test with two `project.deleted`. |
| AC-5 | `test_project_consumer.py`: unknown `uuid` for each event is acked and logs a warning. |
| AC-6, SC-004 | Use-case tests with `assertLogs`: no record contains the e-mail or the org name. Consumer test with a captured Sentry event for a rejection whose original exception message contains the e-mail and the org name: neither appears in the event or in the `weni-eda` rejection log. |
| AC-7 | Existing `project.created` tests stay green; a test acks an unknown `event_type`. |
| RG-1 | Review gate: the two `# pragma: no cover` on `consume` are removed and `coverage` reports both methods (quickstart section 1). |
| RG-2 | Review gate: `WENI-CHANGELOG.md` (quickstart section 4). |

## Rollout and Rollback

1. Infrastructure: add the dead-letter exchange and the four bindings to `flows.projects.queue`.
2. Deploy Flows with the default list. `ProjectConsumer` validates and acks the new events without applying them.
3. When Connect spec 005 is deployed (dual publication), set `PROJECT_EVENTS_LEGACY_ACTIONS=project_type_update` on `edaconsume` and `edaconsume-amq`.
4. When Nexus publishes `project.type.updated` to AmazonMQ, set the list to empty.
5. After the legacy publication is switched off and SC-005 holds, remove `ProjectEventConsumer`, its registration in `handle_consumers` and the setting, in a separate change.

Rollback: restore the default list (no code change). Reverting the code is safe: AmazonMQ events other than `project.created` would be acked and ignored again, while the legacy consumer applies every action.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| III. Observability | Structured fields with `event_id`; e-mail removed from use-case logs. | Legacy messages carry no correlation identifier; their lines use `project_uuid` and `action` until the legacy consumer is removed. |
| IV. Versioned Contracts | The consumed contract is additive; the legacy queue is deprecated in `WENI-CHANGELOG.md` with a removal step. No Courier or Mailroom version is required. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`; each AC maps to a test. Coverage exclusions and the changelog are review gates (RG-1, RG-2), not acceptance criteria. | none |
| VIII. Changelog Maintenance | `feat:` and deprecation bullets under the next version. | none |
| IX. Never Trust the Client | Every field used is validated before any write, and every envelope field written to logs or Sentry is validated before it is written (FR-012). | Who may publish to the queue is a broker permission, outside this repository. |
| X. Fail Gracefully | Failures are raised, reported and rejected, never swallowed. No external call is added; the external calls `Org.release` already makes keep their current timeouts. | Recoverability depends on a dead-letter exchange owned by the infrastructure; it is a rollout prerequisite. |
| XII. Scalability and Peak Load | No process state; peak declared. | none |
| XIII. Diagnosable Errors | Sentry tags `project_uuid`, `event_id`, `org_id`, and `user_id` (the opaque `User.id` found by e-mail, without creating a user); no e-mail. | The events carry no account identifier, and Flows has no local mapping from a project to its Connect account, so that tag is absent. `user_id` is absent when no `User` exists yet for the e-mail or when validation fails before the e-mail is known. Pending team decision: the constitution only admits exceptions written in the article itself. |
| XIV. Tests Exercise Flows | Flow tests from message to org state, success and failure paths; `TembaTest`; existing exclusions removed, none added. | none |
| XV. Explicit Over Clever | Event types, the action mapping and the setting are named constants. | none |
| XVI. Contained Changes | Only the project consumers, the setting, the deletion guard and the e-mail in project use-case logs. The deletion guard is needed because AmazonMQ delivers at least once. | none |

## Implementation Decisions

- **One setting per service, read by both consumers**, so the cut-over and the rollback are one environment change and never depend on when bindings are created.
- **Validation before the skip check**, so a malformed AmazonMQ event is visible even while the legacy consumer is authoritative.
- **Unknown event types stay acked** on `flows.projects.queue`, as today, because the queue already receives event types Flows does not handle.
- **`project.deleted` keeps its own handler** (`Org.release`), as decided by the team.
- **Missing org on `project.updated` is acked** in the new consumer, aligning it with the other three handlers; the legacy consumer keeps rejecting it until it is removed.
- **`timezone` is validated at the boundary** so an invalid zone is rejected before any field of the org is written.
- **Envelope fields are validated as short tokens** because they are written into `key=value` log lines, where a space or line break would forge fields. The pattern accepts the UUIDs and producer names (`weni-engine`) the publishers send today.

## Open Questions

None block the plan. Tracked with the Nexus team in `eda-migracao-projetos.md`: whether `project.type.updated` always carries `user_email` (see Assumptions).
