# Engineering Specification: custom_data on WhatsApp Broadcasts (Flows slice)

**Repository**: weni-ai/flows — backend

**Feature Branch**: `014-wwc-custom-data`

**Created**: 2026-11-03

**Status**: Draft

**Suggested cycle**: SDD Full (`specify` → `plan` → `tasks` → `analyze` → `implement`). The change is a public API contract (Principle IV), coordinates with Courier and Mailroom, and is shared by three write entry points. Do not use SDD Lite.

## Origin Without Product Spec

- Product Spec: none
- Architecture doc: https://github.com/weni-ai/vtex-cx-experience-specs/blob/006-wwc-custom-data/arch-v1/specs/006-wwc-custom-data/architecture.md — pinned tag `006-wwc-custom-data/arch-v1` (immutable commit `1ebcd6346d46d269f6421d7f3c10344ebdda394f`)
- Contracts: same pin, directory `specs/006-wwc-custom-data/contracts/` (`openapi.flows.yaml`, `custom-data.schema.json`, `events/send-whatsapp-broadcast-task.schema.json`)
- Problem: callers of WhatsApp broadcasts cannot attach opaque structured data to `msg`. Downstream hops (Mailroom, Courier WWC, webchat-socket, webchat-service) are specified to deliver that object as `customData` to a custom webchat; Flows is the single validation boundary (AD-002) and must reject invalid values before any broadcast exists.
- Acceptance criteria (Flows slice of the architecture origin ACs; end-to-end delivery to `message:received` / `history:loaded` is owned by other repositories):
  - AC-1: A `POST` to any of the three write entry points with a valid `msg.custom_data` object creates a WhatsApp broadcast (`201`). The stored `Broadcast.metadata` contains that object under `custom_data`, unchanged (no key rename, no expression evaluation). The queued Mailroom task `send_whatsapp_broadcast` carries the same object as `msg.custom_data` because `temba/mailroom/queue.py` already sets `msg = broadcast.metadata` after popping `queue`.
  - AC-2: Omitting `custom_data`, or sending `custom_data: {}`, creates a broadcast whose stored metadata does not treat an empty object as a present value (`{}` is equivalent to absence). Existing fields of `msg` and of the request keep today's behavior.
  - AC-3: `custom_data` that is `null`, a non-object, larger than 16384 compact UTF-8 bytes, nested deeper than 32 levels, or that has a key starting with `$` or containing `.` at any nesting level is rejected with HTTP `400`. Errors are reported under the `msg` key with the exact example strings from `contracts/openapi.flows.yaml`. No `Broadcast` row is created.
  - AC-4: Validation does not depend on `channel` being present and does not filter by Weni Web Channel (WWC) or any other channel type (AD-003). A valid `custom_data` is accepted for WhatsApp Cloud, WWC, missing channel, and any other type.
  - AC-5: The same `WhatsappBroadcastWriteSerializer.validate_msg` is the only validation of `custom_data`. Public v2, internal Django, and FastAPI `/internal/whatsapp_broadcasts` MUST NOT duplicate the rules. `queue.py` MUST NOT change for this feature.
- Inherited binding decisions (architecture AD-001–AD-007, this slice implements AD-002 and the Flows half of AD-001 and AD-003; AD-004 is Mailroom and MUST NOT be implemented here; AD-005–AD-007 are Courier / socket / service):
  - AD-001: API and task field is `msg.custom_data`.
  - AD-002: single validation in Flows; limits and `{}` / `null` rules as above.
  - AD-003: passthrough for any channel.
  - AD-004: Mailroom does not evaluate expressions; Flows MUST NOT evaluate them either.
  - AD-005–AD-007: out of scope in this repository.
- Scope of this spec: the Flows row of the architecture Impact Map only.
- Divergences: none (no Product Spec; architecture is the origin of the "what").

## Clarifications

None. Limits, error text, empty-object semantics, channel policy, and the three write entry points are binding in the pinned architecture and OpenAPI examples.

## Scope in This Repository

**This repository implements**:

- Validation of `msg.custom_data` inside `WhatsappBroadcastWriteSerializer.validate_msg` (`temba/api/v2/serializers.py`), which already serves:
  - public `POST /api/v2/whatsapp_broadcasts.json`
  - internal Django `POST /api/v2/internals/whatsapp_broadcasts`
  - FastAPI `POST /fastapi/internal/whatsapp_broadcasts` (`temba/fastapi_app/broadcasts.py`, which instantiates the same write serializer)
- Persistence of a present, non-empty `custom_data` as part of `Broadcast.metadata` (`Broadcast.create` already sets `metadata = msg` for `BROADCAST_TYPE_WHATSAPP`).
- Named constants for the 16384-byte and 32-depth limits (Principle XV).
- Tests on all three write entry points (Principle XIV).
- A `WENI-CHANGELOG.md` entry (user-facing public API field).

**Out of scope here**:

- Mailroom copy to `extraMetadata` / `msgs_msg.metadata` and expression evaluation (AD-004).
- Courier WWC handler (`handlers/weniwebchat`) and last-part attachment of `custom_data` (AD-005).
- `weni-webchat-socket` and `webchat-service` (`customData`, history) (AD-006, AD-007).
- `send_msg` / goflow / other send APIs (architecture Risks: out of scope unless amended).
- Any change to `temba/mailroom/queue.py`. The existing `queue_broadcast` path for type `W` already publishes `msg` from `broadcast.metadata` after popping `queue`.

## Current State

- `temba/api/v2/serializers.py`, `WhatsappBroadcastWriteSerializer.validate_msg`: validates presence of text/attachments/template/action_type/carousel and a few typed keys. It does not inspect `custom_data`. Extra keys in `msg` are accepted and stored.
- `WhatsappBroadcastWriteSerializer.save`: copies `msg` into `Broadcast.create(..., msg=msg, broadcast_type=BROADCAST_TYPE_WHATSAPP)`.
- `temba/msgs/models.py`, `Broadcast.create`: for WhatsApp broadcasts, `metadata = msg`. Optional `queue` is then written onto that dict.
- `temba/mailroom/queue.py`, `queue_broadcast` for type `W`: pops `queue` from metadata, then `task["msg"] = broadcast.metadata`. No code change is required for `custom_data` to ride the existing task.
- Public endpoint: `temba/api/v2/views.py` / `urls.py` (`api.v2.whatsapp_broadcasts`). Tests: `temba/api/v2/tests.py` (`test_whatsapp_broadcasts`).
- Internal Django endpoint: `temba/api/v2/internals/broadcasts/views.py` (`InternalWhatsappBroadcastsEndpoint`) uses `WhatsappBroadcastWriteSerializer`. Idempotency hashes the whole body (`compute_body_hash`), so a different `custom_data` with a reused `Idempotency-Key` already returns 409. Tests: `temba/api/v2/internals/broadcasts/tests.py`.
- FastAPI: `temba/fastapi_app/broadcasts.py` `post_internal_whatsapp_broadcast` uses the same write serializer and returns `serializer.errors` as JSON `400`. Tests: `temba/fastapi_app/tests.py`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Attach opaque custom_data to a WhatsApp broadcast (Priority: P1)

An integrator (public API token) or an internal service (OIDC / project JWT) creates a WhatsApp-style broadcast and includes `msg.custom_data` as a JSON object (order id, coupon, tags, nested objects and arrays). Flows accepts the request, stores the object on the broadcast, and queues Mailroom with that object inside `msg`.

**Why this priority**: This is the Flows half of the architecture origin AC that a valid `custom_data` is not discarded at the first hop.

**Independent Test**: POST a valid body with `custom_data` on each of the three write entry points; assert `201`, `Broadcast.metadata["custom_data"]` equals the submitted object, and (with `queue_broadcast` mocked or inspected) the task `msg` still contains it after `queue` is popped.

**Acceptance Scenarios**:

1. **Given** an org with a contact URN, **When** `POST /api/v2/whatsapp_broadcasts.json` includes `msg.custom_data` matching the OpenAPI example, **Then** the response is `201` and `metadata.custom_data` equals the request object.
2. **Given** the same body (plus `project` as required), **When** posted to `/api/v2/internals/whatsapp_broadcasts` and to `/fastapi/internal/whatsapp_broadcasts`, **Then** both return `201` with the same stored `custom_data`.
3. **Given** a valid `custom_data` and no `channel`, or a non-WWC channel, **When** the broadcast is created, **Then** it succeeds (AD-003).

---

### User Story 2 - Reject invalid custom_data before creating a broadcast (Priority: P1)

The integrator sends `null`, a string/array/number, an object over 16384 compact UTF-8 bytes, nesting deeper than 32, or a forbidden key (`$foo` or `a.b`) at any level. Flows answers `400` under `msg` with the contract example strings and creates no broadcast.

**Why this priority**: Invalid values must never reach Mailroom; the architecture's Mongo / socket failure mode is why Flows is the only validator.

**Independent Test**: POST each invalid shape on all three entry points; assert `400`, exact `msg` error list, and `Broadcast` count unchanged.

**Acceptance Scenarios**:

1. **Given** `custom_data: null` or a non-object, **When** posted, **Then** `{"msg": ["custom_data must be an object"]}`.
2. **Given** compact UTF-8 serialization longer than 16384 bytes, **When** posted, **Then** `{"msg": ["custom_data must be at most 16384 bytes when serialized"]}`.
3. **Given** nesting deeper than 32 (top-level object is depth 1), **When** posted, **Then** `{"msg": ["custom_data must have at most 32 levels of nesting"]}`.
4. **Given** a key starting with `$` or containing `.` at any nesting level, **When** posted, **Then** `{"msg": ["custom_data keys must not start with '$' or contain '.'"]}`.

---

### User Story 3 - Absence and empty object stay compatible (Priority: P1)

Callers that never send `custom_data` keep today's success and error behavior. `{}` is stored as absence, not as a present empty object.

**Why this priority**: Backward compatible MINOR (architecture Compatibility).

**Independent Test**: Replay an existing successful broadcast fixture without `custom_data`; add `custom_data: {}` and assert the stored metadata has no present empty `custom_data`.

**Acceptance Scenarios**:

1. **Given** a valid broadcast body without `custom_data`, **When** posted, **Then** `201` and metadata has no `custom_data` key (or it is not a present empty object).
2. **Given** `custom_data: {}`, **When** posted, **Then** `201` and the empty object is not persisted as a present value.

---

### Edge Cases

- Compact size uses `json.dumps(..., separators=(',', ':'))` UTF-8 byte length, matching `custom-data.schema.json` `x-max-serialized-bytes` (no extra ASCII escaping requirement beyond that dump).
- Depth: each nested object or array adds 1; a 32-level object is accepted; 33 is rejected.
- Forbidden keys apply to every object in the tree, including keys inside nested objects and (if objects appear as array elements) those objects' keys. Array indices are not keys.
- Strings that look like `@contact.*` inside values are stored verbatim (AD-004; Flows does not evaluate).
- Internal idempotency: reusing `Idempotency-Key` with a different `custom_data` remains `409` (existing hash of the whole body). No new idempotency code.
- Existing `validate_msg` failures (missing text/attachments/template/action_type/carousel) are unchanged and still take precedence when those rules fail; `custom_data` rules apply when the rest of `msg` is otherwise acceptable, or may be reported together under `msg` if both fail. Prefer validating `custom_data` after the existing content check so today's missing-content error text is preserved when `custom_data` is also wrong.
- `queue` remains a metadata key added by `Broadcast.create`, not part of `custom_data`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `WhatsappBroadcastWriteSerializer.validate_msg` MUST accept `custom_data` only when it is a JSON object (Python `dict` after parse). `null` and any non-object MUST raise a validation error with the text `custom_data must be an object`.
- **FR-002**: A present object whose compact UTF-8 serialization exceeds 16384 bytes MUST raise `custom_data must be at most 16384 bytes when serialized`.
- **FR-003**: Nesting deeper than 32 levels MUST raise `custom_data must have at most 32 levels of nesting`.
- **FR-004**: Any object key at any nesting level that starts with `$` or contains `.` MUST raise `custom_data keys must not start with '$' or contain '.'`.
- **FR-005**: `{}` MUST be treated as absence: do not persist an empty object as a present `custom_data` value on `Broadcast.metadata`.
- **FR-006**: A valid non-empty object MUST be persisted unchanged on `Broadcast.metadata["custom_data"]`.
- **FR-007**: Validation MUST NOT require `channel` and MUST NOT inspect channel type (AD-003).
- **FR-008**: Flows MUST NOT evaluate expressions inside `custom_data` (AD-004).
- **FR-009**: Validation MUST live only in `validate_msg`. FastAPI and internal Django MUST keep using `WhatsappBroadcastWriteSerializer` without a second validator.
- **FR-010**: `temba/mailroom/queue.py` MUST remain unchanged. The task contract `send_whatsapp_broadcast` gains `msg.custom_data` only because metadata already is `msg`.
- **FR-011**: HTTP `400` bodies MUST place these errors under `msg` (DRF field errors), matching `openapi.flows.yaml` examples. No broadcast is created on `400`.
- **FR-012**: Public API MINOR: omitting the field MUST behave exactly as today.

### Key Entities

- **WhatsApp broadcast (`Broadcast` type `W`)**: existing entity; `metadata` is the stored `msg` document and is the Mailroom task `msg`.
- **`custom_data`**: optional opaque JSON object on `msg` / `metadata`, constrained by AD-002.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the invalid shapes listed in AC-3 return `400` with the contract strings on all three write entry points, with zero broadcasts created.
- **SC-002**: 100% of valid non-empty `custom_data` requests on all three entry points persist the object byte-for-byte equal to the parsed JSON object.
- **SC-003**: Existing broadcast tests without `custom_data` remain green; callers that omit the field are not broken.
- **SC-004**: Integrators can attach structured payload up to 16384 compact bytes without a second send API.

## Technical Approach

### Components Affected

| Component | Change | Why |
|-----------|--------|-----|
| `temba/api/v2/serializers.py` | modify `validate_msg` | Single boundary (AD-002, Principle IX). Normalize `{}` to absence before `save`. |
| `temba/api/v2/tests.py` | add cases | Public v2 flow tests. |
| `temba/api/v2/internals/broadcasts/tests.py` | add cases | Internal Django + idempotency with `custom_data`. |
| `temba/fastapi_app/tests.py` | add cases | FastAPI entry point shares the serializer. |
| `WENI-CHANGELOG.md` | add bullet | Public optional field. |
| `temba/mailroom/queue.py` | none | Explicit non-change. |

Constants (names to be fixed in plan): max serialized bytes `16384`, max depth `32`, matching schema `x-max-serialized-bytes` and `x-max-depth`.

### Flow

1. Request hits one of the three POST entry points.
2. `WhatsappBroadcastWriteSerializer` runs existing `validate_msg` rules, then `custom_data` rules.
3. On failure: DRF/FastAPI `400` with `msg: ["…"]`; `save` is not called.
4. On success: `save` → `Broadcast.create` stores `msg` as metadata (empty `custom_data` already removed).
5. `broadcast.send_async` → existing `queue_broadcast`: pop `queue`, task `msg` is remaining metadata including `custom_data` when present.

### Rejected Alternatives

- Duplicate FastAPI Pydantic validation: would drift from DRF (user instruction and AD-002).
- Filter WWC in Flows: contradicts AD-003.
- Change `queue.py` to copy `custom_data` explicitly: redundant and out of scope.
- Evaluate `@contact` in Flows: contradicts AD-004 (Mailroom, and even there evaluation is forbidden).

## Contracts

| Interface | Change | Version impact | Backward compatible |
|-----------|--------|----------------|---------------------|
| `POST /api/v2/whatsapp_broadcasts.json` | optional `msg.custom_data` | Flows MINOR | yes |
| `POST /api/v2/internals/whatsapp_broadcasts` | same body field; idempotency hash already includes it | Flows MINOR | yes |
| FastAPI `POST /fastapi/internal/whatsapp_broadcasts` | same serializer | Flows MINOR | yes |
| Mailroom task `send_whatsapp_broadcast` | `msg.custom_data` present when stored | additive; Mailroom versions required documented at release | yes for old Mailroom (drops unknown field) until Mailroom ships last per architecture Delivery Sequence |
| `temba/mailroom/queue.py` | unchanged | none | yes |

Pinned producer contract: `openapi.flows.yaml` @ tag `006-wwc-custom-data/arch-v1`. Error strings MUST match the `ValidationError` examples (`notAnObject`, `tooLarge`, `tooDeep`, `forbiddenKey`).

Courier / Mailroom versions: this Flows change MAY deploy before Mailroom (architecture step 3 then 4). Until Mailroom ships, valid values sit on `Broadcast.metadata` and are ignored by old Mailroom. Rollback of Flows after new Mailroom is unsafe per architecture (unvalidated `custom_data` would propagate); plan MUST record that constraint.

## Data Model and Migrations

No new model or migration. `Broadcast.metadata` is existing JSON. Previously deployed Flows already stores arbitrary `msg` keys; this change only restricts `custom_data` when present.

## Non-Functional Requirements

### Peak Load

- **Declared peak**: the current production peak of WhatsApp-broadcast creates on the three write entry points, plus at most 16384 extra bytes of JSON per request to parse and persist once on `Broadcast.metadata` (not once per recipient). Recipient fan-out remains Mailroom. No extra process state.
- **Statelessness**: validation is per request; persistence is PostgreSQL JSON on `Broadcast`.
- Storage growth of `msgs_msg.metadata` at 16 KB × recipients is a Mailroom/architecture risk (AD-003), not a Flows per-request fan-out.

### Observability

- Do not log `custom_data` contents (opaque integrator payload; treat as message body per architecture Risks).
- Existing API access logs (method, path, status) remain. Sentry on serializer failures follows current DRF behavior; do not attach the object as extra.

### Failure Handling

- Invalid `custom_data`: `400`, no retry, no broadcast (Principle XI: 4xx is not retried).
- Timeouts to Mailroom queue Redis: unchanged existing `send_async` path.
- Idempotency on internal POST: unchanged; `custom_data` participates in the body hash.

### Security and Authorization

- Trust boundary: request JSON is untrusted; validated in `validate_msg` (Principle IX).
- Authorization: unchanged (public org token; internal OIDC/JWT + org resolution).
- Forbidden `$` / `.` keys exist to keep later Mongo writes from 500ing; Flows enforces them even when the channel is not WWC.

## Test Strategy

Map every origin AC to tests on **all three** write entry points unless noted.

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-1 valid persist + task payload | Public: extend `APITest.test_whatsapp_broadcasts` (or a dedicated method next to it) with the OpenAPI `wwcWithCustomData` example (channel optional in a second case). Assert `201`, `Broadcast.objects.get(...).metadata["custom_data"]` equals the object. Mock or capture `queue_broadcast` / inspect queued task so `msg.custom_data` is present after `queue` would have been popped — without editing `queue.py`. Repeat via internal Django tests and FastAPI `post_internal_whatsapp_broadcast` tests. |
| AC-2 omit and `{}` | Three entry points: body without the key (existing success tests stay green). Body with `custom_data: {}` → `201` and metadata has no present empty `custom_data`. |
| AC-3 invalid → 400, no row | Three entry points each: `null`; `"x"`; `[]`; `1`; object over 16384 compact bytes; depth 33; key `$x`; nested key `a.b`; nested object inside an array with `.` in a key. Assert status `400`, `msg` list equals the matching OpenAPI example string, `Broadcast` count unchanged. |
| AC-4 any channel | Three entry points: valid `custom_data` with WAC channel, with WWC channel if fixtures exist, and with no `channel`. All `201`. |
| AC-5 single serializer / no queue.py change | FastAPI and internal tests fail validation with the same strings as public (proves shared serializer). Spec/plan gate: `git diff` for this feature MUST NOT include `temba/mailroom/queue.py`. Unit tests on `validate_msg` MAY cover depth/key helpers; they MUST NOT be the only coverage (Principle XIV). |
| Architecture AC (e2e customData on webchat) | Not tested in this repo. Covered by courier / socket / service engineering specs. |
| Internal 409 | Internal tests: `Idempotency-Key` reused with a different `custom_data` → `409` (existing helper; add one case). FastAPI has no idempotency header today; do not invent it. |

**Flow coverage**: at least one test per entry point from HTTP POST through `Broadcast` row (success) and one from POST to no row (failure).

**Gates**: `poetry run coverage run manage.py test temba.api.v2 temba.api.v2.internals.broadcasts temba.fastapi_app`, `./code_check.py`, green `.github/workflows/ci.yml`. No new `# pragma: no cover`.

## Rollout and Rollback

Follow architecture Delivery Sequence for this repo (step 3 of 4):

1. webchat-service and weni-webchat-socket (other repos).
2. courier (other repo).
3. **This Flows change** (validate and store).
4. mailroom (other repo) last.
5. Announce to integrators after step 4 (`WENI-CHANGELOG.md` can land with the Flows release; platform announcement waits for the last deploy).

**Rollback**: revert Flows only if Mailroom has already been reverted (or never deployed). Otherwise old Flows would accept arbitrary `msg.custom_data` and new Mailroom would copy it.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | PR to `main`, review + green `ci.yml`. | none |
| II. Security and Secrets | No new secrets or auth/crypto dependencies. | none |
| III. Observability | Do not log `custom_data`. Correlation remains `broadcast_id`. | none |
| IV. Versioned Contracts | Optional field, MINOR, OpenAPI pin, Mailroom/Courier versions at release. SDD Full required. | none |
| V. Specification Traceability | `## Origin Without Product Spec`; architecture pinned by tag `006-wwc-custom-data/arch-v1` (`1ebcd6346d46d269f6421d7f3c10344ebdda394f`). | none |
| VI. No Silent Divergence | N/A (no Product Spec). Architecture ADs inherited; no silent drop of AD-002/003. | none |
| VII. Commit Messages | Conventional Commits, ≤50 character descriptions. | none |
| VIII. Changelog Maintenance | `feat:` bullet in `WENI-CHANGELOG.md` for optional `msg.custom_data`. | none |
| IX. Never Trust the Client | Validate in `validate_msg` at the serializer boundary. | none |
| X. Fail Gracefully | `400` with DRF field errors; no stack traces to callers. | none |
| XI. Bounded Retry Over REST | 400 is not retried. Queue path unchanged. | none |
| XII. Scalability and Peak Load | Stateless validation; peak = current broadcast-create peak + 16 KB parse/store once per broadcast. | none |
| XIII. Diagnosable Errors | Existing request context; do not put payload in Sentry extras. | `send_default_pii=True` remains `TODO(SENTRY_PII)`. |
| XIV. Tests Exercise Flows | Three HTTP entry points, success and failure. | none |
| XV. Explicit Over Clever | Named constants for byte and depth limits. | none |
| XVI. Contained Changes | Serializer validation + tests + changelog only; no `queue.py`, no Mailroom, no other send APIs. | none |
| Backend Standards | `./code_check.py`; no new locale strings (API error English matches OpenAPI). | none |
| SDD Full | This spec; plan and tasks follow. | none |

## Implementation Decisions

- Shared `validate_msg` rather than per-view checks (AD-002).
- Strip `{}` in the serializer so `Broadcast.create` never sees a present empty object.
- Size measured on compact `json.dumps` of the already-parsed object (architecture + schema).
- Depth counting as in `custom-data.schema.json`: top-level object is 1.

## Assumptions

- The three write entry points remain the only Flows writers of WhatsApp-broadcast `msg`.
- JSON objects arrive as dicts after DRF/FastAPI parse; validation does not re-parse the raw body except via `json.dumps` for size.
- Tag `006-wwc-custom-data/arch-v1` on `vtex-cx-experience-specs` is the architecture pin (present at `1ebcd6346d46d269f6421d7f3c10344ebdda394f`).

## Open Questions

None.
