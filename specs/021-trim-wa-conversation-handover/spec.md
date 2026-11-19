# Engineering Specification: Trim consumed and expired WhatsApp handover context

**Repository**: weni-ai/flows — backend

**Feature Branch**: `feat/trim-wa-conversation-handover`

**Created**: 2026-11-16

**Status**: Draft

**Input**: User description: "The `wa_conversation_handover` table has no cleanup routine. Mailroom fills `consumed_on`, but rows stay stored forever. Create a periodic routine that removes consumed or expired context, so handover and standby data are kept only temporarily. Follow the `trim_*` Celery pattern with `@nonoverlapping_task` and `CELERY_BEAT_SCHEDULE`. Delete rows already consumed or older than 24 hours. Check how `created_on` behaves when context is appended to an existing row, and pick the expiry reference so content just added to an old row is not deleted. Delete in batches. Do not let cleanup remove new context because it raced with a write or a consume. Validate consumed, expired, valid, and recently updated rows."

**Suggested cycle**: SDD Lite. One periodic task in the app that owns the table, one retention entry, one beat entry, tests, and a changelog bullet. No migration, no public interface, no Courier or Mailroom code change, no new channel type. If planning decides an index is needed (see Implementation Decisions), this ships a migration and SHOULD be promoted to SDD Full with `/speckit.plan`.

## Origin Without Product Spec

- Product Spec: none
- Problem: Rows in `wa_conversation_handover` are never deleted. Mailroom sets `consumed_on` when it attaches the context to an inbound, and pending rows that nobody consumes also stay, so WhatsApp handover summaries and standby transcripts, which contain conversation text, are kept forever.
- Acceptance criteria:
  - AC-1: A periodic task named in the `trim_*` pattern, wrapped by `@nonoverlapping_task` with the lock watchdog enabled, is registered in `CELERY_BEAT_SCHEDULE` and runs every 15 minutes.
  - AC-2: Each run deletes every row whose `consumed_on` is set, whatever its age.
  - AC-3: Each run deletes every unconsumed row whose last write is at least 24 hours old. The 24 hours come from a named entry in `RETENTION_PERIODS`.
  - AC-4: The expiry reference is the last write to the row (`created_on`, which Courier resets to the current time on every append), not `occurred_on`. An unconsumed row written less than 24 hours ago is kept, even when its `occurred_on` or its first content is older than 24 hours.
  - AC-5: Deletion runs in bounded batches (named batch size, 1000 rows) until no eligible row is left.
  - AC-6: A row is deleted only if it is still eligible when the delete runs. A row that was eligible when its batch was selected, but received new content before the delete, is kept with that content.
  - AC-7: Consumed rows that Mailroom just committed are deleted without affecting the new pending row for the same channel and contact. A pending row that Mailroom consumes while it is being deleted ends either deleted or consumed, and the inbound message is processed normally either way.
  - AC-8: Tests cover consumed (recent and old), expired, valid, recently updated rows, the 24-hour boundary, batching across more than one batch, and the race in AC-6. The repository's usual test, style, and CI gates stay green with no new coverage exclusion.
  - AC-9: Each run logs the number of rows actually deleted and the duration, with no contact URN or context text. `WENI-CHANGELOG.md` gains a `feat:` bullet under a new version heading at the top, following the team's release practice.

## Scope in This Repository

**This repository implements**:

- A `trim_*` Celery task in `temba/wa_conversation_handovers/tasks.py` (auto-discovered through `INSTALLED_APPS`).
- A `RETENTION_PERIODS` entry of 24 hours for this table, and a `CELERY_BEAT_SCHEDULE` entry every 15 minutes, in `temba/settings_common.py`.
- Batched deletion that re-checks eligibility at delete time.
- Tests in `temba/wa_conversation_handovers/tests.py`.
- A `feat:` bullet in `WENI-CHANGELOG.md`.

**Out of scope here**:

- Courier and Mailroom code. Courier keeps its upsert. Mailroom keeps its lookup and consume and still has no age filter (see Edge Cases).
- A new column such as `updated_on`, or any schema change, unless planning proves the index is needed.
- Archiving the rows before deletion.
- Org, channel, or contact release paths. These foreign keys are `PROTECT`, and fixing release ordering is a separate change.
- Redis keys Courier keeps for thread ownership and standby deduplication. They already expire after 24 hours.

## Current State

- `WAConversationHandover` (`temba/wa_conversation_handovers/models.py`, table `wa_conversation_handover`) has `occurred_on`, `created_on` (default now), `consumed_on`, and `consumed_msg_id`. A partial unique constraint `uq_wa_conv_handover_pending` allows one unconsumed row per channel and contact. Indexes: `(channel, contact, consumed_on)`, `(org, contact_urn, consumed_on)`, `(channel, contact, -occurred_on)`. There is no index on `created_on`. No other model points to this table, and no task deletes from it.
- **Writer, Courier** (`backends/rapidpro/wa_conversation_handover.go`, `upsertWAConversationHandoverSQL`): `INSERT ... ON CONFLICT (channel_id, contact_id) WHERE consumed_on IS NULL DO UPDATE`. The conflict branch replaces `context_text` on Courier `main`, and appends it on branch `feat/multipartner-standby` (multipartner standby, not yet merged). In both versions it sets `occurred_on = EXCLUDED.occurred_on` (the event's own time, which can be old for Meta retries and spooled events), and sets `created_on = NOW()`. Courier spec 006 records this as "latest write wins for freshness". So **`created_on` is the time of the last write, not the creation time**. No Courier test asserts the `created_on` refresh. A consumed row is never updated again by Courier because the conflict target only matches `consumed_on IS NULL`.
- **Consumer, Mailroom** (`core/tasks/handler/worker.go`, `consumeHandoverContext`): in one transaction, `SELECT id, context_text ... WHERE channel_id = $1 AND contact_id = $2 AND consumed_on IS NULL` without a row lock, then `UPDATE ... SET consumed_on = NOW(), consumed_msg_id = $1 WHERE id = $2 AND consumed_on IS NULL`. If the update affects 0 rows, the inbound keeps its original text and no context is attached. The lookup does not filter by age.
- No reader of consumed rows exists in Flows, Courier, or Mailroom. Mailroom keeps the consumed text in memory for the router request only.
- 24 hours is the WhatsApp thread-idle window that Courier already uses as the TTL of `wac:thread_owner:*` and `wac:standby:seen:*`.
- Sibling tasks (`trim_http_logs_task`, `trim_channel_log_task`) read `settings.RETENTION_PERIODS[...]`, select up to 1000 ids, delete by id, loop until empty, and log the count and `timesince(start)`. They are tested by calling the task directly in a `TembaTest`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Consumed context does not stay stored (Priority: P1)

After Mailroom attaches a handover or standby context to an inbound message, the conversation text it carried is no longer needed. The platform operator expects it to disappear on the next cleanup run instead of accumulating forever.

**Why this priority**: Consumed rows are most of the table and they hold conversation text with no reader. Deleting them is the main retention fix.

**Independent Test**: Store a consumed row and a pending row for the same channel and contact, run the task, and check that only the consumed row is gone.

**Acceptance Scenarios**:

1. **Given** a row consumed one minute ago, **When** the task runs, **Then** the row is deleted.
2. **Given** a row consumed three days ago, **When** the task runs, **Then** the row is deleted.
3. **Given** a consumed row and a new pending row for the same channel and contact, **When** the task runs, **Then** the consumed row is deleted and the pending row is kept unchanged.

---

### User Story 2 - Abandoned context expires after 24 hours (Priority: P1)

Some handover context is never consumed, because the shopper does not write again. The operator expects that context to be removed once 24 hours pass with no new write, matching the WhatsApp thread-idle window.

**Why this priority**: Without expiry, pending rows keep conversation text forever and the retention promise is not met.

**Independent Test**: Store a pending row last written 25 hours ago and another last written 1 hour ago, run the task, and check that only the first is gone.

**Acceptance Scenarios**:

1. **Given** a pending row whose last write was 25 hours ago, **When** the task runs, **Then** it is deleted.
2. **Given** a pending row whose last write was 1 hour ago, **When** the task runs, **Then** it is kept.
3. **Given** a pending row whose last write was exactly 24 hours ago, **When** the task runs, **Then** it is deleted, and one written 23 hours 59 minutes ago is kept.

---

### User Story 3 - Recently appended context is never lost (Priority: P1)

Courier keeps appending standby and handover lines to the same pending row. A row can hold content that started days ago and still receive a line now. The operator expects the cleanup to keep any row that was just written to, so Mailroom attaches the full, current context on the next inbound.

**Why this priority**: Deleting a row that just received content would silently drop context that the brain router needs. That is worse than keeping data too long.

**Independent Test**: Store a pending row with `occurred_on` three days ago and `created_on` now. Separately, select a row as expired, then refresh it with new text before its batch's delete runs. Run the task. Both rows are kept with their latest text.

**Acceptance Scenarios**:

1. **Given** a pending row with `occurred_on` three days ago and last written now, **When** the task runs, **Then** it is kept.
2. **Given** a pending row that is expired when its batch is selected, **When** Courier writes to it before that batch is deleted (append or replace, depending on the Courier version), **Then** the row is kept with the new text and its new write time.
3. **Given** Courier writes a new pending row for a channel and contact right after the task deleted the expired one, **When** the next inbound arrives, **Then** Mailroom attaches only the new content.

---

### User Story 4 - Cleanup does not load the database (Priority: P2)

The operator expects cleanup to keep up with production volume without long locks or one huge delete, including the first run against the backlog that exists today.

**Why this priority**: The first run meets every row stored since the table was created. A single delete of that size would hold locks and bloat the write-ahead log.

**Independent Test**: With the batch size reduced to 2 in a test, store 5 eligible rows and 1 valid row. One run deletes all 5 across 3 batches and keeps the valid row.

**Acceptance Scenarios**:

1. **Given** more eligible rows than one batch, **When** the task runs, **Then** it deletes them in batches of at most the batch size until none are left.
2. **Given** a run still in progress, **When** the next schedule fires, **Then** the second run does not start in parallel.

---

### Edge Cases

- **Append after selection** (AC-6): the delete statement itself re-checks eligibility. Under PostgreSQL's default isolation, a delete that waits on a row Courier is updating re-evaluates its condition against the committed version, so the refreshed row no longer matches and is kept.
- **Insert after delete**: if Courier's upsert waits on a row the task is deleting, it inserts a new pending row once the delete commits. That new row holds only the new content, which is the intended outcome for expired context.
- **Consume after lookup, row deleted**: Mailroom looked up an expired pending row, then the task deleted it. Mailroom's update affects 0 rows, the inbound keeps its own text, and no context is attached. Acceptable, since that context was expired.
- **Consume before delete**: if Mailroom has updated the row and not committed yet, the delete waits. After the commit, the row is consumed and is deleted. Mailroom already holds the text in memory.
- **Expired but not yet trimmed**: Mailroom has no age filter, so a pending row last written between 24 hours and 24 hours plus one run interval ago can still be attached. The 15-minute schedule bounds that window. Adding an age filter to Mailroom is out of scope.
- **Old `occurred_on`**: a Meta retry or a spooled Courier event can carry an `occurred_on` older than 24 hours on a row written now. `occurred_on` is never the expiry reference.
- **Clock source**: Courier sets `created_on` with the database clock and the task computes the cutoff with the worker clock. Skew of seconds or minutes cannot make a row written now look 24 hours old.
- **Run longer than the schedule interval**: the first run may take more than 15 minutes while it clears the backlog. The lock watchdog keeps the lock alive while the run is alive, so the next beat skips instead of starting in parallel. If the worker dies, the lock expires within 900 seconds and the next run resumes.
- **Empty table or nothing eligible**: the run deletes nothing, logs 0, and ends.
- **Database error mid-run**: committed batches stay deleted. The error is raised to Celery and the next scheduled run continues from what is left, so no retry logic is added.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST run a cleanup of `wa_conversation_handover` every 15 minutes, as a non-overlapping task in the `trim_*` pattern registered in the beat schedule.
- **FR-002**: Each run MUST delete every row whose `consumed_on` is set, regardless of age.
- **FR-003**: Each run MUST delete every row whose `consumed_on` is not set and whose `created_on` is at or before now minus the configured retention.
- **FR-004**: The retention MUST be 24 hours and MUST come from a named entry in `RETENTION_PERIODS`, not an inline literal.
- **FR-005**: Expiry MUST be measured from `created_on`, which holds the last write time. `occurred_on` MUST NOT be used to decide expiry.
- **FR-006**: Deletion MUST run in batches of at most a named batch size (1000) and MUST repeat until no eligible row remains.
- **FR-007**: The delete of each batch MUST re-apply the eligibility condition from FR-002 and FR-003 in the same statement. Deleting by id alone is not allowed.
- **FR-008**: The cleanup MUST NOT change a row it does not delete, and MUST NOT touch rows of other tables.
- **FR-009**: Each run MUST log the number of rows actually deleted (as reported by the delete, not the number of selected ids) and the run duration. Logs MUST NOT contain contact URNs, contact names, or context text.
- **FR-010**: `WENI-CHANGELOG.md` MUST record the new retention under a new version heading at the top. No user interface text is added.

### Key Entities

- **Handover context row**: one stored context for a WhatsApp channel and contact, holding text from a handover summary or a standby transcript. It is pending until Mailroom consumes it, and at most one pending row exists per channel and contact.
- **Last write time** (`created_on`): set when Courier creates the row and reset on every append. This is the expiry reference.
- **Event time** (`occurred_on`): the time of the provider event that caused the latest write. Informational only for this feature.
- **Consumption** (`consumed_on`, `consumed_msg_id`): set once by Mailroom when the context is attached to an inbound message. A consumed row is never written again.
- **Retention period**: 24 hours after the last write, aligned with the WhatsApp thread-idle window.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In steady state, no row with `consumed_on` set is older than 15 minutes plus one run duration.
- **SC-002**: In steady state, no unconsumed row has a last write older than 24 hours plus 15 minutes plus one run duration.
- **SC-003**: 0 rows written within the last 24 hours and still unconsumed are deleted, including rows that received an append during a run.
- **SC-004**: No single deletion step removes more than 1000 rows.
- **SC-005**: The first production run clears the existing backlog without overlapping runs and without blocking Courier writes or Mailroom consumes for longer than one batch.

## Assumptions

- Courier keeps `created_on = NOW()` on every append, as recorded in Courier spec 006. This feature depends on that behavior. A Courier regression test for the refresh is recommended as a follow-up in Courier. The choice of `created_on` as the expiry reference does not depend on Courier branch `feat/multipartner-standby`: both `main` and that branch refresh `created_on`. The branch only decides whether a recently written row also carries older appended text.
- Consumed rows have no reader after the consume commits, so deleting them immediately loses no product behavior. `consumed_msg_id` is not kept for audit.
- 24 hours matches the WhatsApp thread-idle window already used for Courier's ownership and standby Redis keys.
- 15 minutes matches the existing high-frequency trim (`trim-event-fires`) and keeps the expired-context window short, since Mailroom has no age filter.
- **Peak load (Principle XII)**: the declared write peak is Courier's inbound peak of 242.9 requests/s (1-minute rate, 2026-10-28 14:06 UTC, recorded in Courier spec 006). That is the upper bound of handover upserts. In the worst case, one 15-minute interval produces at most 218,610 eligible rows, which is at most 219 batches of 1000 in one run. The steady-state table then holds at most the pending rows of the last 24 hours plus one interval of consumed rows. The first run handles the backlog with the same batches.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-1 task, lock, schedule | `temba/wa_conversation_handovers/tests.py` imports the task from `temba/wa_conversation_handovers/tasks.py` and calls it directly, as `temba/request_logs/tests.py` does for `trim_http_logs_task`. A test asserts the `CELERY_BEAT_SCHEDULE` entry points at the task name with a 15-minute schedule. Lock and watchdog behavior is covered by the existing `nonoverlapping_task` tests in `temba/utils/tests.py`; the task declares `use_watchdog=True` (Implementation Decisions). |
| AC-2 consumed rows | Rows consumed 1 minute ago and 3 days ago are both deleted. A consumed row plus a new pending row for the same channel and contact: only the consumed row is deleted, and the pending row's text and `created_on` are unchanged. |
| AC-3 expired rows | A pending row with `created_on` 25 hours ago is deleted. Boundary: `created_on` exactly at the cutoff is deleted, and 23 hours 59 minutes is kept. Time is frozen or the cutoff is computed from a patched now so the boundary is exact. |
| AC-4 expiry reference | A pending row with `occurred_on` 3 days ago and `created_on` now is kept. A pending row whose text was appended (text updated, `created_on` set to now, the way Courier's upsert does) after being created 2 days ago is kept with the appended text. |
| AC-5 batching | With the batch size patched to 2, 5 eligible rows and 1 valid row: one run deletes the 5 and keeps the valid one. The test asserts the number of batches (for example with `assertNumQueries` or by counting delete calls), and uses `CaptureQueriesContext` to assert that each batch issues exactly one `DELETE`, which guards the single-statement delete that FR-007 relies on. |
| AC-6 race with Courier | Batch ids are materialized as a list before the delete, so the delete does not re-run the selection. The test patches the id selection to return the real ids and, before returning, updates one of those rows the way Courier's upsert does (`created_on` set to now, text changed). The run keeps that row with the new text, deletes the other rows of the batch, and logs a count that excludes the kept row. Without the eligibility condition in the delete, this test fails. |
| AC-7 race with Mailroom | A consumed row and the next pending row for the same channel and contact are covered by AC-2. The 0-rows consume after deletion is Mailroom's existing path (`ConsumePendingWAConversationHandover` returns false); no Mailroom change is made. |
| AC-8 gates | `poetry run coverage run manage.py test temba.wa_conversation_handovers`, clean `./code_check.py` (including no missing migrations), green `.github/workflows/ci.yml`. No new `# pragma: no cover`; the per-10,000 progress log of the sibling trims is not copied. |
| AC-9 log and changelog | A test asserts the info log contains the deleted count and no contact URN or context text. The PR adds a `feat:` bullet under a new version heading at the top of `WENI-CHANGELOG.md`. |

**Flow coverage** (Principle XIV): one test stores a mix of consumed, expired, valid, and recently updated rows, runs the task as Celery beat would, and asserts exactly which rows remain. That is the complete use case. The boundary, batching, and race cases are focused siblings.

**Failure paths**: the race in AC-6 is the failure path that matters for data. A database error raised from the task is left to Celery, and the next run resumes. The test suite covers the empty-table run (0 deleted).

**Gates**: `poetry run coverage run manage.py test` for `temba.wa_conversation_handovers`, clean `./code_check.py`, green `.github/workflows/ci.yml`.

## Rollout and Rollback

1. Deploy Flows. No migration and no Courier or Mailroom deploy. Celery beat picks up the new entry on restart.
2. Watch the first run's log line: the deleted count clears the backlog, and the following runs settle to small counts.
3. Confirm a pending row written within 24 hours is still there and still attached by Mailroom on the next inbound.
4. **Rollback:** remove the beat entry or revert the change. Rows already deleted are not restored. Rows that are not deleted simply accumulate again, as they do today.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | Delivered through a PR to `main` with review and green `ci.yml`. | none |
| II. Security and Secrets | No new secret or dependency. Reduces stored conversation text. | none |
| III. Observability | One structured info log per run with count and duration, no URN or context text. | none |
| IV. Versioned Contracts | No public API, channel config, event payload, or migration. Relies on Courier's documented `created_on` refresh, which is unchanged. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`. Each acceptance criterion maps to a check in Test Strategy. | none |
| VI. No Silent Divergence | Not applicable: no Product Spec. | none |
| VII. Commit Messages | Atomic Conventional Commits, descriptions of 50 characters or fewer. | none |
| VIII. Changelog Maintenance | `feat:` bullet in `WENI-CHANGELOG.md` under a new version heading at the top. `CHANGELOG.md` is not rewritten. | none |
| IX. Never Trust the Client | No new input boundary. The task reads only its own settings. | none |
| X. Fail Gracefully | Database calls use the existing connection settings. An error ends the run and the next run resumes. `nonoverlapping_task` keeps its default 900-second lock, extended by the watchdog while the run is alive. | none |
| XI. Bounded Retry Over REST | No REST propagation. | none |
| XII. Scalability and Peak Load | Stateless worker task. Peak declared in Assumptions: 242.9 upserts/s, at most 219 batches per run. | none |
| XIII. Diagnosable Errors | Errors go to Sentry through Celery with the task name. No personal data is added. | Platform `send_default_pii=True` remains `TODO(SENTRY_PII)`. |
| XIV. Tests Exercise Flows | One mixed-rows run test plus boundary, batching, and race siblings on `TembaTest`. | none |
| XV. Explicit Over Clever | Named retention in `RETENTION_PERIODS` and a named batch size constant. A comment explains why `created_on` is the expiry reference (Courier resets it on every append; `occurred_on` can be old) and why the delete re-checks eligibility. | none |
| XVI. Contained Changes | The new task, its two settings entries, tests, and the changelog bullet. No Courier, Mailroom, model, or schema change. | none |
| XVII. Explicit, Scoped Authorization | No endpoint. | none |
| Backend Standards | `code_check.py`. No new locale string. | none |

## Implementation Decisions

- Task name `trim_wa_conversation_handovers_task`, beat key `trim-wa-conversation-handovers`, schedule `timedelta(minutes=15)`, retention key `"wa_conversation_handover": timedelta(hours=24)`.
- Eligibility: `consumed_on IS NOT NULL OR created_on <= cutoff`, with cutoff computed once per run. `__lte` matches the sibling trims.
- The task uses `@nonoverlapping_task(..., use_watchdog=True)` with the default 900-second lock, as `squash_flowcounts` and `sync_classifier_intents` already do. The first run may exceed one schedule interval while it clears the backlog. The watchdog extends the lock while the run is alive, so the next beat skips instead of starting in parallel. If the worker dies, the lock expires within 900 seconds and the next run resumes.
- Each batch selects up to 1000 ids matching eligibility and materializes them as a list (`list(...)`), then deletes `WHERE id IN (...) AND <eligibility>` in one statement. The list keeps the delete from re-running the selection as a subquery, so the eligibility condition in the delete is what protects a row that Courier writes between selection and delete. The selection lives in a small helper that tests can patch (AC-6). The model has no reverse relations or delete signals, so Django runs one `DELETE` without loading rows.
- `num_deleted` adds the row count returned by each `delete()`, not the number of selected ids. A row kept by the re-check (AC-6) is not counted. The loop ends when the selection returns no ids.
- `created_on` is the expiry reference because Courier's conflict update sets it to `NOW()`. Using `occurred_on` would delete fresh rows that carry an old provider timestamp.
- No index is added. In steady state the table stays small (pending rows of the last 24 hours plus one interval of consumed rows), and consumed rows are dense, so each batch query finds 1000 matches quickly. If the plan or production metrics show sequential scans are too costly, a partial index on `created_on` would require a migration and promotion to SDD Full.
- No Mailroom age filter. The 15-minute interval bounds how long expired context can still be attached.

## Open Questions

None. Immediate deletion of consumed rows follows the request ("already consumed or older than 24 hours"), and no reader of consumed rows exists.
