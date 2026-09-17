<!--
  SYNC IMPACT REPORT
  ==================
  Version change: 0.0.0 → 1.0.0 (Initial adoption)
  Modified principles:
    - Added I. Django/Temba Channel Type Conventions
    - Added II. API & Integration Contract Discipline
    - Added III. Secrets, Security & Least Privilege
    - Added IV. Test-First Quality Gates
    - Added V. Observability & Operational Resilience
    - Added VI. Fidelity to the Product Spec
    - Added VII. Release & Migrations Alignment
  Added sections:
    - Engineering Standards
    - Delivery Workflow
    - Governance
  Removed sections: None
  Templates requiring updates:
    - .specify/templates/plan-template.md ✅ verified (Constitution Check present)
    - .specify/templates/spec-template.md ✅ verified
    - .specify/templates/tasks-template.md ✅ verified
  Follow-up TODOs: None
-->

# Flows Constitution

## Core Principles

### I. Django/Temba Channel Type Conventions

New channels MUST follow the established RapidPro/Temba channel type
pattern. Rationale: Flows is a fork of RapidPro; diverging from channel
type structure breaks Courier integration, the flow editor, and Mailroom.

- New channel types MUST live under `temba/channels/types/<channel_name>/`
  with at minimum `type.py`, `views.py`, `tests.py`, and `__init__.py`.
- Channel type classes MUST extend the appropriate base from existing
  types and register consistently with Courier channel type codes.
- Model or schema changes MUST include Django migrations in the same
  change set.
- Business logic MUST stay in type modules or dedicated use-case layers;
  views MUST remain thin.
- UI copy and user-facing strings MUST follow the VTEX Content Guide.

### II. API & Integration Contract Discipline

Inbound and outbound integration behavior MUST be deterministic from the
API contract, channel configuration, and approved external payloads.
Rationale: Flows sits between Courier, Mailroom, and Nexus; ambiguous
contracts cause cross-service failures.

- API views MUST validate input at the boundary before delegating to
  use cases or models.
- REST and internal API changes MUST be documented in the Engineering Spec
  and covered by tests.
- URN schemes and channel identifiers MUST stay consistent with Courier
  and the Product Spec (e.g., `tel:` for PSTN telephony).
- External service calls MUST use explicit timeouts and handle failures
  without leaking internal state.

### III. Secrets, Security & Least Privilege

Sensitive data MUST be protected across code, logs, and configuration.
Rationale: Flows stores channel credentials, org data, and contact
identifiers.

- Secrets MUST never be hardcoded, committed, or written to logs.
- Channel credentials MUST flow through Temba channel config mechanisms.
- Permission checks MUST be enforced on API endpoints that expose or
  mutate channel configuration.
- New dependencies affecting authentication or cryptography MUST be
  documented in the plan.

### IV. Test-First Quality Gates

Every behavior change MUST be backed by automated tests before review.
Rationale: Flows has broad regression surface across channels, flows, and
APIs.

- New behavior MUST include tests that fail before implementation and pass
  afterward.
- Channel type tests MUST use `TembaTest` (or approved test base) and
  follow patterns in neighboring channel types (e.g.,
  `temba/channels/types/weniwebchat/tests.py`).
- API changes MUST include view and use-case tests where applicable.
- CI (`pytest`) MUST pass locally before code review and before merge.
- Bug fixes MUST include a regression test whenever technically feasible.

### V. Observability & Operational Resilience

Production behavior MUST be diagnosable from logs and explicit failure
paths. Rationale: Flows orchestrates conversational automation; silent
failures degrade agent and human-agent experiences.

- Logs MUST include enough context to trace the operation (org, channel,
  request type) but MUST exclude secrets and unnecessary personal data.
- Error responses MUST be actionable for API consumers without exposing
  stack traces or internal details.
- Background tasks and async paths MUST handle retries and idempotency
  where the Product Spec requires it.

### VI. Fidelity to the Product Spec

Engineering work MUST inherit and MUST NOT contradict the ratified Product
Spec from `vtex-cx-engine-specs`. Rationale: Flows implements channel
configuration and agent pipeline integration defined at the product layer.

- Every Engineering Spec MUST open with an **Inheritance from Product Spec**
  section: URL, pinned commit/tag, inherited binding decisions, scope slice,
  and divergences (or none).
- Binding decisions from the Product Spec MUST be implemented verbatim.
- Any need to diverge MUST be raised as an amendment in
  `vtex-cx-engine-specs` before code encodes the change.
- The Product Spec defines *what*; this repository owns *how* to build it.

### VII. Release & Migrations Alignment

Application changes MUST ship in a way that preserves the Flows release
train and database compatibility. Rationale: Flows is versioned with
Courier, Mailroom, and related components.

- Database migrations MUST be backward-compatible within the release cycle
  unless a coordinated MAJOR upgrade is planned.
- Release-impacting changes MUST document required Courier/Mailroom
  version alignment.
- Breaking API or channel configuration changes MUST be called out in the
  plan and pull request notes.

## Engineering Standards

- Python code MUST follow existing project formatting and lint conventions.
- New channel types MUST mirror the structure and test coverage of a
  comparable existing type in `temba/channels/types/`.
- Prefer extending existing abstractions over introducing parallel patterns.
- Locale strings for new UI MUST be added to all required locale files
  when user-facing copy is introduced.

## Delivery Workflow

- Specs MUST capture user scenarios, edge cases, functional requirements,
  non-functional requirements, and measurable success criteria before
  planning.
- Plans MUST include a Constitution Check covering channel conventions,
  API contracts, security, tests, observability, Product Spec fidelity,
  and release/migration impact.
- Tasks MUST include mandatory test work, migrations, and locale updates
  when applicable.
- Pull requests MUST explain runtime impact and rollback considerations.

## Governance

This constitution is the authoritative engineering policy for the Flows
repository. All specifications, plans, tasks, and code reviews MUST enforce
it.

**Amendment Process**:
1. Propose changes in a pull request that updates
   `.specify/memory/constitution.md`.
2. Record the semantic version bump rationale in the Sync Impact Report.
3. Obtain approval from Flows maintainers before merge.

**Versioning Policy**:
- MAJOR: Remove or materially redefine a principle or governance rule.
- MINOR: Add a principle or section, or expand requirements.
- PATCH: Clarify wording or non-semantic guidance.

**Compliance Review**:
- Every plan MUST pass the Constitution Check before and after design.
- Every pull request MUST show how tests, migrations, and Product Spec
  fidelity were addressed.
- Reviewers MUST reject changes that bypass required tests or binding
  decisions.

**Version**: 1.0.0 | **Ratified**: 2026-07-21 | **Last Amended**: 2026-07-21
