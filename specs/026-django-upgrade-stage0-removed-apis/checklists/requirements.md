# Specification Quality Checklist: etapa 0 do upgrade do Django, parte 2 — APIs removidas no Django 4.0 e filtro de avisos

**Purpose**: Validate specification completeness and quality before planning (SDD Full)
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

- Content-quality items were judged as an engineering spec of a framework upgrade: the removed Django APIs are the subject of the change, so naming them is the "what".
- Created on 2026-11-27 from the split of the former single stage-0 spec (025) into four specs, one per PR (024 FR-001). Requirements, decisions and research for the trade-offs and the warnings filter moved here unchanged in substance; FR-005 (no URL converters on non-literal regexes) was promoted from an edge case to a requirement, because the research found a public API route affected by it.
- Requirements of 024 covered here: FR-006 → FR-001; FR-019 → FR-004.
- Review fixes on 2026-11-27: the inventory now has a second command for `django.utils.timezone.utc` (no deprecation warning in 3.2, so the filter cannot catch it), restricted to files where `timezone` is `django.utils.timezone`; the `django.conf.urls` pattern now targets only the `url` name, since `include` stays valid; the PR checks include the FR-006 changelog bullet; research line and count corrections (`contacts/views.py:1213`, 189 files).
- `/speckit-plan` runs after 025 is merged; `research.md` carries the research already done and is refreshed by the plan.
- Principle V: opens with `## Origin Without Product Spec`; every AC maps to a named test, CI gate or PR check.
- TODO(SPECKIT_PRESET): `Test Strategy` and `Constitution Alignment` were written by hand.
- Peak Load is declared not applicable, with the reason.
