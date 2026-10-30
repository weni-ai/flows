# Engineering Specification: Purchase value and currency on Meta CAPI

**Repository**: weni-ai/flows — backend

**Feature Branch**: `012-fix-purchase-custom-data`

**Created**: 2026-10-30

**Status**: Draft (Q1 answered 2026-10-30: missing currency stays `"BRL"`)

**Suggested cycle**: SDD Lite. The change is a contained fix in `temba/conversion_events`: payload shape for Meta purchase events, related tests, and optional CTWA Datalake metadata. No migration, no new public API version, no Courier or Mailroom coordination, and no new channel type.

## Origin Without Product Spec

- Product Spec: none
- Problem: Purchase conversion events sent to Meta Conversions API put `value` and `currency` on the event root. Meta expects them inside `custom_data`, so purchase amount and currency are ignored or rejected. Zero values are dropped as if absent, and success paths do not log enough to confirm what Meta received.
- Acceptance criteria:
  - AC-1: For a purchase that is forwarded to Meta, the payload's `data[0]` contains `custom_data.value` as a number and `custom_data.currency` as a string, and neither `value` nor `currency` appears on the event root.
  - AC-2: `value` of `0` (numeric zero) is treated as present and is sent as `custom_data.value` `0.0` (or `0`).
  - AC-3: When `value` is missing (`null` or omitted), Meta is still called if other purchase conditions are met, but `custom_data` is omitted. Currency is not invented in that case.
  - AC-4: When `value` is present but cannot be converted to a number, the purchase event is still forwarded without `custom_data`, and a warning is logged without the contact identifier.
  - AC-5: When `value` is present and `currency` is omitted from the request, `custom_data.currency` is `"BRL"` (same default as today). A unit test covers that case. Using channel `wa_currency` instead is out of scope for this cut.
  - AC-6: Lead events are unchanged: they do not include `custom_data`, `value`, or `currency`.
  - AC-7: CTWA Datalake metadata for purchase includes `order_value` as today and also `currency` (from the request, or `"BRL"` when omitted) whenever `order_value` is sent.
  - AC-8: Automated tests in this repository cover AC-1 through AC-7 without calling Meta. A success Meta response is asserted from a stub. Production confirmation that Events Manager shows the amount remains a rollout check, not a CI gate.
  - AC-9: On a Meta success and on a Meta failure, logs record event name, HTTP status (or a short error class), dataset identifier, and whether `custom_data` was present. They MUST NOT record `ctwa_clid`, access tokens, phone numbers, or the full request body.

## Scope in This Repository

**This repository implements**:

- Correct placement of purchase `value` and `currency` under `custom_data` in the Meta payload built by the conversion endpoint.
- Treating numeric zero as a valid purchase value.
- Keeping `"BRL"` as the currency when the request omits it (unchanged vs today).
- Adding `currency` to CTWA Datalake purchase metadata whenever `order_value` is sent.
- Structured logs on Meta send outcome without PII or secrets.
- Tests in `temba/conversion_events/tests.py` (and helpers in the same app if needed).
- A `WENI-CHANGELOG.md` entry for the user-facing correction of purchase amounts sent to Meta.

**Out of scope here**:

- Lead events and `conversation_started`.
- Changing who is allowed to POST `/conversion/` or how `ctwa_clid` / dataset gating works.
- Real HTTP calls to Meta in CI.
- Changing the Meta partner agent string, `action_source`, `messaging_channel`, or `user_data` shape.
- Datalake schema migrations owned by the Datalake service; this change only adds an optional metadata field on an existing event.

## Current State

- `POST /conversion/` is handled by `ConversionEventView` in `temba/conversion_events/views.py`.
- For `lead` and `purchase`, when the contact has CTWA data (`ctwa_clid`) and the channel has a Meta dataset, `_build_meta_payload` builds the CAPI body and `_send_to_meta` posts it.
- `_build_meta_payload` currently does `if value:` (so `0` is skipped) and sets `meta_event["value"]` / `meta_event["currency"]` on the root, defaulting currency with `original_payload.get("currency", "BRL")`.
- `_send_to_meta` returns `"Success"` on HTTP 200 without logging the outcome; failures return the Meta error body as a string.
- `_send_ctwa_datalake` maps purchase `value` to `metadata.order_value` and does not send currency.
- Channel WhatsApp Cloud config already stores `wa_currency`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Purchase amount reaches Meta (Priority: P1)

A workspace that attributes WhatsApp ads conversions sends a purchase after a click-to-WhatsApp conversation. Media buyers and operators need Meta Events Manager to show the purchase amount and currency, not a Purchase event with an empty value.

**Why this priority**: This is the defect. Incorrect field placement means ads reporting undercounts or drops revenue.

**Independent Test**: Stub the Meta HTTP client. POST a purchase with `value` and `currency` for a contact that has `ctwa_clid` and a channel with a dataset. Assert the JSON body posted to Meta.

**Acceptance Scenarios**:

1. **Given** a contact with `ctwa_clid` and a channel with a dataset, **When** a purchase is posted with `value` `150.0` and `currency` `"BRL"`, **Then** the Meta body has `data[0].custom_data.value` `150.0` and `data[0].custom_data.currency` `"BRL"`, and `data[0]` has no top-level `value` or `currency`.
2. **Given** the same gating, **When** a purchase is posted with `value` `0`, **Then** `custom_data.value` is `0` (numeric) and `custom_data.currency` is present.
3. **Given** the same gating, **When** a lead is posted, **Then** the Meta body has no `custom_data` and no root `value` or `currency`.

---

### User Story 2 - Missing or invalid money fields fail in a defined way (Priority: P1)

Callers sometimes omit currency, omit value, or send a non-numeric value. Operators must not silently attribute revenue in the wrong currency, and they must be able to see why an amount was dropped.

**Why this priority**: The `if value:` check drops legitimate zero-amount purchases in the same method that misplaces `custom_data`.

**Independent Test**: Unit tests on the conversion endpoint with a stubbed Meta client, covering zero, missing value, invalid value, and missing currency.

**Acceptance Scenarios**:

1. **Given** a purchase with no `value` (omitted or `null`), **When** it is forwarded to Meta, **Then** the event is sent without `custom_data`.
2. **Given** a purchase with `value` `"not-a-number"`, **When** it is processed, **Then** Meta is called without `custom_data` and a warning is logged without contact identifiers.
3. **Given** a purchase with a numeric `value` and no `currency` in the body, **When** it is processed, **Then** `custom_data.currency` is `"BRL"`.

---

### User Story 3 - Operators can confirm Meta accepted the amount (Priority: P2)

After deploy, an operator or engineer needs to confirm a purchase was accepted with a value, using logs and Meta Test Events / Events Manager, without reading secrets from logs.

**Why this priority**: The original bug was hard to prove in production because success logs did not describe the payload shape.

**Independent Test**: Tests assert log records on stubbed 200 and non-200 Meta responses. Staging or Test Events validation is listed under Rollout.

**Acceptance Scenarios**:

1. **Given** Meta returns HTTP 200, **When** a purchase is sent, **Then** a structured log records event name, status `200`, dataset id, and that `custom_data` was present, and does not contain `ctwa_clid` or the access token.
2. **Given** Meta returns a 4xx or 5xx, **When** a purchase is sent, **Then** a log records the status or error class with the same non-PII context.

---

### Edge Cases

- `value` `0`, `"0"`, and `0.0` are valid amounts.
- `value` omitted vs `null` vs empty string: omitted and `null` mean absent; empty string is invalid (same path as non-numeric).
- Currency is used as provided by the caller when present; when omitted or empty, it is `"BRL"`.
- Purchase without CTWA or without dataset still goes to Datalake only; Meta payload rules do not apply.
- CTWA Datalake write failure remains best-effort and must not fail the HTTP conversion response if legacy Datalake succeeded (existing behaviour).

## Clarifications

### Session 2026-10-30

- Q: When purchase `value` is present and `currency` is omitted, should Flows use channel `wa_currency`, reject the Meta send, or omit `custom_data`? → A: Keep today's behaviour: default `currency` to `"BRL"`. Channel `wa_currency` is out of scope for this cut.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The conversion endpoint MUST place purchase amount and currency inside `custom_data` on the Meta event object.
- **FR-002**: The conversion endpoint MUST NOT put `value` or `currency` on the Meta event root.
- **FR-003**: A purchase `value` of numeric zero MUST be sent.
- **FR-004**: Presence of `value` MUST be checked as "not null / not omitted", not as boolean truthiness.
- **FR-005**: Invalid numeric `value` MUST not be sent as `custom_data`; the rest of the purchase event MAY still be sent to Meta.
- **FR-006**: Lead payloads MUST remain without `custom_data`.
- **FR-007**: When `value` is present and `currency` is omitted, the conversion endpoint MUST send `custom_data.currency` `"BRL"`.
- **FR-008**: CTWA Datalake purchase metadata MUST include `currency` whenever `order_value` is sent (request currency, or `"BRL"` when omitted).
- **FR-009**: Meta send success and failure MUST be logged with opaque identifiers only (org/channel/dataset/event name/status), never tokens or `ctwa_clid`.
- **FR-010**: Automated tests MUST stub Meta HTTP and MUST cover custom_data shape, `value` `0`, invalid value, missing value, missing currency, and unchanged lead.

### Key Entities

- **Conversion event**: inbound `lead`, `purchase`, or `conversation_started` on `POST /conversion/`.
- **Meta CAPI purchase event**: outbound event named `Purchase` with `user_data` (`whatsapp_business_account_id`, `ctwa_clid`) and optional `custom_data` (`value`, `currency`).
- **CTWA click record**: stored click that supplies `ctwa_clid` and WABA for Meta user_data.
- **Channel dataset**: channel configuration that enables forwarding to Meta.
- **CTWA Datalake event**: analytics event whose purchase metadata includes `order_value` and, after this change, optional `currency`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of purchase events forwarded to Meta in tests include amount and currency only under `custom_data` when a valid value and a resolved currency exist.
- **SC-002**: 100% of purchase events with `value` `0` in tests still carry that amount to Meta when currency is resolved.
- **SC-003**: 100% of purchase events in tests that omit currency and still send `custom_data` use `"BRL"`.
- **SC-004**: After rollout, a Test Events (or Events Manager) purchase shows a non-empty value matching the posted amount for a known test click.
- **SC-005**: On-call can confirm a Meta success from logs in under five minutes without opening a payload that contains `ctwa_clid`.

## Assumptions

- Callers that already send `currency` keep doing so. Callers that omit it continue to be treated as BRL, matching production today. Switching to `wa_currency` can be a later change.
- Meta continues to accept `action_source` `business_messaging` and `messaging_channel` `whatsapp` as today.
- Adding optional `currency` on CTWA Datalake metadata is backward compatible for consumers that ignore unknown keys.
- Peak load is unchanged: this endpoint already exists; the fix does not add fan-out. Declared peak is the current conversion-event peak for the workspace, on the order of tens of purchase posts per minute in the busiest org, not a new traffic class.
- Manual Events Manager validation is a rollout step; CI never calls Meta.

## Contracts

- Inbound `POST /conversion/` body is unchanged (still optional `payload.value` / `payload.currency`).
- Outbound Meta CAPI body for purchase is a backward-compatible correction toward Meta's documented shape (fields move into `custom_data`). Consumers of the Meta event are Meta, not other Weni services. SemVer of the Flows public API is unaffected.
- CTWA Datalake metadata gains optional `currency`. Additive; no deprecation.

## Observability

- Log Meta send outcome: `event_name`, `dataset_id`, HTTP status or error class, `has_custom_data`, channel UUID, org/project opaque id when already available on the view.
- Do not log `ctwa_clid`, WABA if treated as sensitive in neighbouring logs, access token, or raw bodies.
- Existing Sentry context rules apply; no new PII.

## Failure Handling

- Meta HTTP already uses a 30s timeout. No change to timeout length.
- Retry of Meta POST is unchanged in this spec (out of scope). Exhausted or 4xx failures remain logged and do not block Datalake when that path already succeeds independently.
- Invalid `value` is a request defect: no retry of a rebuilt payload.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-1 custom_data shape | `temba/conversion_events/tests.py`: stub `requests.post` (or `_send_to_meta`'s HTTP). POST purchase with value and currency. Assert JSON `data[0]["custom_data"]` and assert `"value" not in data[0]` and `"currency" not in data[0]`. |
| AC-2 value 0 | Same class: `value` `0` and `"0"`. Assert `custom_data["value"] == 0` (numeric). |
| AC-3 missing value | Purchase without `value` / with `null`. Assert no `custom_data` key. |
| AC-4 invalid value | `value` `"abc"`. Assert no `custom_data`; `assertLogs` warning without the contact URN. |
| AC-5 missing currency | Purchase with numeric `value` and no `currency`. Assert `custom_data["currency"] == "BRL"`. |
| AC-6 lead unchanged | Lead POST still produces Meta payload without `custom_data`. |
| AC-7 Datalake currency | Existing dual-write purchase test extended: `metadata["order_value"]` plus `metadata["currency"]` (body or `"BRL"`). |
| AC-8 no real Meta | Tests patch HTTP; no network. |
| AC-9 logs | `assertLogs` on 200 and on non-200; extras omit `ctwa_clid` and token. |

**Flow coverage** (Principle XIV): one test posts `POST /conversion/` as the client does, with CTWA + dataset, and asserts the stubbed Meta call body and a successful conversion response. That is the complete use case, not only `_build_meta_payload` in isolation. Isolated method tests MAY cover value parsing variants.

**Failure paths**: invalid value, missing value, missing currency, Meta HTTP error, lead (no custom_data).

**Gates**: `poetry run coverage run manage.py test temba.conversion_events`, clean `./code_check.py`, green `.github/workflows/ci.yml`. No new `# pragma: no cover`.

## Rollout and Rollback

1. Deploy Flows with the payload fix. No migration.
2. In staging or Meta Test Events, send one purchase with a known amount and confirm Events Manager shows that amount.
3. Confirm logs on that request contain status and `has_custom_data` and do not contain `ctwa_clid`.
4. **Rollback:** revert the conversion_events change. Meta again receives root-level fields (previous broken behaviour). Datalake consumers that started reading `currency` ignore a missing key.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | Delivered through a PR to `main` with review and green `ci.yml`. | none |
| II. Security and Secrets | No new secret. Token stays in settings. Logs must not print the Meta URL query token. | none |
| III. Observability | Structured outcome logs; no `ctwa_clid` or token. | none |
| IV. Versioned Contracts | Inbound conversion API unchanged. Meta body corrected to vendor contract. Datalake metadata additive. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`. | none |
| VI. No Silent Divergence | Not applicable: no Product Spec. | none |
| VII. Commit Messages | Atomic Conventional Commits, ≤50 character descriptions. | none |
| VIII. Changelog Maintenance | `fix:` bullet in `WENI-CHANGELOG.md` that purchase value/currency go to Meta `custom_data`. | none |
| IX. Never Trust the Client | Value parsed at the server; invalid value dropped from `custom_data`. Auth of `/conversion/` unchanged. | none |
| X. Fail Gracefully | Existing 30s Meta timeout; defined JSON errors; no stack traces to caller. | none |
| XI. Bounded Retry Over REST | Unchanged; this spec does not add unbounded retry. | none |
| XII. Scalability and Peak Load | Stateless view. Peak unchanged: tens of purchase posts per minute in the busiest org. | none |
| XIII. Diagnosable Errors | Logs/Sentry use org/channel/dataset ids, not phone or clid. | Platform `send_default_pii=True` remains `TODO(SENTRY_PII)`. |
| XIV. Tests Exercise Flows | Full POST → stubbed Meta assertion, plus edge cases. `TembaTest`. | none |
| XV. Explicit Over Clever | Named mapping for Meta event names. Default currency `"BRL"` is a named constant with a comment that it keeps today's behaviour pending a later `wa_currency` cut. Comment on why zero is `is not None`. | none |
| XVI. Contained Changes | Only conversion event Meta/Datalake purchase fields and tests. Lead path untouched. | none |
| Backend Standards | `code_check.py`. No new user-facing locale string. | none |

## Implementation Decisions

- SDD Lite: one app, no migration, no Courier/Mailroom.
- `custom_data` only for purchase when there is a parsed numeric value (including zero). Currency is the request value, or `"BRL"` when omitted, so Meta always receives the pair when value is valid.
- Datalake `order_value` remains independent of Meta `custom_data` so analytics still see zero and valid amounts even if Meta is skipped.

## Open Questions

None. Missing currency stays `"BRL"` for this cut.
