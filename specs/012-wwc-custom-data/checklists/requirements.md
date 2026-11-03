# Engineering Spec Quality Checklist: custom_data on WhatsApp Broadcasts (Flows slice)

**Purpose**: Validate the engineering spec before planning
**Created**: 2026-11-03
**Feature**: [spec.md](../spec.md)

## Origin

- [x] Product Spec is `none`, and the origin section matches the format required by the constitution, field for field
- [x] Problem and acceptance criteria are concrete and observable
- [x] Every acceptance criterion maps to a test in this repository (e2e webchat AC is explicitly owned by other repos)

## Technical Completeness

- [x] Scope in this repository is bounded, and what other repos own is named
- [x] Current state references real paths in this codebase
- [x] Technical approach names the components affected and the flow between them
- [x] Every changed public interface appears in Contracts with its SemVer impact
- [x] Backward compatibility or a deprecation path is stated for each breaking change (no breaking change)
- [x] Data model and migration reversibility are covered, or the feature persists nothing new as a schema
- [x] Peak load is declared as a peak, with its window
- [x] Observability states what is logged, with which context, and which correlation identifier
- [x] Failure handling states timeouts, retriable failures, bounds and idempotency
- [x] The trust boundary and the server-side authorization check are identified

## Verifiability

- [x] Every success or acceptance criterion maps to a test in this repository
- [x] Flow coverage covers complete use cases, not only isolated methods
- [x] Failure paths are covered, not only the success path
- [x] Rollout and rollback are described, and rollback is safe (Mailroom ordering recorded)

## Constitution

- [x] Every principle this feature touches has a row in Constitution Alignment
- [x] Every departure from a MUST is justified in the spec, not left to the code
- [x] No obligation of the constitution is left as an unfilled placeholder
- [x] Cycle is SDD Full (public contract + Courier/Mailroom coordination)

## Notes

- Validation passed on the first iteration.
- Core Spec Kit template does not include Origin / Test Strategy / Constitution Alignment (`TODO(SPECKIT_PRESET)`); those sections were added by hand.
- Architecture pin uses tag `006-wwc-custom-data/arch-v1` (commit `1ebcd6346d46d269f6421d7f3c10344ebdda394f`) even though the prompt expected the tag to be missing; the tag is present on `vtex-cx-experience-specs`.
- Checklist items from the generic Spec Kit template that forbid implementation details do not apply to this engineering spec (constitution and existing Flows specs require current state, contracts, and test mapping).
