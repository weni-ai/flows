# Specification Quality Checklist: Connect a Mercado Livre seller to Flows (OAuth claim)

**Purpose**: Validate specification completeness and quality before proceeding to planning
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

- This is an engineering spec (constitution Principle V), so its audience is the Flows, Courier and Mailroom engineers. The user stories and success criteria are written in plain language. Repository file names and existing constraints appear only in "Scope in This Repository" and "Current State", as engineering context.
- The identifiers of the OAuth exchange (authorize and token addresses, scopes, PKCE method) and the channel config keys are part of the contract with Mercado Livre and with Courier, not implementation choices, so they stay in the requirements and in "Fixed Identifiers".
- The `Origin Without Product Spec` section, `Test Strategy` and the Principle XII peak-load note are added by hand because the `vtex-cx-engineering` preset is not installed (see `TODO(SPECKIT_PRESET)` in the constitution).
- No clarification markers were needed. The seven open questions of the feature description were each taken as a recorded default in "Assumptions". Planning decided each of them (research R3, R7, R8, R9, R13), and only the Courier confirmation of the config keys is still open. The questions, for reference:
  1. `state`: opaque nonce with a server-side attempt, as in the Outlook flow, not a signed value.
  2. Config contract: key names and absolute expiry format, to align with Courier CO-02 and RP-04. `oauth_provider` and `oauth_status` reuse the Outlook names.
  3. Switches: both created false in the channel config. Known gap: until RP-05 there is no screen to turn them on.
  4. Token exposure: channel page, list and v2 API checked in this feature. Other surfaces are searched in planning.
  5. Seller already connected in the same organization: the conflict error is enough until RP-05.
  6. Availability: the option shows only when the ML application settings are present, with no separate beta flag.
  7. Site: Brazil only.
- Dependency outside this repository: FND-01 (the application in the DevCenter, its client id, secret and registered redirect URI). Without it the feature is tested only with Mercado Livre mocked.
