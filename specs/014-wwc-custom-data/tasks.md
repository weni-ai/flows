# Tasks: custom_data on WhatsApp Broadcasts (Flows slice)

**Input**: Design documents from `specs/014-wwc-custom-data/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/whatsapp-broadcast-custom-data.md](./contracts/whatsapp-broadcast-custom-data.md)

**Tests**: Included (spec Test Strategy + Principle XIV). Write failing tests before implementation in each story phase.

**Organization**: Tasks are grouped by user story (all P1). Shared helpers live in Foundational because US1–US3 share `validate_msg`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3 from spec.md
- Include exact file paths in descriptions

## Path Conventions

Repository is a Django monolith under `temba/`. Unit helpers: `temba/msgs/custom_data.py` and `temba/msgs/tests_custom_data.py` (same naming as `temba/msgs/tests_cost_service.py`; do not add `temba/msgs/tests/` package).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Feature workspace ready; no product code yet

- [x] T001 Confirm feature directory `specs/014-wwc-custom-data/` has spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md
- [x] T002 Create or switch to git branch `014-wwc-custom-data` from the current integration branch without changing `temba/mailroom/queue.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared AD-002 helpers and serializer hook so stories can add tests without duplicating tree-walk logic

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Add `CUSTOM_DATA_MAX_SERIALIZED_BYTES`, `CUSTOM_DATA_MAX_DEPTH`, and OpenAPI error-string constants in `temba/msgs/custom_data.py`
- [x] T004 Implement `validate_custom_data` and `normalize_custom_data_in_msg` in `temba/msgs/custom_data.py` (type, compact `json.dumps` UTF-8 size, depth with root object = 1, keys starting with `$` or containing `.` at any nesting level, `{}` → absence)
- [x] T005 Write unit tests for helpers in `temba/msgs/tests_custom_data.py` covering depth 32 vs 33, nested forbidden keys (including object inside array), byte boundary, `null`/non-object, and `{}` normalization
- [x] T006 Call helpers from `WhatsappBroadcastWriteSerializer.validate_msg` in `temba/api/v2/serializers.py` after existing content checks; map `ValueError` to `serializers.ValidationError` so errors land under `msg`; strip `{}` from returned `msg`

**Checkpoint**: Foundation ready — `poetry run coverage run manage.py test temba.msgs.tests_custom_data` can run; HTTP story tests still fail until later phases

---

## Phase 3: User Story 1 - Attach opaque custom_data (Priority: P1) 🎯 MVP

**Goal**: Valid `msg.custom_data` on all three write entry points creates a broadcast, persists metadata unchanged, and the Mailroom task `msg` carries the object without editing `queue.py` (AC-1, AC-4, AC-5 persist path)

**Independent Test**: POST the OpenAPI example on public, internal Django, and FastAPI; assert `201`, `Broadcast.metadata["custom_data"]` equals the object; after `send_async`, queued `send_whatsapp_broadcast` has `task.msg.custom_data`. Repeat with no `channel` and with a non-WWC channel.

### Tests for User Story 1

> Write these tests FIRST, ensure they FAIL before relying on T006 behavior for HTTP

- [x] T007 [P] [US1] Add public v2 success tests (OpenAPI example, no channel, WAC channel) in `temba/api/v2/tests.py` next to `test_whatsapp_broadcasts`
- [x] T008 [P] [US1] Add internal Django success tests in `temba/api/v2/internals/broadcasts/tests.py` on `TestInternalWhatsappBroadcast`
- [x] T009 [P] [US1] Add FastAPI success tests in `temba/fastapi_app/tests.py` on `TestPostInternalWhatsappBroadcast`
- [x] T010 [US1] Assert queued batch task `msg.custom_data` using the `assert_queued_batch_task` pattern from `temba/mailroom/tests.py` without modifying `temba/mailroom/queue.py` (place in `temba/api/v2/tests.py` or `temba/mailroom/tests.py` only if the latter already owns the fixture)

### Implementation for User Story 1

- [x] T011 [US1] Ensure `validate_msg` in `temba/api/v2/serializers.py` leaves a valid non-empty object on `msg` so `Broadcast.create` stores it on `metadata` (FR-006, FR-007, FR-008)
- [x] T012 [US1] Confirm `git diff` does not include `temba/mailroom/queue.py`

**Checkpoint**: User Story 1 independently testable via the three POST success paths

---

## Phase 4: User Story 2 - Reject invalid custom_data (Priority: P1)

**Goal**: `null`, non-object, oversized, too deep, or forbidden keys return HTTP 400 with exact OpenAPI strings under `msg` and create no `Broadcast` (AC-3)

**Independent Test**: POST each invalid shape on all three entry points; assert `400`, exact `msg` list, `Broadcast` count unchanged.

### Tests for User Story 2

- [x] T013 [P] [US2] Public v2 400 cases in `temba/api/v2/tests.py`: `null`, `"x"`, `[]`, `1`, compact payload >16384 bytes, depth 33, key `$x`, nested `a.b`, object-in-array with `.` in a key
- [x] T014 [P] [US2] Same invalid shapes in `temba/api/v2/internals/broadcasts/tests.py`
- [x] T015 [P] [US2] Same invalid shapes in `temba/fastapi_app/tests.py`
- [x] T016 [US2] Assert error bodies match [contracts/whatsapp-broadcast-custom-data.md](./contracts/whatsapp-broadcast-custom-data.md) strings and no `Broadcast` row is created in those three test files

### Implementation for User Story 2

- [x] T017 [US2] Align `validate_custom_data` in `temba/msgs/custom_data.py` and `validate_msg` mapping in `temba/api/v2/serializers.py` so DRF/FastAPI emit only the four contract messages (FR-001–FR-004, FR-011)

**Checkpoint**: User Stories 1 and 2 both pass independently

---

## Phase 5: User Story 3 - Absence and empty object stay compatible (Priority: P1)

**Goal**: Omitting `custom_data` keeps today’s behavior; `{}` is not persisted as a present empty object (AC-2, FR-005, FR-012)

**Independent Test**: Existing broadcast tests without `custom_data` stay green; POST with `custom_data: {}` returns `201` and metadata has no present empty `custom_data`. Internal reused `Idempotency-Key` with different `custom_data` still returns `409`.

### Tests for User Story 3

- [x] T018 [P] [US3] Public v2 omit + `{}` cases in `temba/api/v2/tests.py`
- [x] T019 [P] [US3] Internal Django omit + `{}` plus `Idempotency-Key` 409 when `custom_data` differs in `temba/api/v2/internals/broadcasts/tests.py`
- [x] T020 [P] [US3] FastAPI omit + `{}` in `temba/fastapi_app/tests.py` (do not invent FastAPI idempotency)

### Implementation for User Story 3

- [x] T021 [US3] Ensure `normalize_custom_data_in_msg` in `temba/msgs/custom_data.py` removes `custom_data` when `{}` before `Broadcast.create` in `temba/api/v2/serializers.py`

**Checkpoint**: All three user stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Changelog, gates, deploy notes

- [x] T022 Add `feat:` bullet for optional `msg.custom_data` in `WENI-CHANGELOG.md` under the shipping version; note Mailroom/Courier coordination and Delivery Sequence (Flows step 3)
- [x] T023 [P] Run `./code_check.py` and fix Black/isort/flake8 issues in `temba/msgs/custom_data.py`, `temba/msgs/tests_custom_data.py`, `temba/api/v2/serializers.py`
- [x] T024 Run `poetry run coverage run manage.py test temba.api.v2 temba.api.v2.internals.broadcasts temba.fastapi_app temba.msgs` per [quickstart.md](./quickstart.md)
- [x] T025 Confirm `git diff` still excludes `temba/mailroom/queue.py` and that no `# pragma: no cover` was added

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational
- **User Story 2 (Phase 4)**: Depends on Foundational; same serializer as US1 — sequential after US1 if one implementer
- **User Story 3 (Phase 5)**: Depends on Foundational; sequential after US1 if one implementer
- **Polish (Phase 6)**: After desired stories complete

### User Story Dependencies

- **User Story 1 (P1)**: After Phase 2
- **User Story 2 (P1)**: After Phase 2; shares `validate_msg` with US1 (file conflict if parallel)
- **User Story 3 (P1)**: After Phase 2; shares `custom_data.py` / serializer with US1/US2

### Within Each User Story

- Tests MUST be written and FAIL before treating implementation as done
- Helpers (Phase 2) before HTTP tests
- Story complete before polish

### Parallel Opportunities

- T007, T008, T009 can be drafted in parallel (three test files)
- T013, T014, T015 in parallel
- T018, T019, T020 in parallel
- Do not parallelize T006 / T011 / T017 / T021 (same serializer file)

---

## Parallel Example: User Story 1

```bash
# After Phase 2, draft HTTP tests in three files:
Task: "Public v2 success tests in temba/api/v2/tests.py"
Task: "Internal Django success tests in temba/api/v2/internals/broadcasts/tests.py"
Task: "FastAPI success tests in temba/fastapi_app/tests.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup
2. Phase 2 Foundational (helpers + `validate_msg` hook)
3. Phase 3 US1 (persist + three entry points + queued task)
4. **STOP and VALIDATE** US1 independently

### Incremental Delivery

1. Setup + Foundational
2. US1 persist path → demo
3. US2 400 contract strings
4. US3 omit/`{}` + internal 409
5. Polish changelog and CI gates

### Parallel Team Strategy

One implementer recommended: serializer and helper files collide. If two people: one owns `temba/msgs/custom_data.py` + unit tests; the other drafts HTTP tests in the three test files only.

---

## Notes

- Error strings MUST match OpenAPI examples in `contracts/whatsapp-broadcast-custom-data.md`
- FastAPI has no `Idempotency-Key`; do not add it
- Do not evaluate expressions in `custom_data`
- Do not filter by WWC channel type
- Suggested MVP: Phase 1–3 (US1)
