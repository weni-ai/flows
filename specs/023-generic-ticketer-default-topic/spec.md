# Engineering Specification: Default topic on generic ticketer departments

**Repository**: weni-ai/flows — backend

**Feature Branch**: `feat/generic-ticketer-default-topic`

**Created**: 2026-11-25

**Status**: Draft

**Input**: User description: "GET /api/v2/internals/get_departments lists active ticketers for a project and, for each one, fills topics only from TicketerQueue rows. Weni Chats ticketers have those queues. A generic ticketer never has TicketerQueue rows, so topics is always empty. The external ticketer service needs at least one department. Every project already has a default ticket topic named General. Returning that topic for a generic ticketer with no active queues is enough. Suggested cycle: SDD Lite. No migration, no new endpoint, no Mailroom or Courier change."

**Suggested cycle**: SDD Lite. One read-path change on the existing internal departments list, tests in the existing departments test class, and one changelog bullet. No migration, no new endpoint, no change to `get_queues`, `open_ticket`, or the public topics list, and no Mailroom or Courier change. Promote to SDD Full with `/speckit-plan` only if implementation needs a migration or a contract change outside this list.

## Origin Without Product Spec

- Product Spec: none
- Problem: The internal departments list returns an empty topic list for a generic ticketer, because that list is filled only from the ticketer's active queues and a generic ticketer has none. The external ticketer service needs at least one department, and every project already has a default ticket topic.
- Acceptance criteria:
  - AC-1: When an active ticketer is type `generic` and has no active queue, its `topics` list contains exactly one item: the project's default ticket topic.
  - AC-2: That item keeps the existing topic shape. `topic_name` is the default topic's current name (`General` until the project renames it). `topic_uuid` is the default topic's own identifier, the same identifier `open_ticket` already uses when no topic is supplied for a non-Weni-Chats ticketer. It is not the topic's queue identifier and not a queue row identifier. `topic_purpose` is null.
  - AC-3: When a generic ticketer already has one or more active queues, the list contains only those queues. The default topic is not appended.
  - AC-4: A Weni Chats ticketer, and any other ticketer that has active queues, is unchanged: the list contains only those queues.
  - AC-5: A ticketer whose type is not `generic` and that has no active queues still returns `topics` as an empty list.
  - AC-6: The read does not create a topic or a queue. `get_queues`, `open_ticket`, and the public topics list are unchanged. Inactive queues do not count as departments. A generic ticketer whose queues are all inactive is treated as having no active queue (AC-1).
  - AC-7: `GetDepartmentsViewTest` covers a generic ticketer with no queue, a generic ticketer with an active queue, an existing Weni Chats ticketer with a queue, a non-generic ticketer with no queue, and a generic ticketer with only inactive queues. The repository's usual test, style, and CI gates stay green. No new coverage exclusion.
  - AC-8: `WENI-CHANGELOG.md` gains one `feat` bullet under the next unreleased version heading. An already released version is not extended. The upstream changelog is not rewritten.

## Scope in This Repository

**This repository implements**:

- Filling `topics` on the existing internal departments list with the project's default ticket topic when the ticketer is generic and has no active queue.
- Keeping the current queue list for every ticketer that already has an active queue, including generic and Weni Chats.
- Keeping an empty topic list for every non-generic ticketer that has no active queue.
- Tests in `temba/api/v2/internals/tickets/tests.py`, class `GetDepartmentsViewTest`.
- One `feat` bullet in `WENI-CHANGELOG.md` under the next unreleased version heading.

**Out of scope here**:

- Creating or updating a topic or a queue, including a queue that would point a generic ticketer at General.
- `get_queues`, `open_ticket`, and the public topics contract.
- Mailroom and Courier.
- A new endpoint, a migration, or a change to who may call the departments list.
- Returning the default topic for ticketer types other than `generic`.

## Current State

- `GET /api/v2/internals/get_departments` lists active ticketers for the project in `project`, optionally filtered by ticketer `uuid`. The body is `{"results": [...]}`. Each item has `ticketer_uuid`, `ticketer_name`, `type`, `created_on`, and `topics`.
- On the committed line, `topics` is filled only from that ticketer's active queue rows. Each queue becomes `topic_name` (queue name), `topic_uuid` (queue identifier), and `topic_purpose` (queue purpose, which may be null). A ticketer with no active queue, including every generic ticketer, returns `"topics": []`.
- A generic ticketer is `ticketer_type` `generic`. Weni Chats ticketers are the ones that have queue rows today.
- Every project is created with one default ticket topic. Its name starts as `General`, `is_default` is true, and it is the row `open_ticket` already selects when the caller omits a topic for any ticketer that is not Weni Chats. That row has its own identifier and a separate queue identifier. Only the topic identifier is valid for opening a ticket.
- The public topics list and `get_queues` already expose that default topic as a topic. This change does not alter those responses.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A generic ticketer offers its default department (Priority: P1)

An external ticketer service asks for the departments of a project whose ticketing service is generic. That service has no queues of its own. The caller needs one department so it can open a ticket, and the department it receives is the project's default topic, the same topic a ticket already opens on when no topic is chosen.

**Why this priority**: An empty department list blocks the external service. The default topic already exists on every project, so returning it unblocks ticket opening without storing anything new.

**Independent Test**: Create a generic ticketer with no queue, request that project's departments, and check that this ticketer has exactly one topic: name `General`, the default topic's own identifier, and a null purpose.

**Acceptance Scenarios**:

1. **Given** an active generic ticketer and no queue rows for it, **When** the departments list is requested, **Then** that ticketer's `topics` has exactly one item, `topic_name` is the default topic's name, `topic_uuid` is the default topic's identifier, and `topic_purpose` is null.
2. **Given** the same ticketer, **When** the item is compared with the topic used to open a ticket with no topic supplied, **Then** both identifiers are the default topic's own identifier, and neither is the topic's queue identifier.
3. **Given** a generic ticketer whose only queues are inactive, **When** the departments list is requested, **Then** the result is the same single default topic, and no inactive queue appears.

---

### User Story 2 - Ticketers that already have departments stay as they are (Priority: P1)

A project that uses Weni Chats, or a generic ticketer that already has active queues, already receives those queues as departments. Callers that depend on that list must not gain an extra General row, and must not lose a queue.

**Why this priority**: Adding General beside real queues would offer a department the ticketer did not configure and would change a response that already works.

**Independent Test**: Request departments for a Weni Chats ticketer that has one queue, and for a generic ticketer that has one active queue. Each response contains only that queue.

**Acceptance Scenarios**:

1. **Given** a Weni Chats ticketer with one active queue, **When** the departments list is requested, **Then** `topics` contains only that queue, with that queue's name, identifier, and purpose.
2. **Given** a generic ticketer with one active queue, **When** the departments list is requested, **Then** `topics` contains only that queue and does not also contain the default topic.
3. **Given** a project with both a Weni Chats ticketer that has a queue and a generic ticketer that has none, **When** the departments list is requested, **Then** each ticketer is filled on its own: the Weni Chats ticketer has only its queue, and the generic ticketer has only the default topic.

---

### User Story 3 - Other ticketers without queues stay empty (Priority: P2)

A ticketer that is not generic and has no queues still has nothing to offer as a department. The list must not invent the default topic for that type.

**Why this priority**: The fallback exists only so a generic ticketer can satisfy the external service. Applying it to every empty ticketer would change types this request did not ask to change.

**Independent Test**: Create a non-generic ticketer with no queue, request departments, and check that its `topics` list is empty.

**Acceptance Scenarios**:

1. **Given** an active ticketer whose type is not `generic` and that has no queue, **When** the departments list is requested, **Then** that ticketer is still listed and `topics` is `[]`.

---

### Edge Cases

- **Inactive queues only**: they are not departments. A generic ticketer in that state returns the single default topic. A non-generic ticketer in that state still returns an empty list.
- **Renamed default topic**: `topic_name` is the name stored on the default topic today, not a hard-coded `General`. The identifier stays the default topic's own identifier.
- **Queue identifier**: the default topic also has a queue identifier. That value must not be sent as `topic_uuid`. Sending it would not match the topic `open_ticket` resolves.
- **Several generic ticketers on one project**: each with no active queue returns the same default topic, because a project has one default topic. No second topic is created.
- **Inactive ticketer**: it is still omitted. This change does not widen the list of ticketers.
- **Optional ticketer filter**: requesting one ticketer by `uuid` uses the same topic rules as the full list.
- **Missing default topic**: projects are created with one. This read does not create a replacement. If the default topic cannot be read, the request fails and no topic or queue is inserted.
- **Purpose**: the synthetic item sends `topic_purpose` as null. The field is present. It is not omitted and it is not an empty string.
- **No other writes**: repeated reads do not add topics, queues, or tickets.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For an active ticketer of type `generic` with no active queue, the departments list MUST return exactly one topic item, the project's existing default ticket topic.
- **FR-002**: That item MUST use the existing topic fields: `topic_name` is the default topic's current name, `topic_uuid` is the default topic's own identifier, and `topic_purpose` is null.
- **FR-003**: `topic_uuid` MUST be the same identifier `open_ticket` already selects for that project when no topic is supplied for a non-Weni-Chats ticketer. It MUST NOT be the default topic's queue identifier or any queue-row identifier.
- **FR-004**: A generic ticketer with at least one active queue MUST return only those active queues, with the same fields those queues return today, and MUST NOT append the default topic.
- **FR-005**: A Weni Chats ticketer, and any other ticketer that has active queues, MUST keep returning only those active queues.
- **FR-006**: A ticketer whose type is not `generic` and that has no active queue MUST return `topics` as an empty list.
- **FR-007**: Inactive queues MUST NOT appear in `topics` and MUST NOT block the generic default-topic fallback.
- **FR-008**: The read MUST NOT create or update a topic, a queue, or a ticket.
- **FR-009**: `get_queues`, `open_ticket`, and the public topics list MUST keep their current request and response contracts.
- **FR-010**: The set of ticketers returned, the optional `uuid` filter, and the other ticketer fields (`ticketer_uuid`, `ticketer_name`, `type`, `created_on`) MUST stay as they are. Who may call the list MUST stay as it is.
- **FR-011**: `WENI-CHANGELOG.md` MUST gain one `feat` bullet under the next unreleased version heading. A heading that is already released MUST NOT receive this bullet. `CHANGELOG.md` MUST NOT be rewritten.

### Key Entities

- **Ticketer**: an active ticketing service on a project. `type` `generic` is the external generic service. Weni Chats is a different type and is configured with queues.
- **Queue**: a department configured on a ticketer. Only active queues are departments in this list. A generic ticketer normally has none.
- **Default ticket topic**: the one topic created with the project, initially named General, flagged as the default. It is the topic a ticket opens on when the caller does not choose one for a non-Weni-Chats ticketer. It has its own identifier, distinct from its queue identifier.
- **Department item**: one entry in `topics`, with `topic_name`, `topic_uuid`, and `topic_purpose`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On every departments response, 100% of active generic ticketers with no active queue include exactly one topic, and that topic is the project's default ticket topic.
- **SC-002**: On every departments response, 100% of ticketers that have an active queue list only those queues, with no added default topic.
- **SC-003**: On every departments response, 100% of non-generic ticketers with no active queue still have an empty topic list.
- **SC-004**: For a generic ticketer with no active queue, the returned topic identifier matches the topic a ticket already opens on when no topic is chosen, and a caller can open a ticket with that identifier without any new topic or queue having been stored.
- **SC-005**: The public topics list and the queues list are unchanged, and the next unreleased version notes include exactly one feature bullet for this behavior.

## Assumptions

- Every project already has exactly one default ticket topic, created with the project and initially named General. A project may have renamed it. This change reads that row and does not recreate it.
- "No queues" means no active queue rows for that ticketer. Inactive rows are ignored, matching the list's current rule that only active queues are returned.
- The external service only needs a department for ticketer type `generic`. Other types with an empty queue list stay empty.
- `open_ticket` already falls back to the project's default ticket topic for every ticketer that is not Weni Chats. This change does not alter that fallback. It only makes the departments list advertise the same topic.
- The departments list remains an internal read. Its caller check is unchanged.
- One `feat` bullet is enough. The top heading of `WENI-CHANGELOG.md` is used only when that version is still unreleased.
- **Peak load (Principle XII)**: unchanged. The declared peak is the current peak of `GET /api/v2/internals/get_departments` for the busiest project, not an average and not a new traffic class. The change adds no endpoint, worker, or stored row. On that peak it still lists the project's active ticketers, and it adds at most one topic object in memory for each generic ticketer that has no active queue.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-1 generic ticketer, no queue, one default topic | Extend `GetDepartmentsViewTest` in `temba/api/v2/internals/tickets/tests.py`. Create a generic ticketer with no `TicketerQueue`. `GET /api/v2/internals/get_departments?project=<proj_uuid>&uuid=<ticketer uuid>` returns 200 and that ticketer in `results` with `topics` of length 1. `topic_name` equals the default topic's name (`General` on a fresh project). `topic_purpose` is `None`. |
| AC-2 shape and the open-ticket identifier | The same response asserts `topic_uuid` equals `str(org.default_ticket_topic.uuid)` and differs from `str(org.default_ticket_topic.queue_uuid)`. No `TicketerQueue` exists for the ticketer, so the identifier cannot be a queue-row identifier. `open_ticket` is not modified; the assertion is that this uuid is the `Topic.uuid` that `OpenTicketSerializer` already assigns from `org.default_ticket_topic` when the topic is omitted for a non-Weni-Chats ticketer. |
| AC-3 generic ticketer that already has a queue | A second test creates a generic ticketer and one active `TicketerQueue`. `topics` contains only that queue (`topic_name`, `topic_uuid` = queue uuid, `topic_purpose` = queue purpose) and does not contain the default topic's uuid. |
| AC-4 Weni Chats unchanged | The existing Weni Chats case in `test_get_departments_with_uuid` still expects only its queue. It stays green and is not weakened. |
| AC-5 non-generic, no queue | A test creates a non-generic ticketer (Weni Chats with no `TicketerQueue` is enough) and asserts `topics` is `[]`. |
| AC-6 no writes, inactive queues, other contracts untouched | The generic no-queue test asserts the topic count and the queue count for that ticketer are unchanged by the GET. A sibling creates a generic ticketer with only an inactive queue and asserts the single default-topic item and that the inactive queue's uuid is absent. No test edits `GetQueuesView`, `OpenTicketSerializer`, or the public topics API, and no migration file is added. |
| AC-7 gates | `poetry run coverage run manage.py test temba.api.v2.internals.tickets.tests.GetDepartmentsViewTest` covers the class. The pull request stays within clean `./code_check.py` and a green `.github/workflows/ci.yml`. No new `# pragma: no cover`. |
| AC-8 changelog | The pull request adds one `feat:` bullet under the next unreleased heading in `WENI-CHANGELOG.md`. If the top heading is already released, the bullet goes under a new heading above it. `CHANGELOG.md` is not edited. |

**Flow coverage** (Principle XIV): one test calls `GET /api/v2/internals/get_departments` for a generic ticketer with no queue, the way the external service does, and asserts the single default-topic item in `results`. That is the complete use case. The Weni Chats queue case, the generic-with-queue case, the non-generic empty case, and the inactive-queue case are siblings on the same view.

**Failure paths**: there is no new error body. The paths that must stay empty or queue-only are the non-generic ticketer, the generic ticketer with an active queue, and the existing Weni Chats ticketer. A missing default topic is not manufactured; the read uses the existing `org.default_ticket_topic` lookup and does not catch a missing row by inserting one.

**Gates**: `poetry run coverage run manage.py test temba.api.v2.internals.tickets.tests.GetDepartmentsViewTest`, clean `./code_check.py`, green `.github/workflows/ci.yml`. Tests use `TembaTest`, which this class already uses.

## Rollout and Rollback

1. Deploy Flows. No migration and no Courier or Mailroom deploy.
2. Call the departments list for a project whose generic ticketer has no queue. Confirm one topic named with the project's default topic, and confirm a ticket opened with that identifier uses the default topic.
3. Call the list for a Weni Chats project and confirm its queues are unchanged and General was not added.
4. **Rollback:** revert the read-path change. Generic ticketers with no queue return an empty topic list again. No stored topic or queue needs to be removed, because none was written.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | Delivered through a PR to `main` with review and green `ci.yml`. | none |
| II. Security and Secrets | No new secret, dependency, or credential. Ticketer config is not added to this response. | none |
| III. Observability | No new log line. The existing request trace for the departments list remains the trace. | none |
| IV. Versioned Contracts | No new endpoint, no public topics change, no channel config, no event payload, no migration, no Courier or Mailroom version bump. The internal departments list gains one topic item only for a generic ticketer that previously returned an empty list. Field names are unchanged. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`. Each acceptance criterion maps to a check in Test Strategy. | none |
| VI. No Silent Divergence | Not applicable: no Product Spec. | none |
| VII. Commit Messages | Atomic Conventional Commits, descriptions of 50 characters or fewer. | none |
| VIII. Changelog Maintenance | One `feat:` bullet in `WENI-CHANGELOG.md` under the next unreleased version heading. A released heading is not extended. `CHANGELOG.md` is not rewritten. | none |
| IX. Never Trust the Client | No new input. The topic is taken from the project's stored default topic, not from the request body. | none |
| X. Fail Gracefully | No new outbound call. A missing project still returns the existing not-found response. A missing default topic is not replaced by an insert. | none |
| XI. Bounded Retry Over REST | No new REST propagation. | none |
| XII. Scalability and Peak Load | Stateless read. Declared peak is the current peak of this departments list for the busiest project. No new stored state. At most one extra topic object per generic ticketer that has no active queue. | none |
| XIII. Diagnosable Errors | No new Sentry event. The response adds a topic name and an opaque topic identifier the list already knows how to return for queues. | Platform `send_default_pii=True` remains `TODO(SENTRY_PII)`. |
| XIV. Tests Exercise Flows | The departments GET for a generic ticketer with no queue is the full use case, with queue, Weni Chats, non-generic, and inactive-queue siblings. `TembaTest`. | none |
| XV. Explicit Over Clever | The generic fallback is a direct branch after the active-queue lookup: type `generic` and no active queue returns the one existing default topic. No new topic and no new queue. A short comment states why `topic_uuid` is the topic identifier rather than the topic's queue identifier: `open_ticket` resolves the topic identifier. | none |
| XVI. Contained Changes | The departments topic list, its tests, and one changelog bullet. `get_queues`, `open_ticket`, the public topics list, Mailroom, and Courier stay as they are. | none |
| XVII. Explicit, Scoped Authorization | No new endpoint and no change to the departments list's caller check. This change does not add `IsAuthenticated`, `AllowAny`, or an empty permission. | The list's current internal caller check is left as it is. Replacing it is `TODO(DRF_PERMISSIONS)` and is out of scope. |
| Backend Standards | `code_check.py`. No new locale string. No view logic beyond the existing delegation to the departments serializer. | none |

## Implementation Decisions

- SDD Lite: one branch in the existing departments topic lookup. No `plan.md` and no `tasks.md`.
- Active queues win. The default topic is used only when the ticketer type is `generic` and the active-queue lookup is empty.
- The item is built from the existing default topic row. `topic_name` is `Topic.name`, `topic_uuid` is `Topic.uuid`, `topic_purpose` is null. `Topic.queue_uuid` is never written into `topic_uuid`.
- Nothing is inserted. A second read returns the same item because the default topic is already there.
- `GetQueuesView`, `OpenTicketSerializer`, and the public topics serializer are not edited.

## Open Questions

None. The fallback is limited to generic ticketers with no active queue, the identifier is the one `open_ticket` already uses, and no stored row is created.
