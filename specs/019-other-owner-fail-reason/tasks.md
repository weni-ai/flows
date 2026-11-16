# Tasks: Other-owner failure reason

**Input**: Design documents from `specs/019-other-owner-fail-reason/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/other-owner-failure.md, quickstart.md

**Tests**: Included. The spec Test Strategy and Constitution Principle XIV require a flow test for each acceptance criterion.

**Organization**: Tasks follow the user stories in spec.md. P1 stories come before the P2 story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story label. Setup, Foundational, and Polish have none.

## Path Conventions

Paths are from the repository root, as listed in plan.md. Application code lives under `temba/`. Operator templates live under `templates/`.

## Phase 1: Setup

**Purpose**: Confirm the migration leaf before adding a choices-only migration

- [x] T001 Confirm `temba/msgs/migrations/0175_merge_20260910_2109.py` is still the leaf of `temba/msgs/migrations/` (it merges `0174_auto_20260910_2044` and `0174_managedtriggergroup`). Stop if a newer msgs migration exists and point the new migration at that leaf instead.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Register reason `H` and its translations. Every story reads this choice.

**⚠️ CRITICAL**: No user story work starts until this phase is complete.

- [x] T002 Add `FAILED_OTHER_OWNER = "H"` and include it in `FAILED_CHOICES` in `temba/msgs/models.py`. The label is the lazy English string `Another service has the conversation`. Leave the existing labels for `S`, `L`, `E`, `O`, and `D` as plain strings. Keep `failed_reason` nullable with `max_length=1`.
- [x] T003 [P] Depends on T002. Generate `temba/msgs/migrations/0176_alter_msg_failed_reason.py` with `AlterField` on `failed_reason` only. Depend on `msgs.0175_merge_20260910_2109` (or the leaf found in T001). Keep `null=True` and `max_length=1`. Do not add a `CheckConstraint` or any other operation. Do not start this until T002 has added the choice.
- [x] T004 [P] Depends on T002. Add msgid `Another service has the conversation` with msgstr `Otro servicio tiene la conversación` in `locale/es/LC_MESSAGES/django.po`. Do not start this until T002 has fixed the English source.
- [x] T005 [P] Depends on T002. Add msgid `Another service has the conversation` with msgstr `Outro atendimento está com a conversa` in `locale/pt_BR/LC_MESSAGES/django.po`. Do not start this until T002 has fixed the English source.
- [x] T006 [P] Depends on T002. Add msgid `Another service has the conversation` with msgstr `Alt serviciu are conversația` in `locale/ro/LC_MESSAGES/django.po`. Do not start this until T002 has fixed the English source.
- [x] T023 Depends on T003. In `temba/msgs/tests.py`, save outgoing messages with `failed_reason` `NULL`, `S`, `L`, `E`, `O`, `D`, and `H`, reload them, and assert each stored value. Load the new migration module and assert its only operation is `AlterField` on `failed_reason` with `null=True`, and that it contains no `CheckConstraint` and no `AddConstraint`. Finish T023 before any later task edits `temba/msgs/tests.py`.

**Checkpoint**: A message can be saved with reason `H`, empty reason, and each existing code. The migration leaves the column optional. Other catalogs fall back to English.

---

## Phase 3: User Story 1 - The operator sees who has the conversation (Priority: P1) 🎯 MVP

**Goal**: Contact history shows the ownership sentence for an outgoing message failed with reason `H`, in the page and in the event data.

**Independent Test**: Open contact history for a stored outgoing message with status failed and reason `H`. The row shows the message text and the sentence. Under `pt-br` the sentence is exactly `Outro atendimento está com a conversa`.

### Tests for User Story 1

- [x] T007 [P] [US1] Extend `EventTest.test_from_msg` in `temba/mailroom/tests.py` so an outgoing message with status `F` and reason `H` includes `failed_reason_display` plus the existing status, text, and keys. Existing equality cases for other statuses stay unchanged and do not require that key.
- [x] T008 [P] [US1] Extend `ContactTest.test_history` in `temba/contacts/tests.py` so the history response for a stored outgoing `F` + `H` message contains the English sentence and the message text. Under `translation.override("pt-br")` the response contains exactly `Outro atendimento está com a conversa`.

### Implementation for User Story 1

- [x] T009 [US1] In `temba/mailroom/events.py`, set `failed_reason_display` from `get_failed_reason_display()` on outbound `Event.from_msg` results (`msg_created`, `broadcast_created`, `product_sent`, `ivr_created`) only when `failed_reason` is `H`. Omit the key otherwise. Leave `msg_received` unchanged.
- [x] T010 [US1] In `templates/contacts/contact_history.haml`, render `event.failed_reason_display` on the broadcast row and on the `msg_created` / `ivr_created` / `product_sent` row when that value is present. Keep the message text.

**Checkpoint**: User Story 1 is testable on its own. History for other reasons still has no ownership sentence.

---

## Phase 4: User Story 2 - The failed list and the message log use the same sentence (Priority: P1)

**Goal**: The failed outgoing messages list and the message log show the same sentence for reason `H`. An error log does not stop at the word Error.

**Independent Test**: Open the failed-messages list and the channel log for a message failed with reason `H`. Both show the ownership sentence. The log case uses `is_error=True`.

### Tests for User Story 2

- [x] T011 [P] [US2] Extend `MsgCRUDLTest.test_failed` in `temba/msgs/tests.py` so the failed-list response contains the English ownership sentence for a message with reason `H`.
- [x] T012 [P] [US2] Add cases on `ChannelLogTest` in `temba/channels/tests.py`. A channel log with `is_error=True` whose message is failed with reason `H` renders `Another service has the conversation` in the status area. A channel log whose message is failed with reason `E` does not contain that sentence.

### Implementation for User Story 2

- [x] T013 [P] [US2] In `templates/msgs/message_box.haml`, show `object.get_failed_reason_display` on the message row only when `object.failed_reason` is `H`. This row is what `templates/msgs/msg_failed.haml` and `templates/msgs/message_box_spa.haml` already use.
- [x] T014 [P] [US2] In `templates/channels/channellog_read.haml`, show the ownership sentence in the status block when `object.msg` exists and `object.msg.failed_reason` is `H`, including when `object.is_error` is true. Leave the existing Error or status word in place beside that sentence.

**Checkpoint**: List and log show the sentence for reason `H` only.

---

## Phase 5: User Story 3 - Existing failures and automatic retry stay as they are (Priority: P1)

**Goal**: Reasons `S`, `L`, `E`, `O`, and `D` keep their codes and do not gain the new sentence. Jobs that fail old or channel messages leave an existing `F` + `H` row unchanged. Errored messages stay in the retry set.

**Independent Test**: Render one message for each existing reason and confirm the ownership sentence is absent. Run the week-old failure path and the channel-release path against an existing `F` + `H` message and confirm it stays `F` + `H`.

### Tests for User Story 3

- [x] T015 [P] [US3] In `temba/contacts/tests.py`, assert contact history for failed messages with reasons `S`, `L`, `E`, `O`, and `D` does not contain `Another service has the conversation`.
- [x] T016 [US3] In `temba/msgs/tests.py`, assert the failed list for those same five reasons does not contain the ownership sentence, and extend `MsgTasksTest.test_fail_channel_outgoing_messages_task` so a message already failed with reason `H` stays status `F` and reason `H` after `fail_channel_outgoing_messages`.
- [x] T017 [US3] Add a test in `temba/msgs/tests.py` that calls `Msg.fail_old_messages`. An outgoing message already `F` + `H` and older than a week stays `F` + `H`. A queued outgoing message older than a week still becomes `F` with reason `O`. Assert the model index named `msgs_next_attempt_out_errored` still filters outgoing messages with status `E` and `next_attempt` set, and does not include status `F`. An outgoing message with status `E`, a set `next_attempt`, and `created_on` inside the last week stays status `E` with that `next_attempt` after the call, so it remains eligible for that index. Remove `# pragma: needs cover` from `Msg.fail_old_messages` in `temba/msgs/models.py` because this test executes it. Leave the pragma on the Celery wrapper in `temba/msgs/tasks.py`.

**Checkpoint**: Older reasons and the errored retry index are unchanged. `msgs_next_attempt_out_errored` still requires status `E`.

---

## Phase 6: User Story 5 - Resend leaves an owned conversation alone (Priority: P1)

**Goal**: Resend asks Mailroom only for selected messages whose reason is not `H`. An empty reason still goes. A selection that is only `H` does not call Mailroom.

**Independent Test**: From the failed list, resend reason `H` alone, a mix, an empty reason, and an older reason. `msg_resend` receives only non-`H` ids. Each `H` message stays failed with reason `H`.

### Tests for User Story 5

- [x] T018 [US5] Extend `MsgCRUDLTest.test_failed` in `temba/msgs/tests.py`. Resend of only reason `H` does not call `MailroomClient.msg_resend`. A mixed selection calls it with the other ids only. An empty reason and reasons `S`, `L`, `E`, `O`, and `D` are included. After the action, each `H` message is still status `F` with reason `H`. The existing resend of a failed message without reason `H` stays green.

### Implementation for User Story 5

- [x] T019 [US5] In `Msg.apply_action_resend` in `temba/msgs/models.py`, keep messages whose `failed_reason` is `NULL` or any code other than `FAILED_OTHER_OWNER`. Drop reason `H`. Call `mailroom.get_client().msg_resend` only when at least one id remains, using that message's org id. Do not use `exclude(failed_reason="H")`, because SQL inequality drops `NULL`. Do not read Redis or change `temba/mailroom/client.py`.

**Checkpoint**: Resend no longer forwards reason `H`. The `msg/resend` payload is still `org_id` plus `msg_ids`.

---

## Phase 7: User Story 4 - Existing message feeds keep their shape (Priority: P2)

**Goal**: The public message API and the spreadsheet keep the status word `failed` and their current fields and columns.

**Independent Test**: Read and export a message failed with reason `H`. Status stays the existing failed value. No new field or column appears.

### Tests for User Story 4

- [x] T020 [US4] In `temba/api/v2/tests.py` `test_messages`, read one outgoing message stored as status `F` and reason `H` from `api.v2.messages`. The status value stays `failed`, and the JSON keys stay the current `MsgReadSerializer` fields, with no `failed_reason` key. In `temba/msgs/tests.py` `test_message_export`, export a set that includes that same kind of message. The status cell stays `failed`, and the header stays `Date`, `Contact UUID`, `Name`, `URN` or `ID`, `URN Type`, `Direction`, `Text`, `Attachments`, `Status`, `Channel`, `Labels`. Do not add `failed_reason` to `MsgReadSerializer` in `temba/api/v2/serializers.py` or to `ExportMessagesTask` / `Msg.as_archive_json` in `temba/msgs/models.py`. Existing failed-message assertions in both files stay green.

**Checkpoint**: Public reads and exports match the contract in `contracts/other-owner-failure.md`.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Release note and the quickstart gate

- [x] T021 [P] Add a `feat:` bullet in `WENI-CHANGELOG.md` for the operator sentence and for Resend leaving reason `H` on the list. Heading is `3.113.0`, the next minor after `3.112.1`. Do not edit `CHANGELOG.md`.
- [ ] T022 Run the commands in `specs/019-other-owner-fail-reason/quickstart.md`, including `./code_check.py`. No new `# pragma: no cover`. Not run: the project environment does not import Django (`requests` is missing from the Poetry env) and local Postgres rejects user `temba`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on T001. T002 blocks T003, T004, T005, and T006. Those four can then run together. T023 depends on T003 and blocks every later edit of `temba/msgs/tests.py`. Phase 2 blocks every user story.
- **User stories**: Depend on Phase 2. US2, US3, and US5 also touch screens or tests introduced by earlier stories, so the order below is the safe one.
- **Polish**: Depends on the stories you include. T022 runs last.

### User Story Dependencies

- **User Story 1 (P1)**: Starts after Phase 2. No dependency on other stories.
- **User Story 2 (P1)**: Starts after Phase 2. Independent of the history template. Do it after US1 so the sentence text is already fixed.
- **User Story 3 (P1)**: After US1 and US2, because the negative assertions read the history page and the failed list.
- **User Story 5 (P1)**: After Phase 2. It edits `temba/msgs/tests.py` `test_failed`, so run it after US2 and US3, which edit that file first.
- **User Story 4 (P2)**: After T023 and the model change. It adds an `F` + `H` read and export case and checks that API and export files stay otherwise untouched.

### Within Each User Story

- Write the story's tests first and confirm they fail before the implementation task in that story.
- US1: T007 and T008, then T009, then T010.
- US2: T011 and T012, then T013 and T014.
- US5: T018, then T019.

### Parallel Opportunities

- T003, T004, T005, and T006 are parallel with each other only after T002. They are not parallel with T002. T023 waits for T003.
- US1 tests T007 and T008 touch different files.
- US2 tests T011 and T012 touch different files. Implementations T013 and T014 touch different files.
- US3 task T015 touches `temba/contacts/tests.py` and can run beside T016 only after US2 has finished `temba/msgs/tests.py`. T016 and T017 both edit `temba/msgs/tests.py`, so they stay sequential.

---

## Parallel Example: Foundational

```bash
# T003–T006 start only after T002. They are parallel with each other, not with T002.
Task: "Generate temba/msgs/migrations/0176_alter_msg_failed_reason.py"
Task: "Add the Spanish msgstr in locale/es/LC_MESSAGES/django.po"
Task: "Add the Portuguese msgstr in locale/pt_BR/LC_MESSAGES/django.po"
Task: "Add the Romanian msgstr in locale/ro/LC_MESSAGES/django.po"

# After T003, before later edits to temba/msgs/tests.py:
Task: "Persist NULL, S, L, E, O, D, and H and assert the migration has no check"
```

## Parallel Example: User Story 2

```bash
# Tests together:
Task: "Extend MsgCRUDLTest.test_failed in temba/msgs/tests.py"
Task: "Add the ChannelLogTest case in temba/channels/tests.py"

# Then templates together:
Task: "Render reason H in templates/msgs/message_box.haml"
Task: "Render reason H in templates/channels/channellog_read.haml"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Finish Phase 1 and Phase 2.
2. Finish Phase 3 (contact history).
3. Stop and run `temba.mailroom.tests.EventTest.test_from_msg` and `temba.contacts.tests.ContactTest.test_history`.

History then shows the sentence. The failed list, the log, and Resend are not in this slice.

### Release slice

Ship Phases 1 through 6 and Phase 8 together. User Story 5 closes Resend. User Story 4 is the check that the public API and the spreadsheet were left alone. Do not release the choice without the Resend filter.

### Incremental delivery

1. Setup + Foundational, including T023 → reason `H`, the five older codes, and an empty reason are valid stored values, and the migration adds no check.
2. User Story 1 → history shows the sentence.
3. User Story 2 → failed list and message log show it.
4. User Story 3 → older reasons and failure jobs stay as they are.
5. User Story 5 → Resend skips `H`.
6. User Story 4 → API and export stay compatible.
7. Polish → changelog and `./code_check.py`.

---

## Notes

- Commit after each phase or after each story. Descriptions stay imperative and at or under 50 characters.
- Do not add a database check. Do not call Thread Control or read `wac:thread_owner`.
- Do not edit `temba/mailroom/client.py`. The Resend payload stays `org_id` and `msg_ids`.
- Empty `failed_reason` is not `H` and still resends.
- The unrelated empty file `temba/orgs/migrations/0094_ensure_org_marketing_table.py` is outside this feature. Do not revive it or give it a number in the msgs app.
- Changelog heading is `3.113.0`. The bullet is not appended to `3.112.1`.
- Mailroom needs no release. `failed_reason` there is a free string and has no `H` constant. Courier writes `F` + `H`. Flows drops `H` before `msg_resend`.
