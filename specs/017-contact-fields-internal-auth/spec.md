# Engineering Specification: Internal service access and `back_in_stock_sku` on contact fields update

**Repository**: weni-ai/flows — backend

**Feature Branch**: `017-contact-fields-internal-auth`

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "precisamos adicionar a permissão CanCommunicateInternally a view UpdateContactFieldsView (temba/api/v2/internals/contacts/views.py), tomando como exemplo InternalWhatsappBroadcastsEndpoint (temba/api/v2/internals/broadcasts/views.py), e no serializador da view é preciso adicionar o campo back_in_stock_sku em FALLBACK_AUTO_CREATE_CONTACT_FIELD_KEYS (temba/api/v2/internals/contacts/serializers.py)."

**Suggested cycle**: SDD Lite. One view and one serializer module in `temba/api/v2/internals/contacts`, plus tests and changelog. No migration, no new endpoint, no Courier or Mailroom coordination.

## Origin Without Product Spec

- Product Spec: none
- Problem: `PATCH /api/v2/internals/update_contacts_fields` only accepts a module JWT or an AWS Lambda STS caller identity. Weni internal services that authenticate with an internal OIDC token and hold the `can_communicate_internally` permission cannot call it, unlike neighbouring internal endpoints (`InternalWhatsappBroadcastsEndpoint`, `InternalContactFieldsEndpoint`). Separately, callers that send `back_in_stock_sku` to an org that does not yet have that contact field have the value silently dropped, because the key is not in the list of fields the endpoint auto-creates.
- Acceptance criteria:
  - AC-1: A request authenticated by internal OIDC whose user has `can_communicate_internally` updates the contact fields and returns HTTP 200 with `{"message": "Contact fields updated successfully"}`.
  - AC-2: A request authenticated by internal OIDC whose user lacks `can_communicate_internally` is rejected with HTTP 403 and no contact is modified.
  - AC-3: A request with an invalid or rejected OIDC token, and no valid JWT or Lambda identity, is rejected (HTTP 401 or 403) and no contact is modified.
  - AC-4: Existing JWT callers keep the same behaviour and responses (success, 400 validation errors, 404 unknown project).
  - AC-5: Existing Lambda STS callers keep working: a request whose bearer value is an allowed STS URL is not rejected by the OIDC authenticator and is still validated through the Lambda check.
  - AC-6: When `contact_fields` contains `back_in_stock_sku` and the org has no such field and is under its field limit, a text contact field with key and label `back_in_stock_sku` is created and the contact value is set.
  - AC-7: When the org already has `back_in_stock_sku`, the existing field is reused and no duplicate is created.
  - AC-8: When the org is at its field limit, `back_in_stock_sku` is skipped with the same warning behaviour as the other auto-create keys, and the request still succeeds for the remaining fields.
  - AC-9: Automated tests in `temba/api/v2/internals/contacts/tests.py` cover AC-1 through AC-8.

## Scope in This Repository

**This repository implements**:

- Internal OIDC authentication plus `CanCommunicateInternally` as an additional accepted access path on `UpdateContactFieldsView`, alongside the existing JWT and Lambda paths.
- Adding `back_in_stock_sku` to `FALLBACK_AUTO_CREATE_CONTACT_FIELD_KEYS` and to `FALLBACK_AUTO_CREATE_CONTACT_FIELD_LABELS`, and updating the `_resolve_contact_field_for_update` docstring that lists those keys.
- Tests in `temba/api/v2/internals/contacts/tests.py`.
- A `WENI-CHANGELOG.md` entry.

**Out of scope here**:

- Removing or changing the JWT or Lambda access paths.
- Tenant checks for internal OIDC callers (an internal service is trusted for any project, as on the other internal endpoints that use `CanCommunicateInternally`).
- Changing other internal contact endpoints, the field limit, or the value type of auto-created fields.
- The TODO(DRF_PERMISSIONS) clean-up of `IsAuthenticated` in neighbouring views.

## Current State

- `UpdateContactFieldsView` inherits `APIViewMixin` (`permission_classes = []`) and sets `authentication_classes = [OptionalJWTAuthentication]`.
- In `patch`, when `request.jwt_payload` is absent the view calls `LambdaURLValidator.protected_resource`, which reads `Authorization: Bearer <sts_url>`, checks the URL against `LAMBDA_VALIDATION_URL`, calls STS, and checks the ARN against `LAMBDA_ALLOWED_ROLES`.
- The view runs outside `ATOMIC_REQUESTS` so fallback-created fields are committed before Mailroom's `contact_modify` reads them.
- `InternalWhatsappBroadcastsEndpoint` uses `[OptionalJWTAuthentication, InternalOIDCAuthentication]` and `[(IsAuthenticated & (CanCommunicateInternally | IsUserInOrg)) | HasValidJWT]`.
- `weni.internal.permissions.CanCommunicateInternally` checks `request.user.user_permissions` for `can_communicate_internally`; it returns `False` for `AnonymousUser`.
- `OptionalJWTAuthentication` returns `None` for a bearer value that is not a valid JWT, so other authenticators run.
- `InternalOIDCAuthentication` (mozilla-django-oidc) sends any bearer value to the identity provider and raises `AuthenticationFailed` when it is rejected. Placed naively in `authentication_classes`, it would reject every Lambda request, whose bearer value is an STS URL.
- `FALLBACK_AUTO_CREATE_CONTACT_FIELD_KEYS` is `{"segment", "orderform", "email", "session", "vtex_account", "marketing_opt_in"}`; `FALLBACK_AUTO_CREATE_CONTACT_FIELD_LABELS` maps each key to its label and is indexed directly, so a key missing from the labels map would raise `KeyError`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Internal service updates contact fields (Priority: P1)

A Weni internal service (authenticated through the platform's internal OIDC identity) needs to update a contact's fields in a project, the same way it already calls other internal endpoints, without needing a module JWT or an AWS Lambda role.

**Why this priority**: This is the access gap that motivates the change.

**Independent Test**: Authenticate the test client as a user with `can_communicate_internally` through the OIDC authenticator (patched backend), PATCH a body with `project`, `contact_urn` and `contact_fields`, and assert the 200 response and the stored contact values.

**Acceptance Scenarios**:

1. **Given** an internal user with `can_communicate_internally` and an existing contact, **When** it PATCHes `update_contacts_fields` with a known field, **Then** the response is 200 and the contact field value is stored.
2. **Given** an authenticated OIDC user without `can_communicate_internally`, **When** it PATCHes the same body, **Then** the response is 403 and the contact is unchanged.
3. **Given** a bearer token rejected by the identity provider and no other valid credential, **When** the PATCH is sent, **Then** the request is rejected and the contact is unchanged.

---

### User Story 2 - Existing JWT and Lambda callers are unaffected (Priority: P1)

Modules that call the endpoint with a JWT, and AWS Lambda functions that call it with an STS caller identity, must keep working after the deploy without any change on their side.

**Why this priority**: Breaking current callers is a production outage. The Lambda path is the one most at risk, because its bearer value would be rejected by the OIDC authenticator.

**Independent Test**: Run the existing `UpdateContactFieldsViewTest` (Lambda) and `UpdateContactFieldsViewJWTTest` suites unchanged, and add one Lambda test where the bearer is an allowed STS URL and the OIDC backend is not called.

**Acceptance Scenarios**:

1. **Given** a valid JWT, **When** the PATCH is sent, **Then** responses match today's (200, 400, 404 cases).
2. **Given** `Authorization: Bearer <allowed STS URL>` and an accepted Lambda identity, **When** the PATCH is sent, **Then** the response is 200 and the identity provider is never queried with the STS URL.
3. **Given** `Authorization: Bearer <allowed STS URL>` and a rejected Lambda identity, **When** the PATCH is sent, **Then** the response is the Lambda check's error (400 or 401) as today.

---

### User Story 3 - `back_in_stock_sku` is stored even when the field does not exist yet (Priority: P2)

A back-in-stock automation sends the SKU the contact is waiting for as `back_in_stock_sku`. In orgs where that field was never created, the value must still be persisted so flows can use it, as already happens for `segment`, `orderform`, `email`, `session`, `vtex_account` and `marketing_opt_in`.

**Why this priority**: Without it the value is silently ignored in new orgs; independent of the access change.

**Independent Test**: PATCH `contact_fields: {"back_in_stock_sku": "SKU-123"}` for an org without that field and assert the field exists, is text, and the contact holds `SKU-123`.

**Acceptance Scenarios**:

1. **Given** an org without `back_in_stock_sku` and under its field limit, **When** the PATCH contains `back_in_stock_sku`, **Then** a text field `back_in_stock_sku` is created and the contact value is set.
2. **Given** an org that already has `back_in_stock_sku`, **When** the PATCH contains it, **Then** the existing field is used and the field count does not change.
3. **Given** an org at its field limit, **When** the PATCH contains `back_in_stock_sku`, **Then** the field is not created, a warning is logged, and the response is still 200.
4. **Given** the key is sent as `Back_In_Stock_SKU`, **When** the PATCH is processed, **Then** it resolves to the canonical lowercase key like the other auto-create keys.

---

### Edge Cases

- `Authorization` header absent: no authenticator succeeds; the request must be rejected (today the Lambda check fails on the missing header and returns an error; that outcome stays an error and never succeeds).
- An OIDC user who has `can_communicate_internally` and also sends a JWT: the JWT path is tried first, as on the broadcast endpoint; either credential is enough.
- A bearer value that is a valid JWT must never be sent to the identity provider unnecessarily, and a bearer value that is an allowed STS URL must never be sent to it at all.
- `back_in_stock_sku` with an empty string or `null` value follows the same rules as the other contact fields (clears the value).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `UpdateContactFieldsView` MUST accept a request authenticated by internal OIDC when the user has the `can_communicate_internally` permission, checked with `weni.internal.permissions.CanCommunicateInternally`.
- **FR-002**: `UpdateContactFieldsView` MUST keep accepting requests with a valid module JWT, with unchanged responses.
- **FR-003**: `UpdateContactFieldsView` MUST keep accepting requests validated by the Lambda STS check, and the OIDC authenticator MUST NOT reject or contact the identity provider for a bearer value that is an allowed Lambda STS URL.
- **FR-004**: A request that satisfies none of the three paths (JWT, internal OIDC with permission, Lambda) MUST be rejected before the serializer runs and MUST NOT modify any contact or create any field.
- **FR-005**: The permission declaration MUST NOT use `IsAuthenticated` or `AllowAny` (Principle XVII). `CanCommunicateInternally` already denies anonymous users, so it is sufficient on its own for the OIDC path.
- **FR-006**: `back_in_stock_sku` MUST be added to `FALLBACK_AUTO_CREATE_CONTACT_FIELD_KEYS` and to `FALLBACK_AUTO_CREATE_CONTACT_FIELD_LABELS` with label `back_in_stock_sku`.
- **FR-007**: Auto-creation of `back_in_stock_sku` MUST follow the existing rules: text type, case-insensitive key resolution, reuse of an existing active field, and skip with warning when the org field limit is reached.
- **FR-008**: The view MUST stay outside `ATOMIC_REQUESTS` so fallback-created fields are committed before Mailroom reads them.

### Key Entities

- **Internal service user**: platform user authenticated by internal OIDC, authorized by the `can_communicate_internally` Django permission.
- **Contact field (auto-create key)**: org-level text contact field that the endpoint creates on demand when the key is in the allow-list; `back_in_stock_sku` joins that list.
- **Contact**: resolved by `contact_urn` within the org given by `project` or `channel_uuid`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of internal OIDC requests with `can_communicate_internally` and a valid body succeed in tests; 100% of those without the permission are rejected with no contact change.
- **SC-002**: 100% of the existing Lambda and JWT tests for this endpoint pass without modification of their assertions.
- **SC-003**: After rollout, zero increase in 401/403 responses on `update_contacts_fields` from existing Lambda and JWT callers in the first 24 hours.
- **SC-004**: In orgs under the field limit, 100% of requests that send `back_in_stock_sku` result in the value being stored on the contact.

## Assumptions

- Internal OIDC callers are trusted platform services and, as on `InternalContactFieldsEndpoint` and `InternalWhatsappBroadcastsEndpoint`, are not restricted to a single project; the org still comes from `project` or `channel_uuid` in the body.
- Lambda callers keep sending `Authorization: Bearer <sts_url>` with a URL that matches `LAMBDA_VALIDATION_URL`, which makes them distinguishable from OIDC tokens before calling the identity provider.
- `back_in_stock_sku` is a single text value (one SKU, or a caller-formatted string); no new value type is needed.
- Field values continue to be written as the internal user (`INTERNAL_USER_EMAIL`), regardless of which access path authenticated the request.
- Peak load is unchanged: no new endpoint or fan-out. Declared peak is the current peak of `update_contacts_fields`, driven by the busiest automation (order of hundreds of PATCH requests per minute across orgs). OIDC adds one identity-provider round trip per request on that path only, as on the other internal endpoints.

## Contracts

- `PATCH /api/v2/internals/update_contacts_fields` request and response bodies are unchanged. Accepted credentials widen additively (internal OIDC); no existing credential is removed. Internal, non-public endpoint; no SemVer change to the public API.
- `back_in_stock_sku` becomes an auto-created key. Additive; callers that already have the field see no change.

## Observability

- Rejections by permission are standard DRF 401/403 responses; no new logs required.
- Reuse the existing field-limit warning and Sentry message for `back_in_stock_sku`; it already carries the key and org id only.
- Do not log bearer values (OIDC token, JWT, or STS URL).

## Failure Handling

- Identity-provider errors on the OIDC path surface as 401 (rejected token) or the existing mozilla-django-oidc behaviour for other HTTP errors; they must not fall through to a success.
- Lambda STS call keeps its existing 30s timeout and error responses.
- No retry is added; the caller owns retry, as today.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-1 OIDC with permission | New test class in `temba/api/v2/internals/contacts/tests.py` following the pattern used for other `CanCommunicateInternally` endpoints (user granted `can_communicate_internally`, OIDC authenticate patched). PATCH a full body, assert 200 and stored value. |
| AC-2 OIDC without permission | Same class, user without the permission; assert 403 and contact unchanged. |
| AC-3 rejected token | Patch OIDC backend to raise `AuthenticationFailed`; assert 401/403 and contact unchanged. |
| AC-4 JWT unchanged | Existing `UpdateContactFieldsViewJWTTest` passes as is. |
| AC-5 Lambda unchanged | Existing `UpdateContactFieldsViewTest` passes as is; plus one test with `Authorization: Bearer <allowed STS URL>` asserting the OIDC backend is not called and the Lambda result decides the response. |
| AC-6 auto-create | PATCH `back_in_stock_sku` on an org without the field; assert field created as text with key/label `back_in_stock_sku` and contact value set (mirror `test_fallback_creates_marketing_opt_in_when_missing`). |
| AC-7 reuse | Pre-create the field; assert count unchanged and value set. |
| AC-8 field limit | Override the org field limit to the current count; assert no field, warning logged, 200. |
| AC-9 | All of the above live in `temba/api/v2/internals/contacts/tests.py` using `TembaTest`. |

**Flow coverage** (Principle XIV): the OIDC success test and the `back_in_stock_sku` auto-create test go through the full `PATCH` → serializer → Mailroom `contact_modify` (mocked with `@mock_mailroom`) path.

**Failure paths**: missing permission, rejected token, no credentials, Lambda rejected identity, field limit reached.

**Gates**: `poetry run coverage run manage.py test temba.api.v2.internals.contacts`, clean `./code_check.py`, green `.github/workflows/ci.yml`. No new `# pragma: no cover`.

## Rollout and Rollback

1. Grant `can_communicate_internally` to the internal service user that will call the endpoint (if not already granted).
2. Deploy Flows. No migration.
3. Monitor 401/403 rate on `update_contacts_fields` for existing Lambda and JWT callers.
4. **Rollback:** revert the change. OIDC callers lose access; `back_in_stock_sku` stops being auto-created (fields already created remain and keep working).

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | PR to `main` with review and green `ci.yml`. | none |
| II. Security and Secrets | No new secret; OIDC settings already exist. | none |
| III. Observability | No bearer values logged; existing field-limit warning reused. | none |
| IV. Versioned Contracts | Internal endpoint; additive credential and additive auto-create key. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`. | none |
| VI. No Silent Divergence | Not applicable: no Product Spec. | none |
| VII. Commit Messages | Atomic Conventional Commits (e.g. `feat: allow internal auth on contact fields update`, `feat: auto-create back_in_stock_sku field`). | none |
| VIII. Changelog Maintenance | `feat:` bullet in `WENI-CHANGELOG.md`, marked as an access/security-relevant change. | none |
| IX. Never Trust the Client | Authorization enforced on the server for every path; body still validated by `InternalContactFieldsValuesSerializer`. | none |
| X. Fail Gracefully | DRF error responses; existing Lambda timeout. | none |
| XI. Bounded Retry Over REST | No new outbound propagation; no retry added. | none |
| XII. Scalability and Peak Load | Stateless view; peak declared in Assumptions. | none |
| XIII. Diagnosable Errors | Existing warning uses org id and key only. | Platform `send_default_pii=True` remains `TODO(SENTRY_PII)`. |
| XIV. Tests Exercise Flows | Full PATCH tests for OIDC and `back_in_stock_sku`, plus failure paths. `TembaTest`. | none |
| XV. Explicit Over Clever | Allow-list stays a named constant; the reason OIDC must skip STS bearer values is stated where that check lives. | none |
| XVI. Contained Changes | Only `UpdateContactFieldsView`, the auto-create constants/docstring, tests, changelog. | none |
| XVII. Explicit, Scoped Authorization | Permission declared explicitly as JWT, `CanCommunicateInternally`, or Lambda identity; no `IsAuthenticated` or `AllowAny`. | Internal OIDC callers are not scoped to one org, matching existing internal endpoints: `can_communicate_internally` is a service-level grant. |
| Backend Standards | `code_check.py`; no new locale strings. | none |

## Implementation Decisions

- SDD Lite: one app, no migration.
- Follow the broadcast endpoint's composition minus `IsAuthenticated`: JWT first, then internal OIDC with `CanCommunicateInternally`, then the Lambda check as today.
- The OIDC authenticator must not run for a bearer value that is an allowed Lambda STS URL (`LambdaURLValidator.is_valid_url`), so the Lambda path is preserved; the exact mechanism (a thin authenticator subclass or an explicit check in the view) is left to implementation, with a comment explaining why.
- `back_in_stock_sku` is added to both the keys set and the labels map, since the labels map is indexed directly.

## Open Questions

None.
