# Engineering Spec: Named WhatsApp template variables

**Feature Branch**: `008-named-template-variables`  
**Created**: 2026-09-10  
**Status**: Draft  
**Product spec**: `vtex-cx-engine-specs` / `specs/008-named-template-variables/spec.md`

This is the Flows engineering spec. Product requirements, binding decisions, and API contracts live in the product spec and MUST be followed. This document records the HOW inside Flows.

## Inheritance from Product Spec

- **URL / path**: `vtex-cx-engine-specs/specs/008-named-template-variables/spec.md`
- **Pinned commit**: `8bf459d755e6fbde522b67125da3e74e396e3f3a` (branch `008-named-template-variables-meta-parameter-format`)
- **Scope slice**: `engineering/flows` — template registry, read surfaces, parameter policy, broadcast write contract, per-recipient resolution, rejection report, and the three WhatsApp broadcast write entry points.
- **Inherited binding decisions**: BD-001–BD-020, applied only to the Flows slice.
- **Divergences**: none.

Out of this repository (must not be implemented here): template authoring and Graph API version (`weni-integrations-engine`), one-time fleet reconciliation (`weni-integrations-engine`), named substitution primitive (`goflow`), delivery evaluation (`mailroom`), and provider payload assembly (`courier`).

## User Scenarios & Testing *(mandatory)*

Covered by product spec journeys 1–5, restricted to the Flows slice. Engineering tests MUST exercise the shared `WhatsappBroadcastWriteSerializer` so public v2, internal Django, and internal FastAPI stay identical.

### User Story 1 - Registry records format and names from sync (Priority: P1)

A named template arriving from the provider is stored with `parameter_format=named` and per-translation `parameter_names`. A positional template (or a payload that omits format) is stored as positional. Read surfaces publish format and names. A status-only update that omits the new fields MUST NOT clear them.

**Why this priority**: Nothing else in Flows works until the registry carries the authoritative format and names.

**Independent Test**: Ingest a Meta payload with `parameter_format: "named"` and body `Olá {{nome}}, sua cota {{cota}} vence hoje`. Assert the template is named, names are `nome` and `cota`, the public and internal read surfaces publish them, and a second call that updates only status leaves format and names intact.

**Acceptance Scenarios**:

1. **Given** a provider template with `parameter_format: "named"` and named body placeholders, **When** Flows ingests it, **Then** `Template.parameter_format` is `named` and each translation stores its parameter names, not a zero variable count.
2. **Given** a provider template that omits `parameter_format`, **When** it is ingested, **Then** it is recorded as `positional`.
3. **Given** a named template, **When** it is read on the public or internal template surface, **Then** the response includes the format and the parameter names.
4. **Given** an existing named template, **When** a status-only update omits format and names, **Then** the stored format and names are unchanged.
5. **Given** a template whose header or footer contains any placeholder, **When** sync runs, **Then** it is skipped in both formats.

---

### User Story 2 - Dispatch a campaign with per-recipient named data (Priority: P1)

An integrator posts a WhatsApp broadcast for a named template with `named_variables` and/or `recipients[].variables`. Flows validates format match, channel capability (Cloud only: `WAC`/`WCD`), translation name agreement, and recipient uniqueness, then resolves values by name and queues only accepted URNs. Unused names are ignored. Binding never uses a positional index.

**Why this priority**: This is the customer's blocked motion and a complete slice once the registry exists.

**Independent Test**: Post one broadcast for two URNs with different named values against a named Cloud-channel template. Assert each accepted URN is queued with its own name-keyed set, unused names are dropped, and `msg.template` carries `parameter_format` plus `named_variables` / `recipient_variables` — never a positional index.

**Acceptance Scenarios**:

1. **Given** a named template on a Cloud channel, **When** a broadcast supplies per-recipient named values, **Then** accepted recipients are dispatched with their own values under those names.
2. **Given** extra names the template does not declare, **When** the request is submitted, **Then** they are ignored and the request is accepted.
3. **Given** positional `variables` on a named template, or named values on a positional template, or both shapes at once, **When** submitted, **Then** the request is rejected before any broadcast is created.
4. **Given** a named template on a non-Cloud channel, **When** a named broadcast is posted, **Then** it is rejected naming the channel and the template.
5. **Given** translations that disagree on parameter names, **When** a named dispatch is attempted, **Then** it is rejected identifying the disagreeing translation.
6. **Given** a repeated recipient URN, **When** submitted, **Then** the whole request is rejected.

---

### User Story 3 - Incomplete data follows the declared policy (Priority: P2)

Parameter policy is optional Weni-owned JSON keyed by provider name. Missing required values hold back only that recipient; a fully held-back batch is a contract error. Optional gaps use default, then filler. Contact-field fallback is organization-scoped. The response reports accepted/held-back counts and the offending parameter name, never the value.

**Independent Test**: Ten recipients, one required and one optional-with-default parameter; two missing required, three missing optional. Assert eight dispatched, defaults applied, two reported as held back by parameter name.

**Acceptance Scenarios**:

1. **Given** no policy, **When** a named template is dispatched, **Then** every parameter is required and the template is dispatchable without a declaration step.
2. **Given** an optional parameter with a default, **When** a recipient omits it, **Then** they are dispatched with that default.
3. **Given** every recipient missing a required parameter, **When** submitted, **Then** the request is `400` and no broadcast is created.
4. **Given** a partial hold-back, **When** the response is returned, **Then** it names accepted count, held-back count, URN, parameter, and reason — without echoing values.

---

### User Story 4 - Positional broadcasts stay identical (Priority: P3)

Requests that use `msg.template.variables` against a positional template MUST keep today's shape, validation, metadata, and latency envelope. Named fields MUST NOT appear on that path.

**Independent Test**: Existing WhatsApp broadcast tests remain green without expecting `named_variables`, `parameter_format`, or `recipients` on positional fixtures.

## Functional requirements (engineering)

See product spec FR-001–FR-054. Implementation notes for this slice:

- **FR-001 / FR-002 / BD-002**: Persist `Template.parameter_format` (`named` | `positional`, default `positional`). Never infer format from body text or request shape.
- **FR-006 / FR-007 / BD-003**: Persist `TemplateTranslation.parameter_names` as an ordered JSON list for display only. Resolution and queued metadata are name-keyed maps.
- **FR-008**: Public `TemplateReadSerializer` and internal template details expose format and names.
- **FR-015 / FR-016 / FR-019 / BD-015**: Sync in `temba/utils/whatsapp/tasks.py` reads `parameter_format` from the provider payload. `TemplateTranslation.get_or_create` updates format/names only when the caller passes them (non-`None`), so status-only callers cannot wipe named data.
- **FR-020 / FR-021**: Reconciliation is owned by Integrations. Flows only receives corrected payloads through the existing ingest path.
- **FR-024 / BD-004**: Named dispatch compares active translations' name lists; disagreement is a contract error.
- **FR-025**: Skip header/footer with any `{{...}}` placeholder, named or positional.
- **FR-026–FR-034 / BD-007 / BD-011 / BD-018**: `WhatsappBroadcastWriteSerializer` accepts `named_variables` and `recipients`; mutually exclusive with positional `variables`; per-recipient values are literals; batch-level values stay in metadata for mailroom expression evaluation.
- **FR-035–FR-043 / BD-005 / BD-006 / BD-009 / BD-010 / BD-017**: Use-case `named_template_broadcast` applies policy, hold-back, filler, and the all-held-back rejection.
- **FR-049 / BD-008**: Named templates only on channel types `WAC` and `WCD`.
- **FR-051 / FR-052 / BD-019**: Positional path omits named metadata. All three write entry points keep sharing this serializer.
- **FR-054 / BD-020**: Rejection report identifies URN + parameter name + reason. Do not log per-recipient values.

## Key entities

- `Template.parameter_format`, `Template.parameter_policies`
- `TemplateTranslation.parameter_names`
- Existing: `Broadcast` metadata blob (`msg.template`), `Channel` (`WAC`/`WCD`), `Contact` / `ContactField` for fallback

## Assumptions

- Mailroom and Courier consume `parameter_format`, `named_variables`, and `recipient_variables` from the queued `msg` blob; Flows does not assemble the Meta send payload.
- `weni-integrations-engine` remains the authoring and fleet-reconciliation owner.
- Default filler for an optional parameter with no default is a single space, matching the provider's non-empty text rule.
- Header/footer/button named parameters stay out of scope, matching the product spec.
