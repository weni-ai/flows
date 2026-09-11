# Research: Named WhatsApp template variables (Flows)

## Decision: Native Meta named format, not a Weni name-to-slot layer

- **Decision**: Record `parameter_format` and `parameter_names` from the provider. Bind values by name at every hop. Do not compute a positional index.
- **Rationale**: Product spec BD-001/BD-003. The 2026-08-28 slot-binding design emulated a capability Meta already offers and is the source of cross-parameter mix-ups.
- **Alternatives considered**: Weni-side labels bound to `{{1}}`/`{{2}}` — withdrawn by the 2026-09-03 product revision.

## Decision: Format is stored data, never inferred

- **Decision**: `normalize_parameter_format` treats only the explicit string `named` as named; anything else (missing, empty, unknown) is `positional`.
- **Rationale**: BD-002 / FR-002 / FR-004. Body text is not a reliable classifier.
- **Alternatives considered**: Detect named vs positional from `{{nome}}` vs `{{1}}` in the body — forbidden by the product spec.

## Decision: Parameter names come from the provider payload when format is named

- **Decision**: When format is `named`, derive names from `example.body_text_named_params` first, then from named placeholders in the body text. Do not run the positional `{{N}}` max-index extractor on named templates.
- **Rationale**: FR-016. Today's positional regex yields 0 for `{{nome}}`, which is the active defect.
- **Alternatives considered**: Require Integrations to always send an explicit name list — still do that when present; Flows must not record zero names for a named body if the payload already contains them.

## Decision: `get_or_create` only writes format/names when the caller passes them

- **Decision**: `parameter_format=None` / `parameter_names=None` means "leave existing values". Passing a value updates.
- **Rationale**: BD-015 / FR-019. Status-only callers historically rebuild without examples; wiping names would restore the silent-breakage state.
- **Alternatives considered**: Always overwrite with empty defaults — rejected.

## Decision: Named dispatch is Cloud-only (`WAC`, `WCD`)

- **Decision**: Reject named templates on any other channel type at the write contract. No positional downgrade.
- **Rationale**: BD-008 / FR-049. On-prem/360dialog has no `parameter_name` field.
- **Alternatives considered**: Emit positional parameters for named templates — silent data-exposure risk.

## Decision: Policy is optional JSON on `Template`

- **Decision**: `parameter_policies` keyed by provider name: `{required, default, contact_field}`. Absent policy ⇒ every parameter required.
- **Rationale**: BD-005 / BD-006 / FR-037. Meta has no optional parameters; this overlay must not gate dispatch.
- **Alternatives considered**: Separate `ParameterPolicy` table — rejected as overkill for a name-keyed overlay; JSON matches the broadcast metadata style already used.

## Decision: Resolution order and hold-back live in Flows, expression eval stays in Mailroom

- **Decision**: Flows resolves per-recipient literals, batch-level presence, contact-field fallback, default, required/optional. Batch-level expression strings are passed through in `named_variables` for Mailroom to evaluate. Per-recipient values are never evaluated here.
- **Rationale**: BD-011. Flows already evaluates positional lists only after queueing in Mailroom; keep that split.
- **Alternatives considered**: Evaluate `@fields` in Flows before queueing — would duplicate goflow expression semantics and diverge from positional.

## Decision: Additive contract on the existing write serializer

- **Decision**: Add `recipients` and `msg.template.named_variables`. Keep `variables` for positional. Three entry points already share `WhatsappBroadcastWriteSerializer`.
- **Rationale**: FR-052 / BD-019 / 007 precedent.
- **Alternatives considered**: New endpoint for named broadcasts — would fork the contract and miss internals/FastAPI.

## Decision: Out of this repo

- Authoring, Graph API version bump, and one-time fleet reconciliation stay in `weni-integrations-engine`.
- Named placeholder substitution primitive stays in `goflow`.
- Per-message templating record and expression evaluation stay in `mailroom`.
- Meta payload `parameter_name` stays in `courier`.
