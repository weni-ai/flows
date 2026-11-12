# Engineering Spec Quality Checklist: Serve Private Media to the Zendesk File Callback

**Purpose**: Validate the engineering spec before planning or implementation
**Created**: 2026-11-06
**Feature**: [spec.md](../spec.md)

## Origin

- [x] Product Spec is `none`, and the origin section matches the format required by the constitution, field for field
- [x] Problem and acceptance criteria are concrete and observable
- [x] Every acceptance criterion maps to a test in this repository (AC-7 is a manual rollout check, see Notes)

## Technical Completeness

- [x] Scope in this repository is bounded, and what other repos own is named
- [x] Current state references real paths in this codebase
- [x] Technical approach names the components affected and the flow between them
- [x] Every changed public interface appears in Contracts with its SemVer impact
- [x] Backward compatibility or a deprecation path is stated for each breaking change (no breaking change)
- [x] Data model and migration reversibility are covered, or the feature persists nothing
- [x] Peak load is declared as a peak, with its window (estimate; measured in rollout step 1)
- [x] Observability states what is logged, with which context, and which correlation identifier
- [x] Failure handling states timeouts, retriable failures, bounds and idempotency
- [x] The trust boundary and the server-side authorization check are identified

## Verifiability

- [x] Every success or acceptance criterion maps to a test in this repository
- [x] Flow coverage covers complete use cases, not only isolated methods
- [x] Failure paths are covered, not only the success path
- [x] Rollout and rollback are described, and rollback is safe

## Constitution

- [x] Every principle this feature touches has a row in Constitution Alignment
- [x] Every departure from a MUST is justified in the spec, not left to the code (XVII observe mode, manual test run)
- [x] No obligation of the constitution is left as an unfilled placeholder

## Notes

- Clarification 2026-11-06 resolved AC-4: validate `metadata` in observe mode now, block with `403` in a follow-up release.
- The code lives in `rapidpro-apps`, whose tests no CI runs; the spec makes the manual `manage.py test weni.s3` run a PR requirement.
- AC-7 needs a Zendesk account and the real bucket, so it is verified in rollout steps 3 and 4, not by an automated test.
- The peak load is an estimate because Loki returned `401`; rollout step 1 measures it before deploy.
