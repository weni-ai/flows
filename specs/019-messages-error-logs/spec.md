# Feature Specification: Message Failure Details on the Public Messages API

**Feature Branch**: `feature/add-channellog-in-messages-endpoint`

**Created**: 2026-11-16

**Status**: Draft

**Cycle**: SDD Lite (specify → implement from this spec). The requester chose Lite. The change still alters the public Messages API (Principle IV), so the Lite gates stay in force: flow tests, `./code_check.py`, `WENI-CHANGELOG.md`, and no archive-format change. `plan.md` and `tasks.md` are not produced.

**Input**: User description: "Expose message failure details (error logs + failed_reason) on the public Messages API"

## Origin Without Product Spec

- Product Spec: none
- Problem: Customers follow up broadcast batches with `GET /api/v2/messages.json?broadcast={id}`. Many messages come back as `status: "failed"` with `sent_on: null`, and nothing in the response says why. The real reason (for example Meta error codes 131026, 131049, 132001) is already recorded in the channel communication logs of each message, but the API doesn't expose it. Requested by customer Tattini (Marcell), operating a WhatsApp channel for Banco Sicoob, raised by John Cordeiro. The customer-facing contract (`temba/api/v2/messages_channel_logs.md` and its PDF) was approved by John.
- Acceptance criteria:
  1. Every message in the Messages API response has a `failed_reason` field with one of the documented values or `null`.
  2. Without `error_logs=true`, the response is the same as before plus `failed_reason`, the `error_logs` key is absent, and the request does no channel log lookup.
  3. With `error_logs=true`, every message has an `error_logs` list. The list is filled with all of that message's channel logs, newest first, when the message has at least one log marked as error or its status is `failed` or `errored`. Otherwise it is `[]`.
  4. A message rejected by the provider at send time returns the provider error in `error_logs`.
  5. A message reported as failed by the provider after sending (status webhook) returns the status log that carries the provider error in `error_logs`.
  6. `Authorization` header values never appear in `error_logs`. Anonymous-org masking and the existing secret redaction still apply.
  7. Channel logs are only returned for messages already visible to the caller's org.
  8. With `error_logs=true`, the number of database lookups for a page doesn't grow with the number of messages on the page.

## Clarifications

### Verified from code (open item 1, status-webhook failures)

Checked against the local `weni-ai/courier` checkout (`bb6c5bef`, staging):

- **(a) The log is linked to the message: yes.** For a WhatsApp Cloud status webhook, `handlers/facebookapp/facebookapp.go` calls `NewMsgStatusForExternalID` + `WriteMsgStatus`. `backends/rapidpro/status.go` resolves the message ID through `UPDATE ... RETURNING msgs_msg.id`, and `server.go` writes the log as `NewChannelLog("Status Updated", channel, e.ID(), ...)`. The only exception is when the status write fails and gets spooled to disk. In that case the ID stays unset and the log isn't linked.
- **(b) The log is saved with `is_error=True`: no.** `is_error` is `log.Error != ""` (`backends/rapidpro/log.go`), and the error passed for status events is the handler's own error. A successfully processed "failed" status has no handler error, so its log is saved with `is_error=False`.
- **Consequences for the approved customer document:**
  - Under the strict error-only rule (decision 3), asynchronous Meta failures (131049, 131026, the most common case) would return `error_logs: []`.
  - Example 2.2 in the document doesn't match what is stored. The description is `"Status Updated"` (not `"Status Update"`), `is_error` is `false`, and the status log `response` is the body Courier returned, without the `HTTP/1.1 200 OK` status line and headers.
  - Send-time error logs have `"\n\nError: <message>"` appended to `response` by Courier. Section 4 of the document already says the format may vary, so this is covered.

### Session 2026-11-16

- Q: Courier saves Meta's asynchronous "failed" status logs with `is_error=false`. When should a message's `error_logs` be filled? → A: When the message has at least one log marked as error, **or** its status is `failed` or `errored`. Logs are returned with their stored `is_error` value, unchanged. The customer document example 2.2 is corrected to show `"Status Updated"`, `is_error: false`, and a response body without the status line and headers.
- Q: Production default for channel log retention is 48 hours, the customer document says 72 hours. How to align? → A: Confirm the effective production value of `RETENTION_PERIODS_CHANNELLOG` first, then update the customer document to match it. No infrastructure change.
- Q: Cap the page size when `error_logs=true`? → A: No cap. The maximum stays at 1000. The customer document keeps recommending smaller pages with `limit`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Diagnose provider failures of a broadcast batch (Priority: P1)

An integrator following up a broadcast batch asks for the batch's messages with `error_logs=true`. For each failed message, they find the provider's error code and description, whether the provider rejected the message at send time or reported the failure later.

**Why this priority**: This is the reason the feature exists. Without it, the customer can't explain or act on failed messages (for example by fixing a template or removing a contact).

**Independent Test**: Create outgoing messages in one broadcast with different channel log histories. Call `GET /api/v2/messages.json?broadcast={id}&error_logs=true` and check the `error_logs` content of each message.

**Acceptance Scenarios**:

1. **Given** a failed message with one send log marked as error whose response contains provider error `132001`, **When** the integrator lists the broadcast with `error_logs=true`, **Then** that message's `error_logs` contains the error log with `is_error: true`, the provider error in `response`, and `failed_reason: null`.
2. **Given** a failed message with a successful send log (HTTP 200) followed by a status webhook log whose request body contains `statuses[].errors[]` with code `131049`, **When** the integrator lists the broadcast with `error_logs=true`, **Then** `error_logs` contains both logs, newest first: the "Status Updated" log first and the send log second, both with `is_error: false`, with `failed_reason: null`. The message qualifies because its status is `failed`.
3. **Given** a delivered message that has a send log and status logs, none marked as error, **When** the integrator lists with `error_logs=true`, **Then** that message has `error_logs: []` and `failed_reason: null`.
4. **Given** a message with no channel logs at all, **When** the integrator lists with `error_logs=true`, **Then** that message has `error_logs: []`.
5. **Given** a message whose error log is among several success logs, **When** the integrator lists with `error_logs=true`, **Then** all of that message's logs are returned, newest first, and only the failing ones have `is_error: true`.
6. **Given** a message that failed at the provider more than the retention window ago, with its logs already trimmed, **When** the integrator lists with `error_logs=true`, **Then** the message has `error_logs: []` and `failed_reason: null`, and the request succeeds normally.
7. **Given** a failed message with no logs, for example an internal failure, **When** listed with `error_logs=true`, **Then** it has `error_logs: []`, because qualifying only selects which messages get their logs.
8. **Given** a qualifying message, **When** its `error_logs` is returned, **Then** each item has exactly `created_on`, `description`, `is_error`, `method`, `url`, `request`, `response`, `response_status`, and `elapsed_ms`.

---

### User Story 2 - Sensitive data stays protected and isolated (Priority: P1)

The org admin turning on `error_logs` needs to be sure that responses never expose channel credentials, never mask less contact data than the platform already masks, and never show another org's logs.

**Why this priority**: The logs are raw HTTP traffic with provider credentials and contact identifiers. Exposing them through a public API without these protections would be a security incident.

**Independent Test**: Seed logs whose request and response contain `Authorization` headers, the system-user token, and contact URNs, in a normal org, an anonymous org, and a second org. Call the endpoint as each org's API user.

**Acceptance Scenarios**:

1. **Given** a qualifying message whose log `request` contains `Authorization: Bearer <token>`, **When** returned in `error_logs`, **Then** the header value is replaced by `********` and the token appears nowhere in the item.
2. **Given** a log `response` that contains an `Authorization` header, **When** returned, **Then** that header value is replaced by `********` too.
3. **Given** an `Authorization` header written in a different letter case (for example `authorization:`), **When** returned, **Then** it is redacted the same way.
4. **Given** a log that contains the WhatsApp admin system-user token anywhere, **When** returned, **Then** the token is redacted, as it is today when channel logs are displayed.
5. **Given** an anonymous org and a caller without permission to break anonymity, **When** a qualifying message's logs are returned, **Then** the contact URN is masked in `url`, `request`, and `response` the same way the channel log screens mask it. When nothing can be masked safely, the whole value is replaced by the mask.
6. **Given** two orgs, each with failed messages and error logs, **When** org A calls the endpoint with `error_logs=true`, **Then** only org A's messages and their logs are returned. No input parameter can select logs that don't belong to a message in org A's result page.

---

### User Story 3 - Existing integrations are unaffected and pay no extra cost (Priority: P1)

Current integrations keep calling the Messages API without the new parameter. They must see the same response as before, plus `failed_reason`, with no slowdown.

**Why this priority**: The endpoint is public and widely used. A breaking change or a performance regression on the default path would hurt every customer, not only the one asking for the feature.

**Independent Test**: Run the existing Messages API tests unchanged except for the new `failed_reason` field. Check that requests without the parameter, or with `error_logs=false`, run the same number of database queries as before.

**Acceptance Scenarios**:

1. **Given** any request without `error_logs`, **When** the response is returned, **Then** no message contains an `error_logs` key, and all other fields, filters, ordering, and pagination behave as before.
2. **Given** `error_logs=false`, **When** the response is returned, **Then** it is identical to the request without the parameter.
3. **Given** an unrecognized value such as `error_logs=abc`, **When** the request is made, **Then** it is treated as `false` and does not fail, following how other boolean parameters of this API behave.
4. **Given** the parameter is absent or false, **When** the request runs, **Then** no channel log lookup is made.
5. **Given** `error_logs=true` and pages of different sizes, **When** the request runs, **Then** the number of database lookups is the same regardless of how many messages are on the page.

---

### User Story 4 - Know why a message failed before reaching the provider (Priority: P2)

An integrator sees a failed message with no logs. The `failed_reason` field tells them whether the platform itself stopped the message, for example no compatible channel, a suspended account, or a message that sat in the queue too long. This field is present on every request and never expires.

**Why this priority**: Internal failures are less frequent than provider failures, but without this field they are indistinguishable from expired logs.

**Independent Test**: Create messages with each internal failure reason and with none. List them with and without `error_logs` and check `failed_reason`.

**Acceptance Scenarios**:

1. **Given** messages with each internal failure reason, **When** listed, **Then** `failed_reason` is `"suspended"`, `"looping"`, `"error_limit"`, `"too_old"`, or `"no_destination"` respectively.
2. **Given** a message without an internal failure reason, **When** listed, **Then** `failed_reason` is `null`.
3. **Given** a message that failed with `no_destination`, **When** listed with `error_logs=true`, **Then** it has `error_logs: []` and `failed_reason: "no_destination"`.
4. **Given** a message whose failure is older than the retention window, **When** listed, **Then** `failed_reason` still has its value, because it is stored on the message and doesn't expire.

---

### Edge Cases

- **Partially trimmed history**: when older logs of a message were trimmed and newer ones remain, only the remaining logs are returned. The inclusion rule is evaluated on the remaining logs only.
- **Status webhook spooled by Courier**: when Courier couldn't write the status to the database and spooled it, the resulting log isn't linked to the message, so it can't be returned. This is accepted, since the log is unreachable through the message.
- **Webhook carrying statuses of several messages**: Courier stores the full webhook body in the log of each message it updated, so one message's log may contain other contacts' status entries from the same channel. They belong to the same org. In anonymous orgs only the current message's contact is masked, which is the same behavior as the channel log screens. This is accepted and recorded in Assumptions.
- **Incoming messages**: the parameter applies to every message in the result. Incoming messages normally have only non-error "Message Received" logs, so they get `error_logs: []`.
- **Errored, retrying messages**: an `errored` message qualifies by status, so its logs are returned and the integrator can see the retry history. This applies even when no log is marked as error.
- **Failed status but only success logs**: a `failed` message whose only remaining log is a successful send (for example when the status log was spooled and not linked) still returns that send log. It shows the provider accepted the message, even though the failure detail isn't available.
- **Missing values in a log**: `response_status` and `elapsed_ms` are `null` when not recorded, for example on a connection error before any HTTP response.
- **Same timestamp**: logs of one message with the same `created_on` keep a stable order, with the most recently recorded first.
- **Large bodies**: `request` and `response` are returned as stored. Courier already replaces non-text bodies with a placeholder.
- **Parameter letter case**: `error_logs=TRUE` and `error_logs=True` are treated as true.
- **Combined with other filters**: `error_logs` can be combined with any existing filter (`broadcast`, `contact`, `folder`, `id`, `before`, `after`, …) and doesn't change which messages are returned.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every message returned by the Messages API MUST include `failed_reason`: `"suspended"`, `"looping"`, `"error_limit"`, `"too_old"`, `"no_destination"`, or `null`, mapped from the message's stored internal failure reason (S, L, E, O, D, or none).
- **FR-002**: The Messages API MUST accept an optional query parameter `error_logs`. Values `true`/`false` are documented, the default is `false`, and parsing MUST follow the existing boolean parameters of this API (for example `geometry` on boundaries): recognized true values turn it on, and anything else, including invalid values, turns it off without an error.
- **FR-003**: When `error_logs` is off, the response MUST NOT contain an `error_logs` key on any message, and the request MUST NOT look up channel logs.
- **FR-004**: When `error_logs` is on, every message in the response MUST contain an `error_logs` key whose value is a list (possibly empty).
- **FR-005**: For a message that meets the inclusion rule (FR-006), `error_logs` MUST contain all of that message's channel logs, successful and failed, ordered newest first. Logs with the same timestamp are ordered most recently recorded first. For any other message, `error_logs` MUST be `[]`.
- **FR-006**: A message meets the inclusion rule when it has at least one channel log marked as error, **or** its status is `failed` or `errored`. The status condition is needed because Courier saves asynchronous provider failures (status webhooks) with `is_error=false` (see Clarifications). Each returned item keeps its stored `is_error` value. The API MUST NOT reinterpret it or parse provider payloads.
- **FR-007**: Each item in `error_logs` MUST expose exactly: `created_on` (UTC datetime), `description`, `is_error`, `method`, `url`, `request`, `response`, `response_status`, and `elapsed_ms` (call duration in milliseconds, or `null`).
- **FR-008**: The value of every `Authorization` header (header name matched case-insensitively) MUST be replaced by `********` in both `request` and `response` of every returned item.
- **FR-009**: Returned `url`, `request`, and `response` MUST keep the redaction channel logs already apply when displayed: the WhatsApp admin system-user token is redacted, and for anonymous orgs the contact URN is masked unless the API user has permission to break anonymity, falling back to full masking when no safe partial masking is possible.
- **FR-010**: Channel logs MUST only be returned for messages in the current response page, which are already restricted to the caller's org. No request input may select channel logs directly.
- **FR-011**: When `error_logs` is on, resolving the logs for a page MUST take a fixed number of database lookups, independent of the number of messages on the page. When it is off, no lookup beyond today's MUST be made.
- **FR-012**: The page size rules MUST NOT change when `error_logs` is on: the default stays 100 and the maximum stays 1000. The documentation MUST recommend smaller pages with `limit` when `error_logs=true`.
- **FR-013**: The endpoint documentation (the endpoint description and the API explorer parameters) MUST describe the `error_logs` parameter, the `failed_reason` field and its values, the inclusion rule, and that logs are only available within the channel log retention window.
- **FR-014**: The message archive format MUST NOT change. Neither `error_logs` nor `failed_reason` is added. Rationale: archives are written by rp-archiver, which doesn't write `failed_reason`, and the Flows archive representation mirrors that format. Adding the field only in Flows would make the two sources inconsistent. Changing it means a coordinated rp-archiver change, which is out of scope.
- **FR-015**: Channel log retention MUST NOT change. Logs are available for the configured channel log retention period, after which `error_logs` comes back empty for the affected messages. The retention value published to customers MUST match the effective production value of `RETENTION_PERIODS_CHANNELLOG`. The code default is 48 hours, and the customer document currently says 72 hours. Confirming the production value and updating the document to match is a release precondition. Production configuration doesn't change.
- **FR-016**: All existing fields, filters, exclusive-parameter rules, ordering, pagination, and throttling of the Messages API MUST behave exactly as before.
- **FR-017**: The customer document `temba/api/v2/messages_channel_logs.md` (and its PDF) MUST be updated before release to match the final decisions of this spec:
  - Section 1 and section 4 describe the inclusion rule: at least one error log, or status `failed`/`errored`.
  - Example 2.2 shows the status log with description `"Status Updated"`, `is_error: false`, and a `response` with the body only.
  - Section 3 explains that, for asynchronous failures, the provider error is in the `request` of the status log even though it isn't flagged as error.
  - Every mention of "3 days (72 hours)" uses the confirmed production retention value.
- **FR-018**: The change MUST be recorded in `WENI-CHANGELOG.md` as a `feat` entry, noting the new field, the new opt-in parameter, and the redaction behavior.

### Load

- **Peak load**: the Messages API is throttled at 2,500 requests per hour per org (`v2.messages`). The design must hold up when one org sends all of its 2,500 requests per hour with `error_logs=true`, at page sizes up to the maximum of 1000, while several orgs do the same at once. In a broadcast where most messages failed, nearly every message on a page qualifies, each with several logs. That is the worst case to size for.

### Key Entities

- **Message**: an incoming or outgoing message visible through the API. It has a status, an optional internal failure reason (stored, never expires), and zero or more channel logs.
- **Channel log**: a record of one HTTP exchange between the platform and a channel provider: an outgoing send call, or an incoming webhook such as a status update. It has a description, an error flag, method, URL, raw request, raw response, response status, duration, and creation time. It belongs to a channel, optionally to a message, and is deleted after the retention period.
- **Failure reason**: the internal reason a message failed before or outside the provider exchange. It is one of five codes, exposed as stable lowercase strings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For failed messages queried within the retention window, 100% of those rejected by the provider at send time, and 100% of those reported as failed later by the provider, return the provider error code in `error_logs`.
- **SC-002**: Every existing Messages API test passes with only the addition of `failed_reason` to expected responses. No other change to existing response shapes.
- **SC-003**: Requests without `error_logs` run the same number of database queries as before the change, verified by tests.
- **SC-004**: Requests with `error_logs=true` run a constant number of database queries regardless of page size, verified by tests with at least two different page sizes.
- **SC-005**: Zero occurrences of `Authorization` header values or the system-user token in any `error_logs` item, verified by tests that seed them in both request and response.
- **SC-006**: With `error_logs=true`, a page of 100 messages, all of them qualifying, is returned in under 2 seconds at the 95th percentile under the declared peak load. A page of 1000 completes within the platform's request timeout.
- **SC-007**: The customer can identify the failure reason of a broadcast batch queried within the retention window without opening a support request.

## Test Strategy

Each acceptance criterion in the origin section maps to at least one test in `temba/api/v2/tests.py` (or the test module used by `MessagesEndpoint`), built on `TembaTest`. Each test exercises the full request through the endpoint (Principle XIV), and isolated tests of the log service cover edge variations.

| Origin criterion | Tests |
|---|---|
| 1. `failed_reason` | One message per code (S, L, E, O, D) plus none; present with and without `error_logs`. |
| 2. Default path unchanged | Parameter absent, `false`, and invalid (`abc`): no `error_logs` key, same query count as the baseline. |
| 3. Inclusion rule and ordering | Delivered message with only success logs → `[]`; one error among success logs → all logs; no logs → `[]`; `failed` and `errored` messages with only success logs → all logs; `failed` with no logs → `[]`; newest first, with stable tie-break. |
| 4. Send-time provider failure | Error send log with a 132001 response body is returned with all fields. |
| 5. Asynchronous provider failure | Send log (200) plus a "Status Updated" log with `is_error=false` and `statuses[].errors[]` in the request, on a `failed` message → both returned, newest first, with `is_error` unchanged. |
| 6. Redaction | `Authorization` in request and response, mixed letter case; system-user token; anonymous org with and without break-anon permission. |
| 7. Org isolation | Two orgs with error logs; each sees only its own. |
| 8. No N+1 | `assertNumQueries` constant across page sizes with the parameter on. |

Also covered: `limit` up to 1000 still works with `error_logs=true`, and `elapsed_ms` and `response_status` are `null` when missing.

## Constraints Carried to Planning

These project rules were given with the request. They are recorded here so the plan honors them. They are constraints, not product behavior.

- The view only reads the parameter and delegates. Log fetching, the inclusion rule, ordering, and redaction live in a dedicated service or query layer under `temba/channels/` or `temba/msgs/`. The serializer only reads prepared data.
- Logs for a page are resolved in a bounded number of queries, only when the parameter is on. Messages that qualify by status are known from the page itself without a query. Then one query finds the remaining page messages with an error log, and one query fetches all logs for the qualifying IDs, newest first. The plan evaluates whether the existing foreign key index on the log's message reference is enough, or whether a partial index on error logs by message is needed.
- The parameter follows the existing `geometry` pattern on the boundaries endpoint (serializer context flag).

## Constitution Alignment

- **I. Version Control and Review**: Pull request from `feature/add-channellog-in-messages-endpoint`, gated by `.github/workflows/ci.yml`.
- **II. Security and Secrets**: No new secrets. `Authorization` header values are replaced with `********`. The WhatsApp admin system-user token and anonymous-org URN masking stay the ones channel logs already apply. Logs are loaded only for messages already on the caller's page.
- **III. Observability**: No new logging. Existing request logging and Sentry stay as they are.
- **IV. Versioned Contracts**: Additive fields on `GET /api/v2/messages.json`: `failed_reason` always, `error_logs` only when the parameter is on. Existing fields, filters, and the archive format stay unchanged. No migration.
- **V. Specification Traceability**: Engineering origin. Each acceptance criterion in the origin section maps to a test in Test Strategy.
- **VI. No Silent Divergence**: Not applicable. No product spec.
- **VII. Commit Messages**: Conventional Commits when the change is committed.
- **VIII. Changelog Maintenance**: `feat` entry in `WENI-CHANGELOG.md` (FR-018).
- **IX. Never Trust the Client**: `error_logs` is parsed with the existing boolean helper. Unrecognized values turn the parameter off and do not error. The workspace comes from the caller, not from a log id.
- **X. Fail Gracefully and Predictably**: No new error status. A trimmed or missing log returns an empty list and the request succeeds.
- **XI. Bounded Retry Over REST**: Not applicable. No outbound call.
- **XII. Scalability and Peak Load**: Stateless read. Logs for a page use a fixed number of queries, independent of page size. Peak load is declared above. The existing foreign key index on the log's message reference is enough; no partial index.
- **XIII. Diagnosable Errors**: Unexpected errors keep the existing Sentry path. No new personal data is logged.
- **XIV. Tests Exercise Flows**: Endpoint tests go through `GET /api/v2/messages.json`. The log service has isolated tests for redaction and ordering.
- **XV. Explicit Over Clever**: Failure-reason strings and the qualifying statuses are named constants in the service.
- **XVI. Contained Changes**: Messages endpoint, its serializer, one channel-log service, tests, the customer document, and the changelog. Courier, Mailroom, retention, and archives stay unchanged.
- **Cycle choice**: SDD Full is the default for a public contract change. Lite was chosen explicitly. The implementation follows this spec directly.

## Implementation Notes

- **Service**: `temba/channels/usecases/message_error_logs.py`. It maps `failed_reason`, decides which messages on the page qualify, loads their logs in bounded queries, orders newest first (`-created_on`, `-id`), and redacts.
- **View**: `MessagesEndpoint` reads `error_logs` with `str_to_bool` and, only when it is on, calls the service from `prepare_for_serialization`. The log query uses the same database alias as the page.
- **Serializer**: `MsgReadSerializer` reads `failed_reason` through the service mapping and reads `error_logs` from serializer context. When the parameter is off, `to_representation` drops the `error_logs` key.
- **Index**: `ChannelLog.msg` already has the foreign key index. No migration.
- **Retention**: `RETENTION_PERIODS["channellog"]` in this repository is `timedelta(days=3)` (72 hours), which matches the customer document. The "48 hours" note in the clarifications does not match this checkout. Retention is not changed. A production override of that setting, if one exists outside the repo, is still a release check before the document's 72 hours is treated as final.
- **Customer document**: `temba/api/v2/messages_channel_logs.md` is updated for the inclusion rule and example 2.2. The PDF is regenerated from that file when a converter is available.

## Assumptions

- The API user is the user that anonymous-org permission checks run against, the same way the channel log screens check the logged-in user.
- Meta usually sends one status per webhook. Mixed-message webhook bodies are rare, and showing them follows the existing channel log screen behavior (see Edge Cases).
- Courier and Mailroom stay unchanged: the feature only reads what Courier already stores.
- Retention and trimming of channel logs keep working as today through the existing trimming task.
- The documented values for `error_logs` are `true`/`false`. Other values the existing boolean parsing accepts (`1`, `yes`, `y`) also work but aren't advertised.

## Out of Scope

- Persisting the provider error on the message itself (metadata or a new column).
- Any change to Courier or Mailroom, including marking "failed" status logs as errors.
- Changing channel log retention.
- Changes to the `whatsapp_broadcasts` endpoints.
- Changes to the archive format (see FR-014).
