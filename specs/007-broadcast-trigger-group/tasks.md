# Tasks: Managed trigger group for WhatsApp broadcast

**Input**: [plan.md](./plan.md)  
**Prerequisites**: [spec.md](./spec.md)

## Phase 1: Setup

- [x] T001 Extract SpecKit onto `chore/add-speckit` from `main` (same blobs as telephony init)
- [x] T002 Create feature branch `007-broadcast-trigger-group` from SpecKit branch

## Phase 2: Foundational

- [x] T003 Add `ManagedTriggerGroup` model on `msgs` and migration `0174`
- [x] T004 Add `WHATSAPP_BROADCAST_URN_RESOLVE_CONCURRENCY` in `settings_common.py`

## Phase 3: User Story 1 (P1)

- [x] T005 [US1] Use-case: resolve/create managed group, Catch All, quota, display name
- [x] T006 [US1] Use-case: resolve/create contacts from URNs
- [x] T007 [US1] Serializer: allow `trigger_flow_uuid` without `template_batch`; run use-case before dispatch; `metadata.trigger_group`
- [x] T008 [US1] Tests: URN-only 201, group + Catch All, metadata, empty `groups` list

## Phase 4: User Story 2 (P1)

- [x] T009 [US2] Exclusive membership move in one `contact_modify`
- [x] T010 [US2] Tests: contact moves from flow A group to flow B group

## Phase 5: User Story 3 (P2)

- [x] T011 [US3] Preserve Catch All over caller-supplied groups; do not copy those members
- [x] T012 [US3] Tests: groups-only unchanged; mixed urns+groups; no `trigger_flow_uuid` unchanged

## Phase 6: Polish

- [x] T013 Recreate inactive group / restore archived Catch All
- [x] T014 Public v2 coverage for URN + `trigger_flow_uuid`
- [ ] T015 Run targeted Django tests
