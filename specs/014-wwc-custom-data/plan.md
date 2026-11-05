# Implementation Plan: custom_data on WhatsApp Broadcasts (Flows slice)

**Branch**: `014-wwc-custom-data` | **Date**: 2026-11-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/014-wwc-custom-data/spec.md`

## Summary

Add **AD-002** validation for optional `msg.custom_data` on WhatsApp broadcasts in a single boundary (`WhatsappBroadcastWriteSerializer.validate_msg`), shared by public v2, internal Django, and FastAPI. Valid objects persist on `Broadcast.metadata` unchanged; `{}` is normalized to absence. Invalid shapes return **400** with OpenAPI-fixed strings under `msg` and create no broadcast. **`temba/mailroom/queue.py` is unchanged** — the existing `msg = broadcast.metadata` task path carries `custom_data` when present.

Architecture pin: `vtex-cx-experience-specs` tag `006-wwc-custom-data/arch-v1` (`1ebcd6346d46d269f6421d7f3c10344ebdda394f`).

## Technical Context

**Language/Version**: Python ≥3.10,<3.12 (CI 3.11) / Django ^3.2 / DRF / FastAPI (internal route)

**Primary Dependencies**: Existing `WhatsappBroadcastWriteSerializer`, `Broadcast.create`, Mailroom batch queue (read-only for this feature)

**Storage**: PostgreSQL — existing `msgs_broadcast.metadata` JSON (no migration)

**Testing**: `TembaTest` — `poetry run coverage run manage.py test temba.api.v2 temba.api.v2.internals.broadcasts temba.fastapi_app temba.msgs` (unit module if added)

**Target Platform**: Flows API v2 public + internals + FastAPI `/fastapi/internal/whatsapp_broadcasts`

**Project Type**: web-service

**Performance Goals**: Validation is O(size of `custom_data` tree) per request; at most one `json.dumps` for byte measurement. No change to recipient fan-out (Mailroom).

**Constraints**: Error text MUST match pinned `openapi.flows.yaml`; compact size = `json.dumps(..., separators=(',', ':'))` UTF-8 bytes; max depth 32 (root object depth 1); no channel-type filter; no expression evaluation; no `queue.py` edits

**Scale/Scope**: Three write entry points; peak = current WhatsApp-broadcast create rate + up to 16 KB JSON validated/stored once per broadcast (Principle XII)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Pre-design | Post-design |
|-----------|------------|-------------|
| I. Version Control and Review | PR + CI | unchanged |
| II. Security and Secrets | No new secrets/deps | unchanged |
| III. Observability | Do not log `custom_data` | unchanged |
| IV. Versioned Contracts | MINOR additive field; pin architecture OpenAPI | Local contract doc references pin; release notes Mailroom/Courier when shipping |
| V. Spec traceability | Origin without Product Spec + architecture tag | unchanged |
| VI. No Silent Divergence | N/A | unchanged |
| VII–VIII. Commits / Changelog | Conventional commits; WENI-CHANGELOG | unchanged |
| IX. Never Trust the Client | Validate at serializer; helpers pure | Helpers called only from `validate_msg` |
| X. Fail Gracefully | 400 DRF field errors | unchanged |
| XI. Bounded Retry | 400 not retried | unchanged |
| XII. Peak load | Declared in spec | unchanged |
| XIII. Diagnosable errors | No payload in Sentry extras | unchanged |
| XIV. Flow tests | Three HTTP entry points | quickstart lists commands |
| XV. Explicit constants | `CUSTOM_DATA_MAX_*` in dedicated module | see research.md |
| XVI. Contained scope | Serializer module + tests + changelog only | no queue.py |

**Gate result**: PASS. No violations; Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/014-wwc-custom-data/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/whatsapp-broadcast-custom-data.md
├── checklists/requirements.md
└── tasks.md                    # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
temba/msgs/custom_data.py          # NEW — limits, depth/key/size checks, normalize {}
temba/msgs/tests/test_custom_data.py   # NEW — unit tests for helpers (not sole coverage)
temba/api/v2/serializers.py      # validate_msg calls helpers; strip {} before return
temba/api/v2/tests.py              # public v2 POST cases
temba/api/v2/internals/broadcasts/tests.py
temba/fastapi_app/tests.py
WENI-CHANGELOG.md
```

**Structure Decision**: Pure validation helpers live under `temba/msgs/` next to `Broadcast.metadata` semantics (same pattern as broadcast payload concerns). The serializer stays the HTTP boundary and maps helper failures to DRF `ValidationError` strings required by the contract.

## Complexity Tracking

> No constitution violations.
