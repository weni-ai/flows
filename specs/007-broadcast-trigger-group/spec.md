# Engineering Spec: Managed trigger group for WhatsApp broadcast

**Feature Branch**: `007-broadcast-trigger-group`  
**Created**: 2026-08-31  
**Status**: Draft  
**Product spec**: `vtex-cx-engine-specs` / `specs/007-broadcast-trigger-group/spec.md`

This is the Flows engineering spec. Product requirements, binding decisions, and API contracts live in the product spec and MUST be followed. This document records the HOW inside Flows.

## User Scenarios & Testing *(mandatory)*

Covered by the product spec journeys (URN-only campaign, most recent campaign wins, mixed audience). Engineering tests MUST exercise all three write entry points that share `WhatsappBroadcastWriteSerializer`.

### User Story 1 - URN-only campaign with a working reply flow (Priority: P1)

Integrator posts `urns` + `trigger_flow_uuid` with no group. Flows materializes a managed static group for that flow, ensures a Catch All, resolves/creates contacts, adds them to the group, then dispatches.

**Independent Test**: Internal WhatsApp broadcast with two new URNs and a messaging flow. Assert one managed group, one Catch All, both contacts are members, `metadata.trigger_group` is present, `groups` in the response stays empty.

### User Story 2 - Most recent campaign wins (Priority: P1)

A contact included in a later broadcast with a different `trigger_flow_uuid` is moved atomically to that flow's managed group.

### User Story 3 - Mixed audience and unchanged existing integrations (Priority: P2)

`groups` + `urns` + `trigger_flow_uuid`: caller-supplied groups keep today's Catch All; URNs go through the managed group. Requests without `trigger_flow_uuid` are unchanged.

## Functional requirements (engineering)

See product spec FR-001–FR-025. Implementation notes:

- **FR-001 / BD-010**: Remove the `queue=template_batch` restriction on `trigger_flow_uuid` in `WhatsappBroadcastWriteSerializer.validate`.
- **FR-003 / BD-003**: Persist the flow↔group association in `msgs.ManagedTriggerGroup` (OneToOne on `Flow`). Never resolve by group name.
- **FR-007**: Exactly one active Catch All per managed group; restore if archived, recreate if missing.
- **FR-008–FR-012**: Resolve URNs via `Contact.from_urn`, create missing via `Contact.create` (mailroom), then one `Contact.bulk_modify` with add-to-target + remove-from-other-managed-groups.
- **FR-014**: Caller-supplied `groups` still use `create_catchall_trigger` as today.
- **FR-018 / FR-019**: Write `metadata.trigger_group = {uuid, name}`. Do not add the managed group to broadcast recipients.
- **FR-021**: All three entry points already share the write serializer; keep it that way.
- **FR-023**: Enforce `Org.LIMIT_GROUPS` only when creating a new group.
- **FR-024**: If the associated group is inactive or the Catch All is archived/missing, recreate/restore on the next broadcast.

## Key entities

- `ManagedTriggerGroup`: org + flow (unique) + group
- Existing: `ContactGroup` (static), `Trigger` (Catch All), `Broadcast`, `Contact`

## Assumptions

- Mailroom contact create/modify and inbound Catch All routing are unchanged.
- Unqualified phone URNs follow existing URN parsing (`002-whatsapp-default-urn`).
- `TembaTest` runs inside an atomic block; URN create concurrency MUST fall back to sequential in that case so tests share the test transaction.
