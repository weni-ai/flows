# Engineering Spec: Endpoint authorization & tenant-isolation fixes

**Feature Branch**: `fix/endpoint-authz-tenant-fixes`
**Baseline branch**: `feat/add-oidc-auth-to-media-proxy-endpoint` (PR #897 — SEC-08 already addressed there)
**Created**: 2026-10-21
**Status**: Implemented (SDD Lite — specify + implement; SEC-02/05/08 out of scope)
**Source of truth**: internal security audit `docs/SECURITY-AUDIT.local.md` and `docs/SECURITY-AUDIT-OWASP.local.md` (local, not committed). Proof probes in `../docs/security/security_probes/`.

This is the Flows engineering spec for remediating the authorization and tenant-isolation findings on our HTTP endpoints. It records the HOW inside Flows.

## Inheritance from Product Spec

- **URL / path**: N/A — this is internal security remediation derived from an internal audit, not a product feature in `vtex-cx-engine-specs`.
- **Pinned commit**: N/A (see "Decision to confirm D0" below — reviewers decide whether a product spec / amendment is required before implement).
- **Architecture doc**: none.
- **Inherited binding decisions**: none.
- **Scope of this spec**: `engineering/flows` — authorization and tenant binding on `temba/api/v2/**` endpoints (DRF + FastAPI bridge) and the `weni` (rapidpro-apps) routes mounted in this app.
- **Divergences**: none (no product spec contradicted).

> Constitution note (Principle V requires derivation from an approved product spec). Security hardening from an internal audit has no product spec. **D0 (confirm at approval):** proceed as internal remediation, or first open a product-spec entry/amendment in `vtex-cx-engine-specs`.

## Baseline assumption

Implementation starts from `feat/add-oidc-auth-to-media-proxy-endpoint`, which already:

- Replaces the anonymous S3 media proxy auth with `InternalOIDCAuthentication` + `IsAuthenticated` + `IsAdminOrEditorInOrg` (SEC-08).
- Introduces `IsAdminOrEditorInOrg(IsUserInOrg)` with an `allowed_roles` hook in `temba/api/v2/permissions.py`.

This spec reuses that `IsUserInOrg` / `allowed_roles` pattern. **SEC-08 is out of scope here** (done in the baseline).

## Scope

**In scope (this cut): SEC-01 through SEC-11, excluding SEC-02, SEC-05, and SEC-08.**

| ID | Severity | Endpoint / entry point | Root cause |
| --- | --- | --- | --- |
| SEC-01 | Crítica | `internals/whatsapp_broadcasts` (+ FastAPI bridge) | `IsUserInOrg` fail-open + view trusts body `project`/`user_email` |
| SEC-03 | Alta | `internals/messages/stream` | Mixin MRO leaves auth/permission empty |
| SEC-04 | Alta | `internals/flows/import` | Imports into body `project_uuid`, not the authorized tenant |
| SEC-06 | Alta | `internals/flow_starts`, `internals/broadcasts/`, `whatsapp_flows` | Empty fixed token accepts `?token=` |
| SEC-07 | Alta | `org/<uuid>/is_suspended`, `suspend_flag` (weni) | No ownership check before org state change |
| SEC-09 | Média | `projects/internal/message_count` | Reads any project / global aggregate |
| SEC-10 | Média | `ticketer_queues` (weni) | No tenant filter |
| SEC-11 | Alta (a verificar) | other `IsUserInOrg` internal routes (`contact_groups` POST, `contacts_import_confirm` POST, `contacts_fields` GET/POST, `broadcasts/upload_media`) | Same fail-open + body-trust pattern as SEC-01/04 |

**Out of scope:**

- **SEC-02** — broker consumer `flows.update-permission`. Requires cross-team alignment (message origin/integrity, broker ACL). Deferred.
- **SEC-05** — module JWT not bound to tenant on the public `BaseAPIView`. Requires alignment with token issuers (Nexus and other module-JWT callers) before enforcement. Deferred.
- **SEC-08** — handled in the baseline branch.
- **SEC-12 – SEC-15** — outside this 1–11 cut (JWT-ignores-project reads, anonymous external-service reads, confused-deputy `open_ticket`, low-severity defense-in-depth). Not addressed here.

## User Scenarios & Testing *(mandatory)*

Attacker/caller profiles, consistent with the audit: Anonymous, Outsider (valid SSO login, no tenant), Low-privilege member, Member of tenant B, Internal caller / confused deputy.

### User Story 1 - A caller can only act within the tenant it belongs to (Priority: P1)

An authenticated caller hitting a tenant-scoped endpoint acts only on the project its identity (SSO user membership) is bound to. The project and acting user are never taken from the request body in a way that overrides the authenticated identity. Covers **SEC-01, SEC-04, SEC-11**.

**Why this priority**: This is the critical real-world incident — a regular user became admin of a tenant they never belonged to by sending another project/email in the body.

**Independent Test**: Reproduce the existing probes `IsUserInOrgFailOpenProbe` and `FlowImportCrossTenantProbe`. After the fix, the cross-tenant assertions must fail (i.e., the attack now returns 403/404), and the probes are updated to assert the secured behavior.

**Acceptance Scenarios**:

1. **Given** an outsider with a valid token and a non-existent `?project_uuid`, **When** they POST `internals/whatsapp_broadcasts` with `project`/`user_email` of tenant A in the body, **Then** the response is 403 and no broadcast, user, or membership is created for A.
2. **Given** a member of tenant B, **When** they send `?project_uuid=B` but `project=A` in the body, **Then** the request is rejected (403) because body and resolved tenant disagree — it does not act on A.
3. **Given** `internals/flows/import` with `?project_uuid` not matching the body `project_uuid`, **When** posted, **Then** import runs only against the tenant the caller is authorized for, or is rejected.
4. **Given** any in-scope endpoint using `IsUserInOrg` (SEC-11 routes included), **When** the project UUID is missing or resolves to no org, **Then** permission denies (no fail-open) and the view returns a consistent 400/404 without side effects.
5. **Given** `internals/whatsapp_broadcasts`, **When** the acting user is resolved, **Then** it comes from the authenticated identity, not from an arbitrary `user_email` in the body, and no user is auto-created from a body e-mail for a non-trusted caller.

---

### User Story 2 - Unauthenticated callers cannot reach internal write/stream endpoints (Priority: P1)

Anonymous requests cannot authenticate by accident (wrong mixin order) or via empty fixed tokens. Covers **SEC-03, SEC-06**.

**Why this priority**: These are internet-reachable-if-exposed writes with zero credentials.

**Independent Test**: Probes `MsgStreamViewAuthBypassProbe` and `FixedTokenFailOpenProbe`. After the fix, anonymous access returns 401/403 and the probes assert that.

**Acceptance Scenarios**:

1. **Given** `internals/messages/stream`, **When** an anonymous request posts, **Then** it is rejected (401/403) — the view enforces its intended JWT auth regardless of mixin MRO.
2. **Given** a fixed-token endpoint (`internals/flow_starts`, `internals/broadcasts/`, `whatsapp_flows`) whose configured token is empty, **When** a request sends `?token=` (empty), **Then** it is rejected — an unset/empty token never authenticates.
3. **Given** a correctly configured non-empty token, **When** the exact token is sent, **Then** the request is accepted (no regression for legitimate callers).

---

### User Story 3 - Privileged/cross-tenant actions require ownership and role (Priority: P2)

Org-level administrative and read endpoints verify that the caller owns the target object/tenant and holds the required role. Covers **SEC-07, SEC-09, SEC-10**.

**Why this priority**: High/medium findings allowing cross-tenant writes (suspend org) and reads (message counts, ticketer queues).

**Independent Test**: Probes `SuspendAnyOrgProbe`, `InternalMessageCountProbe`, `TicketerQueuesProbe`. After the fix the cross-tenant assertions fail (now 403), probes updated accordingly.

**Acceptance Scenarios**:

1. **Given** an authenticated user who is not an admin of org X, **When** they PATCH `org/<uuid>/is_suspended` or touch `suspend_flag` for X, **Then** it is rejected (403).
2. **Given** an outsider, **When** they GET `projects/internal/message_count` for an arbitrary project or the global aggregate, **Then** it is rejected or scoped to their own tenant only.
3. **Given** a member of tenant B, **When** they GET `ticketer_queues`, **Then** they see only their tenant's queues, never tenant A's.

---

### Edge Cases

- Legitimate internal service accounts (Connect via `CanCommunicateInternally`) that today act "on behalf of" a `user_email` — must keep working for their own coordinated projects (see **D1**).
- Chats media links already depend on the SEC-08 baseline; `internals/flows/import` (SEC-04) from Chats needs the body `project_uuid` to match the caller's authorized tenant.
- Missing vs unknown project UUID must return the same, documented status (400 missing / 404 unknown) consistently across endpoints, with no partial side effects.
- Endpoints currently relying on `IsUserInOrg` fail-open + a view-level `get_org_from_request` must not double-handle the project and must agree on the status code.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `IsUserInOrg.has_permission` MUST deny (return False) when the project UUID is absent or does not resolve to an org. Fail-open MUST be removed. (SEC-01, SEC-04, SEC-11)
- **FR-002**: When a tenant-scoped endpoint receives a project identifier in both the query and the body, and they disagree, the request MUST be rejected (403). A single resolved tenant MUST be used downstream. (SEC-01, SEC-04)
- **FR-003**: After a successful permission check, views and helpers MUST derive the acting tenant only from `request.org`, never by re-reading `project`/`project_uuid` from the body. (SEC-01, SEC-04, SEC-11)
- **FR-004**: `resolve_org_and_user_internal_whatsapp` MUST resolve the acting user from the authenticated identity (`request.user` or the JWT `email`), MUST NOT trust a `user_email` supplied in the body for a non-trusted caller, and MUST NOT create a user from an arbitrary body e-mail. (SEC-01)
- **FR-005**: `MsgStreamView` MUST enforce its intended JWT authentication and permission regardless of mixin resolution order; an anonymous request MUST be rejected. (SEC-03)
- **FR-006**: Fixed-token endpoints MUST reject a request when the configured token is empty or unset; only a non-empty exact match MUST authenticate. (SEC-06)
- **FR-007**: Org-administrative endpoints (`is_suspended`, `suspend_flag`) MUST verify the caller is authorized for the target org before any state change. (SEC-07)
- **FR-008**: Cross-tenant read endpoints (`projects/internal/message_count`, `ticketer_queues`) MUST scope results to the caller's tenant and MUST NOT expose other tenants' data or global aggregates to unauthorized callers. (SEC-09, SEC-10)
- **FR-009**: The SEC-11 internal routes (`contact_groups` POST, `contacts_import_confirm` POST, `contacts_fields` GET/POST, `broadcasts/upload_media`) MUST be verified and brought under the same hardened `IsUserInOrg` + tenant-binding behavior as SEC-01/04. (SEC-11)
- **FR-010**: On authorization failure, endpoints MUST return a consistent, documented status (401 unauthenticated, 403 forbidden, 404 unknown project) with no partial side effects and no internal detail leakage. (cross-cutting; Constitution IX/X)
- **FR-011**: Legitimate internal callers authorized via `CanCommunicateInternally` MUST retain their ability to operate across coordinated projects per decision **D1**; the fix MUST NOT silently break the Connect/Nexus/Chats flows enumerated in Dependencies.
- **FR-012**: The proof probes in `../docs/security/security_probes/` MUST be updated so each in-scope probe asserts the SECURED behavior and passes, and a regression test MUST exist for each fixed finding (Constitution XIV). Out-of-scope probes (SEC-02, SEC-05) remain as-is.

### Key Entities

- **Org / Project**: the tenant boundary (`proj_uuid`), with role membership (`OrgRole`: viewer/editor/admin/agent/…).
- **Authenticated identity**: SSO user (OIDC) with org membership, or module JWT (RS256). Binding the JWT to a tenant (SEC-05) is deferred; this cut relies on SSO membership and ownership checks.
- **Permission classes**: `IsUserInOrg` (base), `IsAdminOrEditorInOrg` (role-restricted), `HasValidJWT`, `CanCommunicateInternally` (trusted internal caller).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every in-scope cross-tenant/no-auth attack from the audit returns 401/403/404 instead of succeeding — verified by the updated probes for SEC-01, 03, 04, 06, 07, 09, 10 flipping from "vulnerable-pass" to "secured-pass", and SEC-11 covered by new regression tests.
- **SC-002**: No legitimate caller enumerated in Dependencies loses access after a coordinated contract update (zero regressions in the `api` CI group for the touched endpoints).
- **SC-003**: 100% of in-scope endpoints that mutate or read tenant data enforce tenant binding at the server boundary (no fail-open path remains in `IsUserInOrg`).
- **SC-004**: `./code_check.py` clean and `.github/workflows/ci.yml` green (groups api, channels, core, others).

## Assumptions

- **A1 (default for D1)**: Trusted internal callers (`CanCommunicateInternally`) MAY continue to act on behalf of a `user_email`, but only for a project consistent with the request; untrusted callers (plain OIDC user) MAY NOT. To be confirmed at approval.
- **A2**: Missing project → 400; unknown project → 404; unauthorized → 403; unauthenticated → 401, applied consistently.
- **A3**: Cross-service contract changes for in-scope endpoints (Chats `flows/import` project agreement; any caller that relied on body-only project for SEC-01/04/11) are coordinated before enforcement is deployed; rollout may be staged/feature-flagged to avoid breakage. JWT-to-tenant binding (SEC-05) is deferred and not relied upon here.
- **A4**: SEC-02, SEC-05 (alignment needed) and SEC-12–SEC-15 are handled outside this spec.
- **A5**: The audit docs and probes are the authoritative description of each finding; this spec does not restate per-finding code detail already in `docs/SECURITY-AUDIT.local.md`.

## Dependencies (downstream callers to coordinate)

Identified from sibling repos under `../`:

- **Connect** (`weni-engine`): broad `internals/*` usage via Keycloak client-credentials; sends `user`/`user_email`/`project` in body (service account → likely `CanCommunicateInternally`). Relevant to SEC-01/04/11 and D1.
- **Nexus** (`nexus-ai`): `internals/whatsapp_broadcasts` (SEC-01) and `internals/messages/stream` (SEC-03) via module JWT; `project` currently in body → must send/confirm the authorized project. (JWT-to-tenant binding itself is SEC-05, deferred.)
- **Chats** (`chats-engine`): `internals/flows/import` (SEC-04) — body `project_uuid` must match the caller's tenant.
- **Router (Nexus)**: `internals/broadcasts/` with `?token=` (SEC-06).
- **weni-cli-backend**, **billing**, **weni-integrations-engine**: `flows_rest_client` internal calls touching in-scope routes.

## Decisions to confirm at approval

- **D0**: Proceed as internal remediation vs. require a product-spec/amendment first (Constitution V).
- **D1**: Exact "act on behalf of" policy for `CanCommunicateInternally` callers (A1).
- **D2**: Role matrix per endpoint (which `OrgRole` may call each), reusing `allowed_roles` from the baseline — e.g., does `whatsapp_broadcasts`/`flow_starts` require admin/editor, or any member?
- **D3**: Rollout strategy for the SEC-01/04/11 contract tightening (hard cutover vs. staged/feature-flagged while Chats/Nexus/Connect adapt).
