<!--
Sync Impact Report:
- Version change: 2.0.0 → 3.0.0
- Bump rationale: MAJOR. Principle V no longer requires every engineering spec to derive from a product spec, and the Constitution Check governance rule no longer assumes every change has a plan.
- Modified principles:
  - V. Specification Traceability: redefined to the new root text. An engineering spec either derives from a product spec (inheritance section) or originates in engineering (new `## Origin Without Product Spec` section). Either origin may follow the SDD Full or the SDD Lite cycle
  - VI. No Silent Divergence: now scoped to engineering specs derived from a product spec
- Added sections:
  - Specification-Driven Delivery (SDD Full and SDD Lite cycles, chosen by complexity, not by origin)
- Modified sections:
  - Governance / Compliance Review: Constitution Check runs on the plan in SDD Full and on the spec's Constitution Alignment in SDD Lite; pull requests show product-spec fidelity or the origin acceptance criteria
- Removed sections: none
- Follow-up TODOs:
  - TODO(SENTRY_PII): `temba/settings_common.py` initializes Sentry with `send_default_pii=True`, which conflicts with Observability and Diagnosable Errors. A later change MUST stop attaching personal data and MUST send only opaque identifiers. Out of scope for this constitution update.
  - TODO(SPECKIT_PRESET): the `vtex-cx-engineering` preset is not installed in this repository, so `/speckit.specify` still uses the core command and template, without the origin gate, the `## Origin Without Product Spec` section, or the `Test Strategy` and `Constitution Alignment` sections that SDD Lite relies on. Until then, those sections MUST be added to `spec.md` by hand. Install it with `specify preset add --dev <clone>/speckit/vtex-cx-engineering` in a separate change.

Provenance:
- Source: weni-ai/vtex-cx-engineering-constitutions (main @ 74ce306)
- Domains: backend
-->

# Flows Constitution

## Core Principles

### I. Version Control and Review

All code MUST enter `main` through a pull request. A merge MUST require at least one approved review and a green run of `.github/workflows/ci.yml`. Direct pushes to `main` MUST be blocked by platform branch protection.

**Rationale:** The policy is only real when the platform enforces it. Peer review and a protected `main` keep history auditable and stop unreviewed changes from reaching production.

### II. Security and Secrets

Secrets MUST never be committed to the repository. Secrets MUST be supplied by an external secrets manager or the runtime environment and injected where `temba/settings_common.py` and `temba/settings.py.prod` read configuration. Access MUST follow least privilege by default. Channel credentials MUST flow through Temba channel config, not through source or logs. Dependencies MUST be declared in `pyproject.toml` and locked in `poetry.lock`, MUST come only from trusted sources, and MUST be checked for known vulnerabilities. A new dependency that affects authentication or cryptography MUST be named in the engineering plan.

**Rationale:** Leaked credentials and untrusted dependencies are among the most common and most damaging breaches. Flows stores channel credentials, org data, and contact identifiers, so prevention is far cheaper than remediation.

### III. Observability

Logs MUST be structured and MUST never contain secrets or sensitive personal data. Errors MUST be traceable across Flows, Courier, Mailroom, and RabbitMQ consumers through a correlation or trace identifier. Log context MAY include opaque org, channel, and request-type identifiers.

**Rationale:** Structured, privacy-safe telemetry is what makes incidents diagnosable without creating a new data-exposure risk. Flows orchestrates conversational automation; a silent failure degrades both automated and human-agent flows.

### IV. Versioned Contracts

Any change to a public interface MUST be versioned with SemVer. In this repository that covers Django REST Framework endpoints under `temba/api`, the FastAPI surface in `temba/fastapi_app`, channel configuration consumed by Courier, and event payloads published or consumed by RabbitMQ consumers. Changes MUST be backward compatible or MUST ship with an announced deprecation path. Silent breaking changes MUST NOT be introduced. Django migrations MUST ship in the same change set as the model or schema change and MUST stay backward compatible within the release cycle unless a coordinated major upgrade is planned. A release-impacting change MUST document the required Courier and Mailroom versions, consistent with the release train in `README.md`.

**Rationale:** Courier, Mailroom, and other Weni platform consumers depend on stable contracts. Explicit versioning and deprecation give them a predictable path to adapt. Flows sits between those services; an ambiguous or silent break becomes a cross-service outage.

### V. Specification Traceability

An engineering spec either derives from a product spec or originates in engineering. Both are regular paths of the process; neither requires a justification, and either may follow the SDD Full or the SDD Lite cycle defined in Specification-Driven Delivery. Engineering specs live under `specs/NNN-<short-name>/spec.md`.

When the change has a product spec, the engineering spec MUST derive from exactly one approved product spec and MUST reference it through an immutable, pinned version (commit or tag). A mutable URL or ID alone MUST NOT be used. The product spec lives in `vtex-cx-engine-specs` and MUST exist and be tagged before its engineering spec is created. An engineering spec MUST NOT redefine the "what" it inherits: problem, scope, success criteria, and binding decisions belong to the product spec. A technical architecture document SHOULD be produced for non-trivial features; when it exists it MUST be linked from the engineering spec, also pinned by commit or tag, but its absence MUST NOT block the engineering spec.

An engineering spec derived from a product spec MUST open with an inheritance section in exactly this format:

```
## Inheritance from Product Spec
- Product Spec: <title> — <URL>
- Pinned version: <commit/tag>
- Architecture doc: <none | URL + commit/tag>
- Inherited binding decisions: <short list>
- Scope of this spec: <slice implemented by this repo>
- Divergences: <none | link to amendment>
```

Binding decisions from the product spec MUST be implemented verbatim. The product spec defines what; this repository owns how to build it.

An engineering spec without a product spec — a hotfix, a fix, or technical debt in Flows — states its own "what" and MUST open with an origin section in exactly this format:

```
## Origin Without Product Spec
- Product Spec: none
- Problem: <what is wrong or missing, in one or two sentences>
- Acceptance criteria: <observable outcomes that prove the change is done>
```

The problem and acceptance criteria of that section are what the change is verified against, and each acceptance criterion MUST map to a test in this repository.

**Rationale:** Traceability from intent to technical execution keeps decisions auditable and lets any change be traced back to the need that justified it. When the change is born in product, the product spec is that origin, and pinning its version guarantees that every team implements the same version of the feature. When the change is born in engineering, the engineering spec itself is the origin, and its problem and acceptance criteria are what the change is verified against. Keeping the architecture doc optional avoids blocking delivery on ceremony when the design is trivial. A fixed opening format for each path keeps the origin machine-checkable and uniform across repositories.

### VI. No Silent Divergence

When a technical need contradicts something inherited from the product spec — scope, success criteria, or a binding decision — the divergence MUST NOT be implemented silently in code. It MUST be raised as an amendment in `vtex-cx-engine-specs` and recorded in the `Divergences` field of the engineering spec's inheritance section, linking to that amendment. Once the amendment is approved and produces a new tag, the engineering spec's `Pinned version` MUST be updated to it. A technical difference that contradicts nothing inherited is not a divergence but an implementation decision, and MUST live in the engineering spec. This principle applies only to engineering specs derived from a product spec; a spec without one inherits nothing it could diverge from.

**Rationale:** In a federated model the product spec is the single source of truth. A silent code deviation makes intent and implementation drift apart with no audit trail.

### VII. Commit Messages

Commits MUST follow Conventional Commits: `<type>: <description>`. Allowed types are `feat`, `fix`, `docs`, `refactor`, `test`, and `chore`. The description MUST be imperative, specific, and no longer than 50 characters. Commits MUST be atomic: one logical change per commit.

**Rationale:** Conventional commits enable automated changelog generation and semantic versioning. Atomic commits simplify bisecting, reverting, and reviewing.

### VIII. Changelog Maintenance

Every user-facing change MUST be recorded in `WENI-CHANGELOG.md` under the version that ships it, before that version is released. Version bumps MUST follow SemVer and the Flows release train documented in `README.md`. A security-relevant change MUST be identifiable as such in the entry. Upstream RapidPro history in `CHANGELOG.md` MUST NOT be rewritten to record Weni-only changes.

Exception: this repository is a service, not a public library, and its consumers already read `WENI-CHANGELOG.md` as version headings (`3.x.y`) with bullets prefixed by a Conventional Commit type (`feat`, `fix`, `chore`). Keep a Changelog section headings (Added, Changed, Deprecated, Removed, Fixed, Security) are not used. The type prefix plus the description MUST still communicate the same categories, and a security change MUST say so in the bullet.

**Rationale:** A maintained changelog communicates impact to platform consumers and is the release note for this repository. The exception keeps that record in the file and shape the release process already uses, without dropping the obligation to list every user-facing change.

### IX. Never Trust the Client

Everything that reaches the server from outside — the web UI, a channel webhook, a third-party callback, or another API — MUST be treated as potentially malicious, incomplete, or incorrect until it is validated. Every external input MUST be validated for type, format, range, and business rules at the server boundary before use. That boundary is a Django REST Framework serializer, a FastAPI request model, or the equivalent parser on a webhook or consumer. Authorization MUST be enforced on the server for every request that reads or mutates org, channel, contact, or flow state, regardless of any check already performed by the client. Views MUST stay thin: validation happens at the boundary, and business logic lives in channel type modules or `temba/<app>/usecases/`.

**Rationale:** Clients run outside the server's control and can be inspected, modified, or bypassed. Validating at the boundary is what prevents injection, data corruption, and privilege escalation that client-side checks cannot stop.

### X. Fail Gracefully and Predictably

Calls to external dependencies MUST have explicit timeouts and MUST NOT block indefinitely. In this repository that includes Courier, Mailroom, channel provider APIs, Elasticsearch, Redis, and PostgreSQL. Failures MUST be handled explicitly and surfaced as consistent, well-defined error responses. Unhandled crashes, stack traces, and leaked internal details MUST NOT be returned to callers.

**Rationale:** Failure is a certainty. Handling it explicitly keeps a partial outage contained and observable instead of letting one dependency take down Flows or expose internals.

### XI. Bounded Retry Over REST

When data is propagated between services over a REST call — including calls from Flows to Courier, Mailroom, or an external channel API — a failure in that call MUST be retried rather than dropped. A retry MUST be attempted only when the failure could plausibly succeed on another attempt (connection error, request timeout, HTTP 5xx, or HTTP 429) and MUST NOT be attempted on a 4xx that reflects a defect in the request itself. A retry MUST only be applied to an operation that is idempotent or protected by a deduplication key; when the operation is neither, it MUST be made idempotent rather than left without retry. Every retry policy MUST define a maximum number of attempts and a backoff strategy. Unbounded retry MUST NOT be used. When the attempts are exhausted, the failure MUST be logged and MUST remain recoverable. It MUST NOT be silently discarded.

**Rationale:** Propagation between services fails for transient reasons far more often than for permanent ones. Bounds keep retry from amplifying an outage, and an observable exhausted case is what stops data from disappearing between two services that each believe they succeeded.

### XII. Scalability and Peak Load

Flows web and worker processes MUST be stateless so they can scale horizontally. State that outlives a single request MUST NOT be kept in process memory or on local disk. It MUST live in a shared store: PostgreSQL/PostGIS, Redis, or Elasticsearch. The peak load a change is expected to sustain MUST be declared in its engineering spec, stated as peak and not as average.

**Rationale:** Capacity is a design input. Sizing for average traffic fails exactly when demand matters most. Stateless processes are what make adding instances a valid answer to load.

### XIII. Diagnosable Errors

Every error reported to Sentry MUST carry enough context to be located and filtered without reproducing it: at minimum the project (org) identifier, the account identifier, the user identifier, and the correlation identifier of the request. Those identifiers MUST be opaque. Sensitive personal data — names, e-mail addresses, phone numbers, or government identifiers — MUST NOT be attached to an error report under any circumstance.

**Rationale:** An error without identifying context can be counted but not investigated. Opaque identifiers give the filter an investigation needs while keeping the report free of personal data.

### XIV. Tests Exercise Flows

Every flow MUST have at least one test covering the complete use case, from input to resulting effect. Tests that assert a single method in isolation are allowed and SHOULD be used for edge cases and input variations that are expensive to reach through the whole flow, but they MUST NOT be the only coverage a flow has. Every flow MUST cover its success path and its failure paths. An error path that no test exercises MUST NOT be considered covered.

Tests MUST use `TembaTest` (`temba/tests/base.py`) unless an existing neighboring test already uses another approved base. Channel type tests MUST follow the pattern of a comparable type, such as `temba/channels/types/weniwebchat/tests.py`. The local and CI command is `poetry run coverage run manage.py test`. The pull request gate is a green `.github/workflows/ci.yml` run (groups `api`, `channels`, `core`, and `others`) and a clean `./code_check.py`. A bug fix MUST include a regression test whenever technically feasible. New coverage exclusions (`# pragma: no cover` or equivalent) MUST NOT be added to hide an untested path.

**Rationale:** A suite made only of isolated method tests can be green while the composition of those methods is broken. Failure paths are the least exercised in development and the most expensive in production. The Django test runner and `code_check.py` are the gates this repository actually enforces.

### XV. Explicit Over Clever

What a piece of code does MUST be evident where it happens. Hidden side effects and implicit control flow MUST NOT be introduced to save lines. Any literal that carries meaning — a threshold, a limit, a timeout, a retry count — MUST be a named constant rather than an inline value. A literal that carries no meaning beyond its own value, such as an index of 0 or an increment of 1, is exempt. Comments MUST explain why a decision was made: the constraint, the trade-off, or the non-obvious reason. A comment that restates what the code already says is a signal that the code SHOULD be rewritten to say it.

**Rationale:** Code is read far more often than it is written. An unexplained literal is a decision nobody can review. Comments that stay on the why preserve the information the code cannot carry.

### XVI. Contained Changes

A change MUST be limited to the context it was asked to address. Refactoring, renaming, reformatting, or behaviour adjustments outside that context MUST NOT ride along; each belongs to its own change. This principle governs the scope of a change as a whole. The requirement that each commit be atomic governs how that change is divided internally, and a change that stays within scope MAY still span several commits.

**Rationale:** A change that reaches beyond its stated scope is a change nobody reviewed on purpose. It hides the intended fix inside unrelated edits and turns a revert into a choice between losing the fix and keeping an unrelated regression.

## Flows Backend Standards

These rules instantiate the principles above on the stack and layout of this repository.

- Runtime is Python `>=3.10,<3.12` (CI uses 3.11), Django `^3.2`, Django REST Framework, and FastAPI, managed with Poetry.
- Shared state lives in PostgreSQL/PostGIS, Redis, and Elasticsearch 7. Background work uses Celery. Cross-service events use RabbitMQ via `pika` in `temba/<app>/consumers/`.
- Application code lives under `temba/<app>/`. Use cases live under `temba/<app>/usecases/` when the app already uses that layer.
- A new channel type MUST live under `temba/channels/types/<channel_name>/` with at minimum `type.py`, `views.py`, `tests.py`, and `__init__.py`. The type class MUST extend the appropriate existing base and MUST register a Courier channel type code consistently with neighboring types.
- URN schemes and channel identifiers MUST stay consistent with Courier and the product spec.
- Python formatting MUST pass `./code_check.py`, which runs Black (`--line-length=119`), flake8, isort (`setup.cfg`), and checks for missing migrations.
- User-facing copy MUST follow the VTEX Content Guide. New locale strings MUST be added for the supported languages (EN source, ES, PT, and RO) in `locale/` when the change introduces them.
- Prefer extending an existing abstraction over introducing a parallel pattern.

## Specification-Driven Delivery

A change in this repository follows one of two cycles. Both start from an engineering spec written by `/speckit.specify`, with either origin from Principle V. The cycle MUST be chosen by the complexity of the change, not by its origin: a change with a product spec MAY follow SDD Lite, and a change without one MAY follow SDD Full.

- **SDD Full**: `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` → `/speckit.analyze` → `/speckit.implement`. `/speckit.clarify` and `/speckit.checklist` MAY be used between steps. The feature directory carries `spec.md`, `plan.md`, and `tasks.md`.
- **SDD Lite**: `/speckit.specify` → implementation directly from `spec.md`. `plan.md`, `tasks.md`, and `/speckit.analyze` are not produced. `/speckit.implement` reads `tasks.md` and therefore belongs to SDD Full only.

SDD Full SHOULD be used when the change adds or alters a channel type, changes a public contract listed in Principle IV, ships a migration, needs coordination with Courier or Mailroom, or spans more than one app under `temba/`. SDD Lite SHOULD be used for a hotfix, a contained fix, or technical debt that touches none of those.

SDD Lite reduces artifacts, not obligations. A Lite spec MUST still open with the section Principle V requires for its origin, MUST fill its Test Strategy and Constitution Alignment sections, and MUST declare the peak load whenever Principle XII applies. The pull request MUST pass the same gates as SDD Full: green `.github/workflows/ci.yml`, clean `./code_check.py`, flow tests, and a `WENI-CHANGELOG.md` entry for a user-facing change. When a Lite change turns out to touch any SDD Full trigger above, it SHOULD be promoted to SDD Full by running `/speckit.plan` on the same spec.

**Rationale:** Ceremony should match risk. A plan and a task breakdown pay for themselves on contract, schema, and cross-service work, and only add latency to a one-file fix. Keeping the spec and the gates mandatory in both cycles is what stops the lighter path from becoming a way around the constitution.

## Governance

This constitution is the authoritative engineering policy for the Flows repository. Specifications, plans, tasks, and code reviews MUST enforce it. It supersedes informal practice when they conflict. Root engineering policy prevails over a domain specialization; a domain rule specializes the root and MUST NOT contradict it. An exception MUST be written in the article that needs it, with the reason.

**Amendment Process**:

1. Propose the change in a pull request that updates `.specify/memory/constitution.md`.
2. Record the semantic version bump and the rationale in the Sync Impact Report.
3. Obtain approval from Flows maintainers before merge.

**Versioning Policy**:

- MAJOR: remove or materially redefine a principle or governance rule.
- MINOR: add a principle or section, or expand requirements.
- PATCH: clarify wording or non-semantic guidance.

**Compliance Review**:

- The Constitution Check MUST cover version control, secrets, observability, versioned contracts, spec origin (product-spec inheritance or origin without product spec), silent divergence when a product spec exists, commits, changelog, input validation, timeouts, bounded retry, statelessness and declared peak load, diagnosable errors, flow tests, explicit constants, contained scope, and channel layout when the change adds or alters a channel.
- In SDD Full, every plan MUST pass the Constitution Check before Phase 0 research and again after Phase 1 design.
- In SDD Lite, there is no plan: the Constitution Alignment section of `spec.md` is the Constitution Check and MUST be complete before implementation starts.
- `/speckit.analyze` MUST treat a conflict with a MUST in this constitution as CRITICAL.
- Every pull request MUST state the cycle it followed and show how tests, migrations, changelog, and either product-spec fidelity or the origin acceptance criteria were addressed.
- Reviewers MUST reject a change that bypasses required tests or a binding product decision.

**Version**: 3.0.0 | **Ratified**: 2026-07-21 | **Last Amended**: 2026-10-27
