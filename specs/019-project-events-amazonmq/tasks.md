# Tasks: Consume project events from AmazonMQ

**Input**: Design documents from `/specs/019-project-events-amazonmq/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/project-events.md](./contracts/project-events.md), [quickstart.md](./quickstart.md)

**Tests**: Required. The spec's Test Strategy and Constitution Principle XIV demand flow tests (`TembaTest`) for success and failure paths. Tests sit with the code they cover, and write them before the implementation they exercise.

**Organization**: Grouped by user story. US1 and US2 are P1, US3 is P2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1, US2, US3
- Test command: `poetry run coverage run manage.py test temba.projects`. Gate: `./code_check.py`.

## Phase 1: Setup

- [X] T001 Create the branch `feat/project-events-amazonmq` from `main` (Principle I; commits follow Conventional Commits, one logical change each)

---

## Phase 2: Foundational (blocks all user stories)

**Purpose**: Shared types, setting, check, logging and the test helper that every story uses.

- [X] T002 [P] Add `PROJECT_EVENTS_LEGACY_ACTIONS` to `temba/settings_common.py`, outside `if USE_EDA:`: split on `,`, strip, drop empty items, default `updated,status_updated,project_type_update,deleted`, unset gives four actions and `""` gives `[]` (research R3)
- [X] T003 [P] Add a `temba.projects` logger at `INFO` with the `console` handler and `propagate: False` to `LOGGING` in `temba/settings_common.py` and `temba/settings.py.prod` (research R8)
- [X] T004 [P] Create `temba/projects/consumers/project_events.py`: move `EventAction` and `ProjectStatus` here from `project_event_consumer.py` (and import them back there), and add `is_legacy_action`, `ProjectEventContext` (with `user_id`), `ProjectEventRejected`, `find_org_id`, `find_user_id` (read-only, `None` for a non-string or unknown e-mail), `canonical_uuid`, `scrub_sentry_event` and `report_exception` (tags include `user_id`) per data-model.md and research R2, R6, R9
- [X] T005 [P] Create `temba/projects/consumers/project_event_payloads.py`: `InvalidProjectEvent(ValueError)`, `ENVELOPE_TOKEN_PATTERN`, `ProjectEventEnvelope.from_event` for `event_id`, `event_type` and `producer`, and the four frozen dataclasses with strict `from_data` validators per research R1 (messages name field and rule, never the value) (FR-012)
- [X] T006 [P] Create `temba/projects/checks.py` registering system check `projects.E001` for items outside `EventAction` (imported from `project_events.py`), and import it from `temba/projects/__init__.py` as `temba/assets/__init__.py` does
- [X] T007 [P] Add tests in `temba/projects/consumers/tests/test_project_event_payloads.py` for the envelope (UUID and `weni-engine` accepted; space, line break, non-string, over 64 characters and `producer` object rejected; `producer` `null` accepted) and every payload rule in R1, with no value in messages; and in `temba/projects/consumers/tests/test_project_events.py` for `is_legacy_action` with `override_settings`, `scrub_sentry_event` (drops frame `vars`, redacts e-mails), `find_org_id` (unknown and `None` give `None`), `find_user_id` (existing user gives its id, unknown e-mail and non-string give `None`, no `User` created), `canonical_uuid`, and `report_exception` tags
- [X] T008 [P] Add tests in `temba/projects/tests.py` for the check: `["deleted", "bogus"]` gives `projects.E001`, default and `[]` give none, default equals `[a.value for a in EventAction]`
- [X] T009 Add a `handle()` test helper (patching `message_started` and `message_finished` in `weni.eda.django.consumers.consumer`, research R10) in `temba/projects/consumers/tests/helpers.py` and use it from the consumer test modules

**Checkpoint**: `manage.py test temba.projects` passes and `PROJECT_EVENTS_LEGACY_ACTIONS="deleted,bogus" manage.py check` fails with `projects.E001`.

---

## Phase 3: User Story 1 - Project changes reach Flows through AmazonMQ (P1) MVP

**Goal**: With the legacy list empty, the four AmazonMQ events produce the same org state as the legacy messages.

**Independent Test**: `override_settings(PROJECT_EVENTS_LEGACY_ACTIONS=[])`, send each event through `handle()`, check org fields, `modified_by` and `basic_ack` (AC-1, SC-001).

- [X] T010 [US1] Write flow tests in `temba/projects/consumers/tests/test_project_consumer.py`: one per event (`project.updated` incl. `null` fields unchanged, `project.status.updated` with `INACTIVE` and `ACTIVE`/`IN_TEST`, `project.type.updated`, `project.deleted`), plus an unknown `event_type` acked and the existing `project.created` tests still green (AC-7)
- [X] T011 [US1] Rewrite `temba/projects/consumers/project_consumer.py`: add the four `ProjectEventType` constants and `LEGACY_ACTION_BY_EVENT_TYPE`; thin `consume` (context, `_process`, `report_exception`, `raise ProjectEventRejected ... from None`); `ProjectEventEnvelope.from_event` right after `message.event()` for every event type, before anything is logged; `_handle_project_change` building the payload and calling `update_project_config`, `update_project_status`, `update_project_type` or `delete_project`; log `project_event_consumed`; keep `project.created` and unknown-type paths otherwise unchanged; remove `# pragma: no cover` from `consume` (FR-001, FR-010, FR-012, RG-1)

**Checkpoint**: US1 tests pass with the list empty.

---

## Phase 4: User Story 2 - Exactly one consumer applies each action (P1)

**Goal**: For every value of the list, each change is applied by one consumer; the other acks its copy.

**Independent Test**: For the default and `[]`, with each of the four actions, and for `["project_type_update"]`, deliver the legacy message and the AmazonMQ event for the same change and assert which use case ran (AC-2, SC-002).

- [X] T012 [US2] Write tests in `test_project_consumer.py` and `test_project_event_consumer.py`, parameterized over the four actions so each action is exercised both listed and not listed: default list (legacy applies, `ProjectConsumer` acks and logs `project_event_skipped reason=legacy_consumer_applies`), `[]` (`ProjectConsumer` applies, legacy message acked and logged as skipped with `reason=amazonmq_consumer_applies`); plus `["project_type_update"]` as the mixed case (deletion applied by `ProjectConsumer`, type change by the legacy consumer); assert the use case is not called for skipped copies
- [X] T013 [US2] Add the skip step to `ProjectConsumer._handle_project_change` after validation and before the org lookup, logging `project_event_skipped` (FR-004, FR-006)
- [X] T014 [US2] Update `temba/projects/consumers/project_event_consumer.py`: import enums from `project_events.py`; thin `consume` and `_process`; store `canonical_uuid(project_uuid)` in the context; skip with ack when `not is_legacy_action(action)`; set `context.user_id = find_user_id(user_email)` before applying; rename `_process_event` to `_apply_event`; resolve `org_id` in the `except` path before `report_exception`; remove `# pragma: no cover` from `consume`; behaviour for listed actions unchanged (FR-005, FR-006, FR-012, RG-1)
- [X] T015 [US2] Update existing assertions in `test_project_event_consumer.py` that call `consume` so they run through the helper and still pass with the default list

**Checkpoint**: dual-delivery matrix passes for the three list values.

---

## Phase 5: User Story 3 - Invalid or repeated events never damage an org (P2)

**Goal**: Invalid events change nothing and are diagnosable; repeats are harmless; no e-mail in logs or Sentry.

**Independent Test**: Invalid events, a repeated deletion and a missing org (AC-3 to AC-6, SC-003, SC-004).

- [X] T016 [P] [US3] Write tests in `temba/projects/consumers/tests/test_project_consumer.py`: invalid UUID, missing `user_email`, missing and unknown `status`, `is_multi_agents` of `1` and `"true"`, unknown `timezone`, envelope with a missing key, `event_id` with a space or a line break, numeric `event_id`, object `producer` (also on a `project.created` envelope); each asserts `basic_reject(tag, requeue=False)`, one `capture_exception`, org unchanged, and for envelope cases no `project_event_consumed` line and no log record containing the rejected value; validation runs even when the action is in the legacy list; two `project.deleted` events leave `released_on` unchanged. In `test_project_event_consumer.py`, a legacy message whose `project_uuid` is not a UUID keeps today's outcome and no log line or tag carries that value (FR-012)
- [X] T017 [P] [US3] Write tests in `test_project_consumer.py` for a valid event of each type with an unknown `uuid`: acked and `project_event_org_not_found` warning with `project_uuid` and `event_id` (AC-5)
- [X] T018 [P] [US3] Rewrite `test_delete_already_deleted_project` and add a transaction test in `temba/projects/usecases/tests/test_project_delete.py`: second call leaves `released_on` and `modified_by` unchanged and creates no user; a channel release that raises leaves the org active and `released_on` `None`
- [X] T019 [P] [US3] Add `assertLogs` tests in `test_project_delete.py`, `test_project_status_update.py` and `test_project_type_update.py` asserting no record contains the e-mail or the org name (AC-6)
- [X] T020 [US3] Add the missing-org step to `ProjectConsumer._handle_project_change` (`find_org_id`, warning log, ack, set `context.org_id`), then set `context.user_id = find_user_id(payload.user_email)` right before the use case (FR-008, R6)
- [X] T021 [US3] Update `temba/projects/usecases/project_delete.py`: return the org with a `project_already_released` log when `not org.is_active`, before resolving the user; run `org.release(user)` inside `transaction.atomic()`; log without e-mail or name (FR-007, FR-009)
- [X] T022 [P] [US3] Rewrite the log lines in `temba/projects/usecases/project_status_update.py` and `temba/projects/usecases/project_type_update.py` as `key=value` lines with `project_uuid`, `org_id` and the new value, without e-mail or name (FR-009)
- [X] T023 [US3] Add tests, using `handle()` and a captured Sentry event, where the use case raises an exception whose message contains the e-mail and the org name: the Sentry event and the `weni-eda` rejection log contain neither, and no frame variables; the event carries the `user_id` tag when a `User` has the e-mail, and no `user_id` tag (and no `User` created) when none does (R6, R9, AC-6, SC-004)

**Checkpoint**: all failure-path tests pass.

---

## Phase 6: Polish and cross-cutting

- [ ] T024 [P] Add to `WENI-CHANGELOG.md`, under a new topmost heading for the next minor version, a `feat:` bullet for consuming the four events from AmazonMQ with `PROJECT_EVENTS_LEGACY_ACTIONS`, and a bullet deprecating `flows.project-events` (FR-011, RG-2)
- [X] T025 Run `poetry run coverage run manage.py test temba.projects` and the coverage report from [quickstart.md](./quickstart.md); confirm both `consume` methods are covered and `rg -n "def consume.*pragma: no cover"` on the two consumer files prints nothing (RG-1)
- [X] T026 [P] Run `./code_check.py` and fix Black, flake8 and isort findings
- [X] T027 [P] Run the start-up refusal checks in quickstart.md section 3 (`manage.py check` with an unknown, empty and valid value)
- [ ] T028 Hand off the staging validation in quickstart.md section 5 to the release owner, with the infrastructure prerequisites (four bindings and dead-letter exchange on `flows.projects.queue`); confirm the changelog version number when opening the PR

---

## Dependencies and order

- Phase 1, then Phase 2, then stories. Inside Phase 2: T004 before T006, T007 and T009 (T006 imports `EventAction` from `project_events.py`); T005 before T007; T002 before T006 and T008.
- **US1** needs Phase 2. **US2** needs US1's `_handle_project_change` (T011) for T013, but T014 is independent of it. **US3** needs T011; T020 and T021 can follow T013.
- Tests come before the code they exercise: T018 and T019 before T021 and T022; T016 and T017 before T020.
- `project_consumer.py` is edited by T011, T013 and T020, so those run in that order. `project_event_consumer.py` is edited only by T004 (import) and T014.
- Use-case files (T021, T022) are independent of the consumers.

```text
T001 -> T002, T003, T004, T005
T004 -> T006, T009          T004, T005 -> T007          T002 -> T006, T008
T009 -> T010 -> T011 -> T013 -> T020
T009 -> T012 -> T014 -> T015
T011 -> T016, T017 -> T020
T018, T019 -> T021, T022
T020, T021, T022 -> T023
all -> T024 -> T025, T026, T027 -> T028
```

## Parallel examples

- Phase 2: T002, T003, T004, T005 together; then T006, T007, T008 and T009 together.
- US3: T016, T017, T018, T019 (tests, separate files or sections) together, then T021 with T022.

## Implementation strategy

- **MVP**: Phase 1, Phase 2 and US1 (T001 to T011). It consumes the four events, but with the default list nothing changes in production until US2 exists, so ship US1 and US2 together.
- **Increment 2**: US2, which makes the transition safe. **Increment 3**: US3 and polish.
- Deploy order follows the spec's Rollout: infrastructure, then Flows with the default list, then the list is changed per environment. Rollback is restoring the default.
