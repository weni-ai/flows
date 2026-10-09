# Implementation Plan: Named WhatsApp template variables

**Branch**: `008-named-template-variables` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)

## Summary

Record Meta's native named parameter format on the Flows template registry, publish it on read surfaces, and accept name-keyed broadcast values (batch + per-recipient) with Weni-owned policy and hold-back — without changing the positional path. Binding is by name only. Named dispatch is Cloud API channels (`WAC`/`WCD`) only.

## Technical Context

**Language/Version**: Python 3.9+ / Django 3.2 (Temba/Flows)

**Primary Dependencies**: Django, DRF, FastAPI (internal route), existing WhatsApp template sync (`temba.utils.whatsapp.tasks`)

**Storage**: PostgreSQL — `templates_template.parameter_format`, `templates_template.parameter_policies` (JSON), `templates_templatetranslation.parameter_names` (JSON)

**Testing**: Django `TembaTest` (`python manage.py test`)

**Target Platform**: Flows API (public v2, internals, FastAPI) and WhatsApp template ingest

**Project Type**: web-service

**Performance Goals**: P95 ≤ 10s at 100 recipients, ≤ 30s at 1000 (product NFR-001/002); positional path with no measurable regression (NFR-005)

**Constraints**: No name-to-slot mapping; no named metadata on positional requests; named templates rejected off Cloud channels; no persistence of per-recipient values onto contacts

**Scale/Scope**: One Flows service; three write entry points sharing `WhatsappBroadcastWriteSerializer`; max 1000 recipients and 100 names per recipient

## Constitution Check

- I. Channel conventions: N/A (no new channel type). Schema change includes Django migration `0016_named_template_parameters` on `templates`.
- II. Contract: write serializer remains the single contract; positional validation preserved; named fields additive and mutually exclusive with `variables`.
- III. Secrets: no new secrets. Rejection report and logs name URN/parameter/reason, not per-recipient values.
- IV. Test-first: failing tests for named ingest, format mismatch, Cloud-only, hold-back, and unchanged positional path, then implementation.
- V. Observability: format mismatches, translation disagreement, unsupported channel, and held-back recipients attributable to org/template without echoing values.
- VI. Fidelity: inherits product spec BD-001–BD-020 and FR-001–FR-054 for the Flows slice; no divergences.
- VII. Migrations: backward-compatible additive columns with positional defaults. Named dispatch also requires goflow ≥ 1.20.5, mailroom ≥ 1.97.0, courier ≥ 1.67.0; until those layers carry names, a named template that is not ready MUST be rejected at the write contract (BD-016).

Post-design re-check: passed. No constitution violations.

## Project Structure

### Documentation (this feature)

```text
specs/008-named-template-variables/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/whatsapp-broadcast-named.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
temba/templates/parameter_format.py
temba/templates/models.py
temba/templates/migrations/0016_named_template_parameters.py
temba/utils/whatsapp/tasks.py
temba/utils/whatsapp/tests.py
temba/msgs/usecases/named_template_broadcast.py
temba/msgs/usecases/tests/test_named_template_broadcast.py
temba/api/v2/serializers.py
temba/api/v2/templates/serializers.py
WENI-CHANGELOG.md
```

**Structure Decision**: Extend the existing Temba templates + WhatsApp broadcast serializer. Policy and resolution live in a dedicated use-case module, matching `managed_trigger_group.py`.

## Complexity Tracking

> No constitution violations.
