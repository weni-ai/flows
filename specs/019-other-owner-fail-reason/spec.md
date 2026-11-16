# Engineering Specification: Other-owner failure reason

**Repository**: weni-ai/flows — backend

**Feature Branch**: `019-other-owner-fail-reason`

**Created**: 2026-11-13

**Status**: Draft

**Suggested cycle**: SDD Full. The change adds a stored failure reason, a migration that widens the allowed reason, operator-facing copy, and a Courier rollout dependency. It touches message storage and contact history.

**Input**: User description: "Sem Product Spec. Fatia complementar ao Courier spec 008-fail-wac-not-owner. Este repositório aceita `failed_reason` H e mostra ao operador o texto “Outro atendimento está com a conversa”. Não redefinir o envio à Meta."

## Origin Without Product Spec

- Product Spec: none
- Problem: Courier can already record a terminal WhatsApp Cloud send failure when another app owns the thread, but this product has no name for that reason and the operator only sees a generic failure. The stored code Courier writes must be a valid reason here, the contact history must say why the send stopped, and Resend must leave that message off the request to Mailroom.
- Acceptance criteria:
  - AC-F1: The outgoing-message failure reasons include the code `H`, described in Portuguese as “Outro atendimento está com a conversa”, with an English source string and Spanish and Romanian translations.
  - AC-F2: An outgoing message with status failed and reason `H` shows that sentence in the contact history, on the failed-messages list, and on the message log. The operator can tell it apart from a generic failure and from “Error Limit”.
  - AC-F3: The existing reasons suspended, looping, error limit, too old, and no destination keep their current codes, labels, and the way they appear today.
  - AC-F4: The public message API and the message spreadsheet continue to expose send status only. They gain no reason field. The contact-history payload gains the new sentence for reason `H` and remains readable by existing clients.
  - AC-F5: The reason column stays optional. Existing rows, including empty reasons and the current codes, stay valid. No database rule is added that would reject `H` or any value Courier already writes.
  - AC-F6: Resend asks Mailroom only for selected messages whose reason is not `H`. An empty reason still goes. A selection that is only `H` does not call Mailroom. Each omitted message stays failed with reason `H`.
  - AC-M: This repository does not change Mailroom. Automatic retry selection already ignores a terminal failure. No Mailroom feature is added. See Other repositories.

## Courier contract

Courier spec 008-fail-wac-not-owner (weni-ai/courier) owns the send decision. This repository does not redefine it.

When Courier blocks a WhatsApp Cloud service message because another app owns the thread, or when the provider returns error code 131070 under that block, Courier writes:

- message status = failed (`F`)
- failure reason = `H`

Courier stores the letter only. It does not store or render the sentence. Templates of type marketing, utility, and authentication, and direct sends, still go out. With the Courier flag off, a 131070 stays an errored message (`E`), which Mailroom may retry. Those rules stay in Courier.

**Letter check in this repository.** The failure-reason codes stored today are `S` (suspended), `L` (looping), `E` (error limit), `O` (too old), and `D` (no destination). `C` is not used. `H` is not used on the failure reason. The status value `H` means handled, on a different field, so it does not occupy the reason code. Courier keeps the constant `H`. This repository does not ask Courier to switch letters.

## Scope in This Repository

**This repository implements**:

- Registering reason `H` on the outgoing message, with the operator sentence and the translations AC-F1 names.
- Showing that sentence in the contact history, on the failed outgoing messages list, and on the message log when the message is failed with reason `H`.
- Keeping every other failure reason and the public message API and spreadsheet behavior as they are today.
- A migration that only records the new allowed reason. The column stays optional. No database check is added.
- On Resend, sending to Mailroom only the selected messages whose reason is not `H`.
- Regression coverage and a changelog bullet for the new operator sentence and for Resend leaving reason `H` in place.

**Out of scope here**:

- Deciding whether a WhatsApp Cloud message is sent. Redis thread ownership, the Courier flag, Graph error 131070, templates, and direct sends stay in Courier.
- A Flows flag for the block.
- Calling the Thread Control API.
- Inbound standby, handover, and the WhatsApp Cloud dedicated channel.
- Changing Mailroom.
- Adding a failure-reason field to the public message API or to the message spreadsheet.
- Reading who owns the thread at Resend time. Flows does not ask Courier or Redis. A message already stored with reason `H` stays off the Mailroom request even if the other app has since given the thread back. A new send, started by another path, is still Courier’s decision.

## Current State

Inspected in this repository. These are findings, not assumptions.

**Stored reason**

- `Msg.failed_reason` already exists in production migrations. It is a single character, optional, added in `0160` and last widened in `0162` to suspended, looping, error limit, too old, and no destination.
- The model choices are the same five codes. Django applies those choices when a form or `full_clean` runs. A direct database update does not consult them.
- The only database check on the message table is `no_sent_status_without_sent_on`. Nothing in migrations or SQL constrains `failed_reason`. PostgreSQL already accepts `H`, any other single character, and an empty reason.
- No application path found calls `full_clean` on a message. The only writer of the reason in this repository is the job that fails queued, pending, or errored messages older than a week, and it sets “too old”. Releasing a channel marks queued, pending, and errored messages failed and leaves the reason untouched.

**What the operator sees**

- Contact history builds an event from the message (`Event.from_msg`). The event carries the status letter and the message text. It does not carry the failure reason. The page shows the text and, for status errored or failed, a warning icon. It never prints “Error Limit” or any other reason sentence.
- The failed outgoing messages list shows contact, text, time, and a log link. It has no reason sentence. The bulk action Resend is offered unless the workspace is suspended.
- The message log status line shows “Error” when the log is an error, otherwise the message status word (“Failed”). It does not read the failure reason.
- The public message read API and the internal message read API expose status `failed`. They have no failure-reason field.
- The spreadsheet export writes the status word (`failed` for a terminal failure) and has no reason column. Archived message JSON used by that export also omits the reason.
- Existing reason labels are fixed English words. They are not translation entries. New operator copy in this product is translated from an English source into Spanish, Portuguese (`pt_BR`), and Romanian.

**Retry**

- The index used to find messages to retry (`msgs_next_attempt_out_errored`) includes only outgoing messages in status errored with a scheduled next attempt. A terminal failure is outside that index.
- The week-old failure job and the channel-release failure job select queued, pending, and errored messages. They do not select a message that is already failed, and they do not put a failed message back into the errored state.
- Dewiring moves a wired message to errored. It does not touch a terminal failure.
- No Mailroom client payload in this repository reads `failed_reason`. `msg/resend` sends the workspace id and the message ids only.
- The worker that actually claims errored messages and sends them is not in this repository.

## Other repositories

**Flows (this repository).** Owns the reason choice, the operator sentence, the contact history, the failed-messages list, the message log, the message table, and the Resend filter that keeps reason `H` out of `msg/resend`. This spec is that slice.

**Courier.** Already writes status `F` and reason `H` when its flag is on. It keeps the letter `H`. It does not render the sentence. No Courier change comes from this spec.

**Mailroom.** No code change and no release. Confirmed in the Mailroom source: `failed_reason` is a free string, and `H` is not one of its named reasons (`S`, `L`, `E`, `O`, `D`, `T`, `M`). Courier writes `F` + `H` on the message row. The retry index and the failure jobs in this repository already treat status failed as terminal, and Mailroom’s claim loop selects errored messages. Mailroom’s resend path would clear `failed_reason`, so this repository drops reason `H` before `msg/resend`. The payload stays the workspace id plus the remaining message ids. When every selected id is `H`, Mailroom is not called.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The operator sees who has the conversation (Priority: P1)

An operator opens a contact after a WhatsApp Cloud service message was not sent because another app owns the thread. The history shows the message as failed and the sentence “Outro atendimento está com a conversa” (in the operator’s language). The message text stays visible.

**Why this priority**: Without this sentence, the operator cannot tell a thread owned elsewhere from a send that hit an error limit or an unnamed failure.

**Independent Test**: Open the contact history for an outgoing message stored as failed with reason `H`. The ownership sentence is on that row, in Portuguese under the Portuguese locale and in the English source under the default locale.

**Acceptance Scenarios**:

1. **Given** an outgoing message stored as failed with reason `H`, **When** the operator opens that contact’s history, **Then** the row shows the message text, the failed warning, and the ownership sentence.
2. **Given** the same history is returned as data to the page, **When** the event for that message is read, **Then** the event includes the same sentence and the existing status and text fields.
3. **Given** the workspace language is Portuguese, **When** the operator views that row, **Then** the sentence is exactly “Outro atendimento está com a conversa”.

---

### User Story 2 - The failed list and the message log use the same sentence (Priority: P1)

An operator looking at failed outgoing messages, or opening the log linked from one of them, sees the same ownership sentence on a message failed with reason `H`. A log that today shows only the word “Error” still shows the sentence.

**Why this priority**: The failed list is where operators review sends that stopped, and the log is the detail they open from that list. History alone would leave those screens generic.

**Independent Test**: Open the failed outgoing messages screen and the message log for a message failed with reason `H`. Both show the ownership sentence.

**Acceptance Scenarios**:

1. **Given** a failed outgoing message with reason `H` on the failed-messages list, **When** the operator views that list, **Then** the row shows the ownership sentence together with the message text.
2. **Given** that message has a channel log, **When** the operator opens the log, **Then** the status area shows the ownership sentence, including when the log itself is marked as an error.
3. **Given** a failed message with any other reason, or with no reason, **When** the operator views the list or the log, **Then** those screens stay as they are today.

---

### User Story 3 - Existing failures and automatic retry stay as they are (Priority: P1)

Messages that already failed for suspension, looping, error limit, age, or a missing destination keep their codes and their current presentation. A message that is only errored, including a 131070 recorded while the Courier flag is off, is still eligible for the existing retry path. A message already failed, with or without reason `H`, is not moved back into that path by any job in this repository.

**Why this priority**: A new reason must not relabel older failures or turn a terminal failure into another send attempt.

**Independent Test**: Store one message for each existing reason and one errored message. Confirm the existing labels and codes, confirm the history and failed list do not gain the ownership sentence for those reasons, and confirm the jobs that fail old or channel messages still ignore messages that are already failed.

**Acceptance Scenarios**:

1. **Given** a message failed with reason suspended, looping, error limit, too old, or no destination, **When** it is shown in history or on the failed list, **Then** it does not show the ownership sentence and its stored code is unchanged.
2. **Given** an errored outgoing message with a next attempt, **When** retry eligibility is evaluated the way this repository indexes it, **Then** that message remains in the errored retry set.
3. **Given** a message failed with reason `H` and an empty next attempt, **When** the week-old failure job and the channel-release failure job run, **Then** they leave that message failed with reason `H`.

---

### User Story 4 - Existing message feeds keep their shape (Priority: P2)

Consumers of the public message API and of the message spreadsheet keep receiving the status word for a failed send. They are not required to understand a new field.

**Why this priority**: The operator sentence belongs on the screens that already explain a single message. Widening the public contract is a separate change.

**Independent Test**: Read one failed message with reason `H` through the public message API and export a failed set that contains it. The status is still the existing failed word, and the payload and spreadsheet columns are unchanged.

**Acceptance Scenarios**:

1. **Given** an outgoing message failed with reason `H`, **When** a client reads it from the public message API, **Then** the status is the existing failed value and the body has the same fields as before.
2. **Given** a message export that includes that message, **When** the spreadsheet is written, **Then** the status column still shows the existing failed word and the columns are unchanged.

---

### User Story 5 - Resend leaves an owned conversation alone (Priority: P1)

An operator selects failed outgoing messages and chooses Resend. Messages failed because another service has the conversation stay on the list, still failed, with the same sentence. Mailroom is asked to resend only the other selected messages. A message with no stored reason still resends, as it does today.

**Why this priority**: Resend is the operator path that can hand a terminal failure back to Mailroom. Leaving reason `H` out of that request keeps the blocked send from being tried again from this screen.

**Independent Test**: From the failed-messages list, resend a message with reason `H`, a message with another reason, a message with an empty reason, and a mixed selection. Mailroom receives only the ids whose reason is not `H`. The `H` messages stay failed with reason `H`.

**Acceptance Scenarios**:

1. **Given** the operator selects only messages failed with reason `H`, **When** they choose Resend, **Then** Mailroom is not called and each message stays failed with reason `H`.
2. **Given** the selection mixes reason `H` with other failures, **When** they choose Resend, **Then** Mailroom receives only the ids whose reason is not `H`, and each `H` message stays failed with reason `H`.
3. **Given** a failed message with an empty reason, or with suspended, looping, error limit, too old, or no destination, **When** the operator resends it, **Then** Mailroom receives that id, as it does today.

---

### Edge Cases

- A failed message with an empty reason still appears as a generic failure. It does not show the ownership sentence.
- A failed message with a reason this product already knows (suspended, looping, error limit, too old, no destination) does not show the ownership sentence.
- An errored message, including one Courier left errored because the ownership flag was off, does not show the ownership sentence and is not rewritten to failed by this change.
- A handled message, whose status letter is also `H`, is unrelated. Its status stays handled, and it does not gain a failure reason.
- The ownership sentence appears in addition to the message text. The text is not replaced.
- A failed message with reason `H` and no channel log still shows the sentence in the contact history and on the failed list. The log screen applies only when a log exists.
- Portuguese, Spanish, and Romanian operators see the translated sentence. Any other locale falls back to the English source.
- Rows written before this change, and rows whose reason is empty, remain valid after the migration.
- An empty failure reason is not `H`. Resend still includes that message.
- A selection that becomes empty after reason `H` is removed does not call Mailroom.
- Resend does not clear reason `H`, does not change the status, and does not ask who owns the thread now. The same row stays ineligible for Resend after the other app gives the conversation back. A new message, started from another action, is outside this filter.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The product MUST recognize failure reason `H` on an outgoing message and MUST describe it with the English source “Another service has the conversation”.
- **FR-002**: Under Portuguese, that description MUST be exactly “Outro atendimento está com a conversa”. Spanish MUST be “Otro servicio tiene la conversación”. Romanian MUST be “Alt serviciu are conversația”.
- **FR-003**: Contact history MUST show that sentence on an outgoing message that is failed with reason `H`, on the screen and in the history event data, together with the message text and the existing failed warning.
- **FR-004**: The failed outgoing messages list MUST show that sentence on a row whose message is failed with reason `H`.
- **FR-005**: The message log MUST show that sentence in the status area when the logged message is failed with reason `H`, including when the log is marked as an error.
- **FR-006**: Messages failed for suspended, looping, error limit, too old, or no destination MUST keep those codes and labels, and MUST keep the presentation they have today on history, the failed list, and the message log.
- **FR-007**: The public message API MUST keep its current fields for a failed message. The message spreadsheet MUST keep its current columns and MUST keep writing the existing status word for a failed send.
- **FR-008**: The failure-reason column MUST stay optional. The migration MUST leave empty reasons and the existing reason codes valid. It MUST NOT add a database rule that rejects `H` or any single character the column can already store.
- **FR-009**: Jobs in this repository that fail old messages or fail a channel’s queued messages MUST leave a message that is already failed, including reason `H`, unchanged. Errored messages MUST remain the ones eligible for the existing retry index.
- **FR-010**: This repository MUST NOT add a switch for the ownership block, MUST NOT call the Thread Control API, and MUST NOT decide which WhatsApp Cloud messages Courier sends.
- **FR-011**: Version notes under heading `3.113.0` MUST record the new operator sentence and that Resend leaves a message failed with reason `H` in place.
- **FR-012**: Resend MUST ask Mailroom only for selected messages whose failure reason is not `H`. A message with an empty reason MUST still be included. When every selected message has reason `H`, Mailroom MUST NOT be called. Each omitted message MUST stay failed with reason `H`.

### Key Entities

- **Outgoing message**: A message this product tried to send. It has a status and, when the send has been given up, an optional one-letter failure reason.
- **Failure reason**: Why a terminal failure was recorded. Reason `H` means another service has the conversation. The other reasons stay the five already stored.
- **Contact history**: The timeline an operator opens for one contact, including the event data behind that page.
- **Failed outgoing messages**: The list of visible outgoing messages whose send was given up.
- **Message log**: The channel log detail linked from a message, when a log exists.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the contact-history checks, 100% of outgoing messages failed with reason `H` show the ownership sentence, and 0% of them show “Error Limit” as the explanation.
- **SC-002**: On the failed-messages list and the message log, 100% of messages failed with reason `H` show that same sentence.
- **SC-003**: 100% of messages with the five existing failure reasons keep their current codes and do not show the ownership sentence.
- **SC-004**: Public message reads and spreadsheet exports of a message failed with reason `H` keep the current status word and the current fields or columns, with zero new required fields.
- **SC-005**: A message with an empty reason, a message with each existing reason, and a message with reason `H` are all valid records, and the reason remains optional.
- **SC-006**: 100% of messages already failed with reason `H` stay failed with reason `H`, and 100% of errored messages that were waiting to be tried again stay waiting.
- **SC-007**: In Resend checks, 100% of selected messages with reason `H` stay out of the Mailroom request and stay failed with reason `H`. 100% of selected messages with an empty reason or another reason are included. A selection that is only reason `H` produces zero Mailroom calls.

## Assumptions

- Courier is the only writer of reason `H`. This repository displays and accepts that code. It does not try to detect thread ownership itself.
- The English source “Another service has the conversation” is the translation source for the Portuguese sentence the request fixed. “Atendimento” in that sentence means the other WhatsApp conversation owner, not an error quota.
- Spanish and Romanian copy above is the faithful translation of that same sentence. The constitution’s required locales are English (source), Spanish, Portuguese (`pt_BR`), and Romanian. Other catalogs fall back to English.
- The public message API and the spreadsheet do not expose a failure reason today, so AC-F4 is met by leaving them unchanged rather than by adding a field.
- Contact history is rendered by this product and also returned as event data. Both carry the sentence so the screen and the page data agree.
- Resend eligibility is the stored reason, not the current thread owner. Flows does not read Redis or ask Courier at Resend time. After another app gives the conversation back, that same failed row stays off Resend. The operator reaches Courier again by starting a new send.
- **Peak load (Principle XII)**: unchanged. Declared peak is the current peak of contact-history and failed-message list views for the busiest workspace, not an average and not a new traffic class. The reason is already on the message row those screens load. The change adds no endpoint, no worker, and no extra request at that peak.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-F1 reason `H` and the four strings | Model test: `H` is one of the failure-reason choices and its display is the English source. Locale catalogs `locale/es`, `locale/pt_BR`, and `locale/ro` contain that msgid with the Spanish, Portuguese, and Romanian sentences in FR-002. A `translation.override("pt-br")` around the history render asserts the exact Portuguese sentence. |
| AC-F2 history, failed list, message log | `temba/mailroom/tests.py` `EventTest.test_from_msg`: an outgoing message failed with reason `H` includes the sentence on the event and still includes status, text, and the existing keys. `temba/contacts/tests.py`: the contact-history response for that message contains the sentence and the message text. `temba/msgs/tests.py` `test_failed`: the failed-list response contains the sentence for reason `H`. Channel-log read test: a log for that message contains the sentence when the log is marked as an error. |
| AC-F3 other reasons | The same history and failed-list renders for reasons `S`, `L`, `E`, `O`, and `D` do not contain the ownership sentence. Choice codes and the existing English labels for those five stay as they are. Existing `test_from_msg` cases for other statuses stay green. |
| AC-F4 API and export | Existing public message API assertions for a failed message stay on status `failed` with the current field set. Existing export header and status-column assertions stay green. No new serializer field and no new spreadsheet column. |
| AC-F5 optional column, no new check | Migration test or model save: a message with reason `H`, a message with each existing reason, and a message with an empty reason all persist. The new migration does not add a check constraint and does not set the column non-null. |
| AC-F6 Resend skips reason `H` | `temba/msgs/tests.py` `test_failed`: resend of a message failed with reason `H` does not call `msg_resend`. A mixed selection calls `msg_resend` with the other ids only. An empty reason and an existing reason still produce a call that includes those ids. A selection that is only `H` does not call Mailroom. After the action, each `H` message is still status failed with reason `H`. The existing resend of a failed message with no reason `H` stays green. |
| AC-M no Mailroom feature | Confirmed against the Mailroom source: no `H` reason constant, claim stays on status errored, and resend would clear the reason if called. `msg/resend` still sends the workspace id and message ids. No Mailroom release. `fail_old_messages` and `fail_channel_outgoing_messages` tests: a message already failed with reason `H` stays `F` + `H`. |
| Changelog | `feat:` bullet under heading `3.113.0` in `WENI-CHANGELOG.md`. `CHANGELOG.md` is not rewritten. |

**Flow coverage** (Principle XIV): one test loads contact history the way an operator does, with a stored outgoing message failed with reason `H`, and asserts the sentence in the response. One test loads the failed-messages list and one opens the message log for the same kind of message. One test posts Resend the way the operator does, including a selection that is only reason `H` and a mixed selection. Those are the complete operator paths. The event assertion covers the history payload. Isolated checks cover the other reason codes, the empty reason, the public API field set, and the failure jobs leaving `F` + `H` untouched.

**Failure paths**: an empty reason and each existing reason render without the new sentence and still resend. An errored message stays out of the ownership copy and inside the errored retry set. A Resend selection that is only reason `H` does not call Mailroom. There is no new error response.

**Gates**: `poetry run coverage run manage.py test` for the touched modules (`temba.msgs`, `temba.contacts`, `temba.mailroom`), clean `./code_check.py`, green `.github/workflows/ci.yml`. No new `# pragma: no cover`.

## Rollout and Rollback

1. Deploy this repository so reason `H` is a known label and the screens show the sentence. The database already accepts the letter; this deploy is what makes the sentence available. Ship it before, or together with, the Courier release that writes `H`, which matches the Courier rollout order.
2. Deploy Courier with the ownership flag off. Sends stay as they are today. A 131070 stays errored.
3. Enable the Courier flag in staging, then in production. Service messages blocked for ownership, and 131070 under that flag, show the sentence here. Templates and direct sends still go out, by Courier’s rule.
4. **Rollback:** revert this repository’s choice, copy, and screens. Rows already stored with `H` remain readable as an unknown reason until the choice returns, because the column stays an optional single character and no check is added. Courier rollback is Courier’s own flag.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | Delivered through a PR to `main` with review and green `ci.yml`. | none |
| II. Security and Secrets | No new secret, dependency, or credential. The sentence is a fixed label. | none |
| III. Observability | No new log line and no personal data in a new event. Existing page and job logs stay the trace. | none |
| IV. Versioned Contracts | Public message API and spreadsheet stay as they are. History event data gains an optional sentence for reason `H`; existing keys stay. The migration stays backward compatible inside the release: the column remains optional and no check is added. Courier and Mailroom versions: Courier spec 008 writes `F` + `H`; Mailroom needs no release for this slice. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`. Each acceptance criterion maps to a check in Test Strategy. | none |
| VI. No Silent Divergence | Not applicable: no Product Spec. | none |
| VII. Commit Messages | Atomic Conventional Commits, imperative descriptions of 50 characters or fewer. | none |
| VIII. Changelog Maintenance | `feat:` bullet in `WENI-CHANGELOG.md` under heading `3.113.0`. `CHANGELOG.md` is not rewritten. | none |
| IX. Never Trust the Client | The reason is stored by Courier and displayed from the database. The screens do not accept a reason string from the browser. | none |
| X. Fail Gracefully | No new outbound call. Existing Mailroom resend timeouts stay as they are. | none |
| XI. Bounded Retry Over REST | No new REST propagation. Automatic retry eligibility stays on errored messages only. | none |
| XII. Scalability and Peak Load | Stateless render of a column already on the message row. Declared peak is the current peak of contact-history and failed-list views for the busiest workspace. No new endpoint, worker, or stored state. | none |
| XIII. Diagnosable Errors | No new Sentry event. | Platform `send_default_pii=True` remains `TODO(SENTRY_PII)`. |
| XIV. Tests Exercise Flows | Contact-history, failed-list, and message-log responses assert the sentence for a stored `F` + `H` message. The failed-list Resend post asserts that reason `H` stays out of `msg/resend`. `TembaTest`. | none |
| XV. Explicit Over Clever | Reason `H` is a named constant next to the existing reason constants. The sentence is the choice label, translated, not a one-off string in the template. | none |
| XVI. Contained Changes | Reason choice, the three operator surfaces, the Resend filter, their tests, locales for the new sentence, the migration, and the changelog bullet. The public API, the spreadsheet, Courier, and Mailroom stay as they are. | none |
| XVII. Explicit, Scoped Authorization | No new endpoint. Contact history, the failed list, and the message log keep their current page authorization. | none |
| Backend Standards | `code_check.py`. New copy in English, Spanish, Portuguese, and Romanian. | none |

## Implementation Decisions

- SDD Full: migration, operator copy, and a Courier deploy dependency.
- Keep Courier’s letter `H`. `C` is unused and is not adopted.
- Show the sentence only when the stored reason is `H`. Do not start showing the five older reason labels; they are not shown today.
- Put the sentence on the history event as an added display value. Leave the existing status and message fields intact.
- Leave the public message API and the spreadsheet without a reason field.
- Do not add a database check. The column is already an optional single character, and a check would be the first thing that could make Courier’s update fail.
- Filter Resend in `Msg.apply_action_resend` before `msg/resend`. Keep a message when its reason is not `H`, including an empty reason. Drop reason `H`. Call Mailroom only when at least one id remains. An empty reason must use a comparison that treats “no reason” as different from `H`. A SQL `exclude` on the letter alone drops empty reasons, because an empty value does not satisfy inequality.
- Do not look up the current thread owner during Resend.

## Ponta a ponta

Courier writes status failed and reason `H`. This repository shows “Outro atendimento está com a conversa” in the contact history, on the failed list, and on the message log. Automatic retry does not pick up that message: the retry index and the failure jobs ignore status failed.

Resend on the failed list no longer forwards reason `H`. A mixed selection sends the other ids only. A selection that is only `H` does not call Mailroom. The message stays failed with that reason. The filter does not ask who owns the thread now, so the same row stays off Resend after the other app gives the conversation back. A new send, started from another action, still goes to Courier, which decides again.

Two accepted gaps remain visible end to end. The public message API and the spreadsheet still say only that the send failed. An operator or integration that looks only there does not see the ownership sentence. Courier still does not render the sentence; only the screens in this spec do.
