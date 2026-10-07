# Engineering Spec: Multichannel consumer identity

**Feature Branch**: `feat/multichannel-consumer-identity`  
**Created**: 2026-10-07  
**Status**: Draft  
**Product spec**: `vtex-cx-engine-specs` / `specs/009-multichannel-customer-identity/spec.md`

This is the Flows engineering spec. Product requirements and binding decisions live in the product spec and MUST be followed. This document records the HOW inside Flows.

## Inheritance from Product Spec

- Product Spec: Multichannel Consumer Identity — `vtex-cx-engine-specs/specs/009-multichannel-customer-identity/spec.md`
- Pinned version: `c8d007a120bd6cccb67c2eba92afaab773434fc1`
- Architecture doc: `vtex-cx-engine-specs/specs/009-multichannel-customer-identity/architecture.md` @ `c8d007a120bd6cccb67c2eba92afaab773434fc1`
- Inherited binding decisions: BD-001–BD-022, applied only to the Flows slice
- Scope of this spec: Consumer graph on the existing contact, anchors, attachment status, identity audit, attach/detach API, inactivity configuration, and the shared schema for protocol and `msgs_msg.protocol_id`
- Divergences: none

Out of this repository: protocol lifecycle, timers, and follow-up (`mailroom`); inbound protocol resolution (`courier`); the agent `attach` command (`weni-cli`); Live Desk, nexus, Web Chat socket, Studio rename, and commerce connectors.

Coordination plan: `docs/plans/multichannel-consumer-identity-plano.md` in the workspace.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A channel identity stays an orphan until proven (Priority: P1)

A new URN creates or reuses a provisional contact and is stored as `not-attached`. Messaging does not require a Consumer anchor. The same URN does not create a second leaf.

**Why this priority**: Recognition must not block inbound messaging.

**Independent Test**: Create a contact with one WhatsApp URN and another with one Web Chat URN. Assert two contacts, both URNs `not-attached`, and no anchor row.

**Acceptance Scenarios**:

1. **Given** no prior URN, **When** a contact is created for that URN, **Then** the URN `attachment_status` is `not-attached` and no anchor is written.
2. **Given** an existing URN, **When** inbound resolution runs again, **Then** the same contact and URN are returned.
3. **Given** an orphan URN, **When** no attach is called, **Then** no second contact is joined to it.

### User Story 2 - A verified anchor links the URN to one Consumer (Priority: P1)

Attach with a verified anchor creates the Consumer when none exists, or links the URN to the Consumer that already owns that anchor in the same project. Protocols already bound to the URN move with it in the same database transaction. A claimed anchor does not merge histories.

**Why this priority**: This is the join between WhatsApp and Web Chat.

**Independent Test**: Attach an orphan Web Chat URN with a `commerce_user_id` already confirmed on a WhatsApp contact. Assert one Consumer UUID, the Web Chat URN `confirmed` on that contact, and the Web Chat protocol rows now pointing at that contact.

**Acceptance Scenarios**:

1. **Given** no Consumer for a verified anchor in the project, **When** attach runs, **Then** the provisional contact becomes the Consumer, the anchor is stored, and the URN is `confirmed`.
2. **Given** the same verified anchor already on another contact in the project, **When** attach runs, **Then** the URN and its protocols move to that contact and no second Consumer is created.
3. **Given** `verified` is false, **When** attach runs, **Then** status is `claimed` and histories stay separate.
4. **Given** the attach would join two contacts that already hold distinct verified anchors, **When** attach runs, **Then** the response is `conflicting_consumer` and neither contact changes.
5. **Given** two concurrent attaches of the same URN or anchor, **When** both commit, **Then** exactly one wins and the other receives `conflicting_consumer`.
6. **Given** an empty or malformed anchor, **When** attach runs, **Then** the response is `validation` and the graph is unchanged.

### User Story 3 - A mistaken link is reassigned (Priority: P1)

Detach moves the URN and the protocols bound to it to a target Consumer, or back to `not-attached` when no target is given. It requires a valid confirmation code or a privileged actor. Tickets and CSAT stay on the protocols that move.

**Why this priority**: A false link corrupts two people.

**Independent Test**: Confirm an attach, detach with a valid code to a second contact, and assert the URN and its protocols belong to the target. Repeat with an expired code and assert nothing moved.

**Acceptance Scenarios**:

1. **Given** a confirmed URN, **When** detach is requested without a valid code and without privilege, **Then** the response is `confirmation_required` and the link stays.
2. **Given** a valid code and a target Consumer, **When** detach runs, **Then** the URN and its protocols belong to the target.
3. **Given** a valid code and no target, **When** detach runs, **Then** the URN is `not-attached` and keeps its protocols.
4. **Given** a target that would collide on a verified anchor, **When** detach runs, **Then** the response is `conflicting_consumer` and nothing moves.
5. **Given** an already orphan URN, **When** detach runs, **Then** the operation is an audited no-op.

### User Story 4 - Every identity change is auditable (Priority: P1)

Attach, detach, conflict, deletion, and no-op each write one identity event with actor, time, anchor type, URN, affected protocols, resulting Consumer, resulting status, and outcome.

**Independent Test**: Run one success, one conflict, and one no-op. Assert three events with those fields and the matching outcome.

**Acceptance Scenarios**:

1. **Given** any attach or detach outcome, including refusal, **When** the call returns, **Then** one `contacts_identityevent` row records that outcome.
2. **Given** a caller outside the project, **When** they call attach, detach, or read the graph, **Then** the response is `forbidden` and no event is written for another project.

### User Story 5 - Stream messages stay writable without a protocol (Priority: P1)

`POST /api/v2/internals/messages/stream` keeps inserting a message when `protocol_id` is absent. When the caller sends a `protocol_id` that belongs to the project, the message stores it.

**Why this priority**: Nexus writes stream messages directly. A required protocol id would break that path before Nexus changes.

**Independent Test**: Post a stream message without `protocol_id` and assert `201` with a null protocol. Post another with a protocol of the same project and assert the foreign key. Post a protocol from another project and assert `400`.

**Acceptance Scenarios**:

1. **Given** a stream body without `protocol_id`, **When** it is posted, **Then** the message is stored and `protocol_id` is null.
2. **Given** a stream body with a `protocol_id` of the same project, **When** it is posted, **Then** the message references that protocol.
3. **Given** a `protocol_id` from another project or an unknown id, **When** it is posted, **Then** the request is rejected and no message is stored.

### Edge Cases

- A Consumer whose last URN was detached stays addressable and can receive a later attach. The provisional contact left with zero URNs is archived and is not a second Consumer.
- The same anchor value in another org does not match.
- Tax document and verified email are normalized before uniqueness is checked. `commerce_user_id` is compared as given.
- Inactivity hours outside 1–24 (AI) or 1–672 (human) are rejected and the previous org config remains.
- Repeated identical attach of a URN already `confirmed` on that Consumer is an audited no-op.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Flows MUST realize the Consumer as `contacts_contact`. It MUST NOT add a parallel person table.
- **FR-002**: Flows MUST add `contacts_contacturn.attachment_status` with values `not-attached`, `claimed`, and `confirmed`, defaulting to `not-attached` for new and existing rows.
- **FR-003**: Flows MUST add table `contacts_anchor`, unique on `(org_id, anchor_type, value)`, for `commerce_user_id`, `verified_email`, and `tax_document`.
- **FR-004**: Flows MUST add table `contacts_identityevent` with columns `actor`, `created_on`, `anchor_type`, `urn_id`, `affected_protocol_ids`, `consumer_id`, `attachment_status`, and `outcome`.
- **FR-005**: Flows MUST add table `msgs_protocol` and nullable `msgs_msg.protocol_id`. `protocol_id` MUST NOT be `NOT NULL`.
- **FR-006**: Flows MUST expose one attach operation and one detach operation. Both run in a single database transaction that updates the URN, the anchor, the audit row, and `msgs_protocol.contact_id` for protocols of that URN.
- **FR-007**: Flows MUST scope every read and write by the caller's project, mapped to `org_id` through `internal_project.project_uuid`.
- **FR-008**: Flows MUST accept an optional `protocol_id` on `POST /api/v2/internals/messages/stream` and MUST keep accepting the current body with no protocol.
- **FR-009**: Flows MUST store per-project inactivity hours on the org config the mailroom already reads: `ai_inactivity_hours` (1–24, default 1) and `human_inactivity_hours` (1–672, default 96).
- **FR-010**: Flows MUST NOT implement protocol open/close, timers, follow-up, or courier ingest.

### Key Entities

- **Consumer**: existing contact. Opaque UUID. Owns URNs, anchors, and protocols.
- **Channel identity**: existing URN plus `attachment_status`.
- **Anchor**: proof of personhood, unique per type and value inside the org.
- **Identity event**: audit row for attach, detach, conflict, deletion, and no-op.
- **Protocol**: new structure. Flows owns the table; mailroom owns the lifecycle.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Two URNs in one project attached with the same verified anchor resolve to one contact UUID in the same request.
- **SC-002**: Two URNs that never attach remain two contacts, both messageable.
- **SC-003**: 100% of attach, detach, conflict, and no-op calls in the test suite leave one identity event with actor and outcome.
- **SC-004**: An anchor used in project A never resolves to a contact in project B.
- **SC-005**: A stream post without `protocol_id` returns success and stores a message. A stream post with a foreign protocol is rejected.
- **SC-006**: Attach or detach that the test suite runs twice with the same body does not create a second Consumer or a second event beyond the audited no-op.

## Assumptions

- Project isolation is the existing org. External contracts say `project_id`; persistence uses `org_id`.
- The product spec is pinned by commit because that commit has no release tag. The pin moves to the tag when one exists.
- Protocol lifecycle is specified in the mailroom engineering spec. This spec only creates the table and moves `contact_id` inside the attach transaction.
- Nexus will later send `protocol_id` on the stream body. Until then the column stays null on that path.
- Studio rename of Contact to Consumer is a later task in this repository and does not block the API.
- Detach confirmation delivery reuses the contact's registered email or phone. Privileged actors may bypass the code.
