# Implementation Plan: Other-owner failure reason

**Branch**: `019-other-owner-fail-reason` | **Date**: 2026-11-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/019-other-owner-fail-reason/spec.md`

## Summary

Accept Courier’s stored failure `status=F` + `failed_reason=H` on `msgs_msg`, show “Another service has the conversation” (Portuguese: “Outro atendimento está com a conversa”) on contact history, the failed-messages list, and the message log, and keep Resend from sending those ids to Mailroom. No new column, no database check, no public API field, no Mailroom change.

## Technical Context

**Language/Version**: Python ≥3.10,<3.12 (CI 3.11) / Django ^3.2

**Primary Dependencies**: Existing `Msg` choices, `Event.from_msg`, contact-history and message-list templates, `MailroomClient.msg_resend` (caller filter only)

**Storage**: PostgreSQL — existing nullable `msgs_msg.failed_reason` varchar(1). Choices-only migration. No check constraint.

**Testing**: `TembaTest` via `poetry run coverage run manage.py test` on the modules in [quickstart.md](./quickstart.md)

**Target Platform**: Flows web (contact history, failed outgoing messages, channel log)

**Project Type**: web-service

**Performance Goals**: No new query. The reason is a column already loaded with the message row.

**Constraints**: Letter stays `H`. Empty reason still resends. Do not use SQL `exclude(failed_reason="H")` (it drops NULL). Do not add a CHECK. Do not read Redis or call Thread Control. Public message API and spreadsheet stay unchanged. Deploy before or with the Courier release that writes `H`.

**Scale/Scope**: Peak unchanged: current peak of contact-history and failed-list views for the busiest workspace (Principle XII). One choice, three screens, one Resend filter, four locale strings (EN source, ES, pt_BR, RO).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Pre-design | Post-design |
|-----------|------------|-------------|
| I. Version Control and Review | PR to `main`, review, green `ci.yml` | unchanged |
| II. Security and Secrets | No new secret, dependency, or credential | unchanged |
| III. Observability | No new log line; no personal data added | unchanged |
| IV. Versioned Contracts | Public message API and spreadsheet unchanged. History event gains an optional display string. `msg/resend` payload shape unchanged; caller omits `H`. Migration keeps the column optional and adds no check. Courier spec 008 writes `F`+`H`. Mailroom needs no release. | Contracts in `contracts/other-owner-failure.md` match this |
| V. Specification Traceability | Origin without Product Spec. AC-F1–AC-F6 and AC-M map to tests | unchanged |
| VI. No Silent Divergence | No Product Spec | unchanged |
| VII. Commit Messages | Conventional Commits, ≤50 character descriptions | unchanged |
| VIII. Changelog Maintenance | `feat:` bullet in `WENI-CHANGELOG.md`. `CHANGELOG.md` untouched | unchanged |
| IX. Never Trust the Client | Resend loads rows by id and reads `failed_reason` from the database. The browser does not send the reason letter | unchanged |
| X. Fail Gracefully | No new outbound call. Existing Mailroom timeout stays | unchanged |
| XI. Bounded Retry | No new REST retry. Errored-message index stays status `E` only | unchanged |
| XII. Scalability and Peak Load | Stateless render. Declared peak is the current contact-history and failed-list peak | unchanged |
| XIII. Diagnosable Errors | No new Sentry event | Platform `send_default_pii=True` remains `TODO(SENTRY_PII)` |
| XIV. Tests Exercise Flows | History GET, failed-list GET, channel-log GET, and Resend POST on stored `F`+`H` rows. `TembaTest` | Commands in quickstart.md |
| XV. Explicit Over Clever | Named constant `FAILED_OTHER_OWNER = "H"`. Sentence is the choice label, wrapped for translation | unchanged |
| XVI. Contained Changes | Choice, three screens, Resend filter, locales, migration, tests, changelog | File list below. No API serializer, no export columns, no Mailroom client payload change |
| XVII. Explicit, Scoped Authorization | No new endpoint. Resend keeps `msgs.broadcast_send`. History, failed list, and log keep their current permissions | unchanged |

**Gate result**: PASS. No violations. Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/019-other-owner-fail-reason/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/other-owner-failure.md
├── checklists/requirements.md
└── tasks.md                    # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
temba/msgs/models.py                         # FAILED_OTHER_OWNER, choice label, apply_action_resend filter
temba/msgs/migrations/0176_*.py              # AlterField choices only; depends on 0175_merge_20260910_2109
temba/msgs/tests.py                          # failed list, Resend, channel-release job leaves F+H
temba/mailroom/events.py                     # optional failed_reason_display on outbound events
temba/mailroom/tests.py                      # EventTest.test_from_msg
temba/contacts/tests.py                      # contact history sentence, including pt-br
templates/contacts/contact_history.haml      # sentence on broadcast and message rows
templates/msgs/message_box.haml              # sentence on the shared message row
templates/channels/channellog_read.haml      # sentence in the status area
temba/channels/tests.py                      # ChannelLogTest log page
locale/es/LC_MESSAGES/django.po
locale/pt_BR/LC_MESSAGES/django.po
locale/ro/LC_MESSAGES/django.po
WENI-CHANGELOG.md
```

**Structure Decision**: The reason already lives on `Msg`. Display is the translated choice label, copied onto the history event only when the code is `H`, then rendered by the three templates that already show the message. Resend stays `Msg.apply_action_resend`; it filters the queryset the bulk action already loaded. `message_box.haml` is the row used by `msg_failed.haml` and, through `block.super`, by `message_box_spa.haml`.

## Complexity Tracking

> No constitution violations.

## Phase 0 and Phase 1

Research is [research.md](./research.md). The stored field and the three interfaces are [data-model.md](./data-model.md) and [contracts/other-owner-failure.md](./contracts/other-owner-failure.md). Validation commands are [quickstart.md](./quickstart.md).

Post-design Constitution Check: every row above still passes. Design added no endpoint, no column, no check, and no Mailroom payload field.
