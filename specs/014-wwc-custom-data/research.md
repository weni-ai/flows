# Research: custom_data on WhatsApp broadcasts (Flows slice)

## Decision: Single module for limits and tree walks

- **Decision**: Add `temba/msgs/custom_data.py` with `CUSTOM_DATA_MAX_SERIALIZED_BYTES = 16384`, `CUSTOM_DATA_MAX_DEPTH = 32`, contract error message constants, and functions `validate_custom_data(obj) -> None` (raises `ValueError` with exact contract text) and `normalize_custom_data_in_msg(msg: dict) -> dict` (remove key when absent, `{}`, or after validation strip empty).
- **Rationale**: Principle XV (named limits); Principle IX (serializer thin); tree logic is testable without HTTP. Keeps `serializers.py` aligned with existing one-line field checks.
- **Alternatives considered**: Inline everything in `validate_msg` — harder to unit-test depth/key edge cases. New `usecases/` module — overkill for stateless JSON checks with no DB.

## Decision: Validation order inside `validate_msg`

- **Decision**: Run existing content rules first (text/attachments/template/action_type/carousel). If `custom_data` key is missing, skip custom_data rules. If present, run `validate_custom_data` then normalize `{}` out of the returned dict before other checks complete.
- **Rationale**: Spec edge case — preserve today's missing-content error when both content and `custom_data` are wrong; only run custom_data when key is present or when normalizing after successful parse.
- **Alternatives considered**: Validate `custom_data` before content check — could change error precedence for broken requests.

## Decision: Map helper errors to DRF under `msg`

- **Decision**: `validate_msg` catches `ValueError` from helper and re-raises `serializers.ValidationError(message)` (string form), producing `{"msg": ["<exact contract string>"]}` consistent with existing `validate_msg` errors.
- **Rationale**: OpenAPI `FieldErrors` examples; existing pattern for `Must provide either text...`.
- **Alternatives considered**: Nested `{"msg": {"custom_data": [...]}}` — contradicts pinned OpenAPI examples.

## Decision: Depth counting matches architecture schema

- **Decision**: Depth of a JSON value: `dict` or `list` at root = 1; each nested `dict` or `list` increments by 1; scalar leaves do not add depth beyond their container. Reject when depth > 32.
- **Rationale**: `custom-data.schema.json` `x-max-depth` description (top-level object is depth 1).
- **Alternatives considered**: Count only object nesting — arrays with nested objects would be under-counted.

## Decision: Forbidden keys at every object level

- **Decision**: When walking the tree for depth, also scan every `dict` key at every level for `$` prefix or `.` substring.
- **Rationale**: AD-002 / Mongo-safe keys; spec edge case for objects inside arrays.
- **Alternatives considered**: Top-level keys only — would allow `$` in nested integrator payloads and fail downstream.

## Decision: Size on compact JSON of parsed object

- **Decision**: After type and key/depth checks, `len(json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))`.
- **Rationale**: Architecture and schema `x-max-serialized-bytes`.
- **Alternatives considered**: Raw request body size — would diverge from stored object after parse/re-serialize.

## Decision: Prove task payload without changing `queue.py`

- **Decision**: In API tests, after successful POST, call `bcast.send_async()` and use existing `MailroomTest.assert_queued_batch_task` pattern (or mock `on_transaction_commit` to run synchronously) to assert task `msg.custom_data` equals submitted object and `queue` is top-level on task when set via metadata.
- **Rationale**: AC-1; FR-010; mailroom tests already document task shape.
- **Alternatives considered**: Only assert DB metadata — misses regression if `save` strips field before queue.

## Decision: Local contract doc, canonical OpenAPI in experience-specs

- **Decision**: `contracts/whatsapp-broadcast-custom-data.md` in this repo summarizes write shape and errors for implementers; canonical OpenAPI remains pinned in `vtex-cx-experience-specs` at `006-wwc-custom-data/arch-v1`.
- **Rationale**: Principle IV — cross-repo contract owner is experience-specs; engineering repo needs a stable pointer for tasks/review.
- **Alternatives considered**: Copy full OpenAPI into Flows — duplicate drift risk.

## Decision: Deploy / rollback (Flows step 3 of 4)

- **Decision**: Document in quickstart: ship after socket/service + courier; before Mailroom; do not roll back Flows alone if Mailroom with propagation is already live.
- **Rationale**: Architecture Delivery Sequence and rollback note.
- **Alternatives considered**: Feature flag in Flows — architecture explicitly uses deploy order instead.
