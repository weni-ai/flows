# Specification Quality Checklist: atualização do Django 3.2 para o 5.2 LTS em etapas

**Purpose**: Validate specification completeness and quality of the umbrella spec (no own `plan.md`; each stage has a child spec)
**Created**: 2026-11-27
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Content-quality items were judged as an engineering spec of a framework upgrade. The subject of the change is the framework and its dependencies, so naming Django, the packages and the affected files is the "what", not a leaked "how". Exact pinned versions, task breakdown and order of commits are left to `plan.md`. The "users" are Flows end users (no visible change), developers and the platform team.
- Success criteria SC-003 to SC-007 are stated as operational outcomes (error rate, latency, support tickets, maintenance window) and avoid naming tools.
- Clarification resolved on 2026-11-27: D-4, `django-hamlpy` on Django 5.2 is handled by a `weni-ai/django-hamlpy` fork that only relaxes the Django bound (FR-026). Vendoring and converting templates were rejected and recorded in D-4.
- Restructured on 2026-11-27 into an umbrella spec: it keeps the objective, decisions D-1 to D-4, stage gates and per-stage minimum requirements, and tracks stage status. Stage 0 is spec 025 (SDD Lite). `TimezoneParityTest` and the HAML compile test moved to stage 0. FR-001 relaxed to "one or more PRs per stage, never mixing stages". FR-019 now installs the warnings filter in settings, because the `-W` command-line option matches only full module names.
- Updated on 2026-11-27 for the team rule "one PR merged into main = one spec": FR-001 now requires one child spec per PR (several per stage), and stage 0 is split into specs 025 (protection tests), 026 (APIs removed in 4.0 and warnings filter), 027 (POST logout) and 028 (`csv_imports` removal). The stage table lists one row per child spec, and the changelog rule is one bullet per child spec with a visible change.
- Principle V: the spec opens with `## Origin Without Product Spec`, and every AC maps to a named test or CI gate.
- TODO(SPECKIT_PRESET): `Test Strategy` and `Constitution Alignment` were written by hand.
- Peak Load: declared as non-regression; numeric value pending before stage 1, same approach as spec 022.
- Evidence collected on 2026-11-27 at commit `9bb192176`: `poetry.lock` constraints, PyPI metadata of each blocking package, scan of `temba/` and of installed third-party packages for APIs removed in Django 4.0 to 5.1, and a diff of `smartmin` 3.1.0 against 5.2.5 (only `csv_imports` removed among modules used by Flows).
