# Engineering Spec: Public API for broadcasts statistics

**Feature Branch**: `feat/broadcasts-statistics-public-api`

**Created**: 2026-10-28

**Status**: Draft

**Cycle**: SDD Lite

**Input**: User description: "Make `/api/v2/internals/broadcasts-statistics` a public API like the other `/api/v2/*.json` endpoints. Public does not mean anonymous: it MUST accept API Key and JWT authentication, the same way `/api/v2/whatsapp_broadcasts.json` does."

## Origin Without Product Spec

- Product Spec: none
- Problem: Broadcast statistics (bulk-send broadcasts with processed, sent, delivered, read, failed counts and cost) are only reachable through `/api/v2/internals/broadcasts-statistics`, which accepts only internal OIDC tokens. Customers and integrations that already call the public v2 API with an API Key, or Weni services that call it with a JWT, cannot read these statistics.
- Acceptance criteria:
  - AC-1: A request with a valid API Key of a workspace member returns `200` with the paginated bulk-send broadcasts and statistics of the API Key's workspace.
  - AC-2: A request with a valid JWT whose tenant claims (`project_uuid` / `project`, or `channel_uuid` / `channel`) identify a workspace returns `200` with that workspace's bulk-send broadcasts and statistics. A `project_uuid` query parameter never selects the workspace of a JWT request.
  - AC-3: Every workspace role (Administrator, Editor, Marketing, Agent, Viewer, Surveyor) can read the endpoint, as on the internal endpoint. A request without credentials, with invalid credentials, or from a user outside the workspace returns `403`.
  - AC-4: An API Key of workspace A never returns broadcasts of workspace B, even when the `project_uuid` of workspace B is sent as a query parameter.
  - AC-5: The `start_date`, `end_date`, `name`, and `id` filters and the `limit`/`offset` pagination behave as they do on the internal endpoint, and results are ordered by most recent first.
  - AC-6: An invalid filter value (non-ISO-8601 date, non-integer `id`, `start_date` after `end_date`) returns `400` with a descriptive error instead of a server error.
  - AC-7: Each result item has the same fields and shape as the internal endpoint item.
  - AC-8: The number of database queries to serve one page does not grow with the number of items on the page.
  - AC-9: The endpoint is listed in the v2 API root and in the API explorer, and its documentation page renders.
  - AC-10: `/api/v2/internals/broadcasts-statistics` keeps its current authentication, contract, and behavior.

## Coexistence with the Internal Endpoint

The public endpoint is added alongside `/api/v2/internals/broadcasts-statistics`, not in place of it. Both endpoints are served at the same time for an indefinite period. Removing the internal endpoint is a possible future decision, to be taken only after its consumers have moved to the public endpoint, and it may never be taken. If it is, it MUST be its own change with its own spec and an announced deprecation path (Principle IV). Nothing in this change depends on that removal.

## Differences from the Internal Endpoint

Both endpoints return the same data: the same bulk-send broadcasts of the workspace, the same filters (`start_date`, `end_date`, `name`, `id`), the same ordering, the same `limit`/`offset` pagination, and the same item fields and defaults. A consumer reads both responses the same way. The differences below are intentional and come from the public v2 API conventions.

| Aspect | Internal endpoint | Public endpoint |
|---|---|---|
| Authentication | Internal OIDC token only | API Key, Basic with API token, Django session, Connect session token, JWT; no internal OIDC |
| Workspace resolution | `project_uuid` query parameter, always required | From the credentials only: API Key workspace, JWT tenant claims (SEC-05), or session workspace; query `project_uuid` is ignored |
| Template lookup | Any template with the broadcast's `template_id` | Only templates of the caller's workspace; a template of another workspace is reported as `null` |
| Authorization | Any member of the workspace, any role | Any workspace role, through a dedicated read permission (`msgs.broadcast_statistics_api`) granted to all six roles; any valid JWT is accepted. Viewers cannot hold API Keys, so they reach it through a Django or Connect session |
| Invalid date or non-integer `id` | Not validated; can surface as a server error | `400` with the offending field |
| `start_date` after `end_date` | `200` with an empty list | `400` with a validation error |
| Missing or unknown workspace | `400` `Project UUID not provided` / `404` `Project not found` | `400` from the public API error handler (`Invalid project` / `Organization not found`) |
| Rate limit | None | `v2` scope: 2,500 requests per hour per (workspace, user) for token-authenticated requests |
| Database | Primary | Read-only replica; recently updated statistics may lag by the replica delay |
| Request without `.json` | Not applicable | Renders the documentation page without querying broadcasts |
| Queries per page | Grow with page size (statistics and template looked up per item) | Constant with respect to page size |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Integration reads broadcast statistics with an API Key (Priority: P1)

A customer integration that already uses the public v2 API (for example to send WhatsApp broadcasts through `whatsapp_broadcasts.json`) reads the delivery statistics of its bulk-send broadcasts using the same API Key, so it can report on campaign performance without asking for internal credentials.

**Why this priority**: This is the reason for the change. Without it, external consumers have no supported way to read the statistics.

**Independent Test**: Create bulk-send broadcasts with statistics in two workspaces, call the public endpoint with the API Key of an Administrator of the first workspace, and check that only the first workspace's broadcasts are returned, with their statistics, most recent first.

**Acceptance Scenarios**:

1. **Given** an Administrator API Key and three bulk-send broadcasts in the workspace, **When** the integration requests the endpoint, **Then** it receives `200` with the three broadcasts and their statistics, most recent first.
2. **Given** an Administrator API Key of workspace A and broadcasts in workspace B, **When** the integration requests the endpoint passing workspace B's `project_uuid`, **Then** no broadcast of workspace B is returned.
3. **Given** a Viewer logged in through a Django or Connect session, **When** the Viewer requests the endpoint, **Then** it receives `200` with the workspace's broadcasts.
4. **Given** a Surveyor API Key, **When** the integration requests the endpoint, **Then** it receives `200`.
5. **Given** no credentials, or a user who is not a member of the workspace, **When** a client requests the endpoint, **Then** it receives `403`.

---

### User Story 2 - Weni service reads broadcast statistics with a JWT (Priority: P1)

A Weni service that already calls public v2 endpoints with a signed JWT reads the broadcast statistics of the workspace identified by the token's tenant claims. Following SEC-05 (`specs/009-endpoint-authz-tenant-fixes`), a query parameter cannot point a JWT at another workspace.

**Why this priority**: JWT is the second authentication method explicitly required; it is how platform services reach the public API today.

**Independent Test**: Call the endpoint with a JWT whose payload has the workspace `project_uuid` and check the response contains that workspace's bulk-send broadcasts.

**Acceptance Scenarios**:

1. **Given** a valid JWT with `project_uuid` of a workspace, **When** the service requests the endpoint, **Then** it receives `200` with that workspace's bulk-send broadcasts.
2. **Given** a valid JWT with `project_uuid` of workspace A and a `project_uuid` query parameter of workspace B, **When** the service requests the endpoint, **Then** it receives only workspace A's broadcasts.
3. **Given** a valid JWT without tenant claims and a `project_uuid` query parameter, **When** the service requests the endpoint, **Then** it receives `400` and no data.
4. **Given** a valid JWT pointing to a workspace that does not exist, **When** the service requests the endpoint, **Then** it receives `400` with an invalid project error.

---

### User Story 3 - Filtering and paginating statistics (Priority: P2)

A consumer narrows results by creation period, broadcast name, or broadcast id, and pages through large histories.

**Why this priority**: Parity with the internal endpoint so that existing consumers can switch without losing capabilities.

**Independent Test**: Create broadcasts with different names and creation dates, call the endpoint with each filter and with `limit`/`offset`, and check the returned subset and pagination links.

**Acceptance Scenarios**:

1. **Given** broadcasts created 10 and 40 days ago, **When** the consumer filters with `start_date` 30 days ago, **Then** only the broadcast from 10 days ago is returned.
2. **Given** broadcasts named "Alpha" and "Beta", **When** the consumer filters with `name=bet`, **Then** only "Beta" is returned.
3. **Given** five broadcasts, **When** the consumer requests `limit=2&offset=2`, **Then** it receives the third and fourth most recent broadcasts, `count=5`, and `next`/`previous` links.
4. **Given** `start_date=not-a-date`, **When** the consumer requests the endpoint, **Then** it receives `400` with an error naming the invalid field.

### Edge Cases

- A bulk-send broadcast without a statistics record returns the statistics block with zero counts, `currency` `BRL`, and null timestamps, as the internal endpoint does.
- A broadcast whose `template_id` points to a template that no longer exists returns `template: null`.
- A broadcast without `created_by` returns `created_by: null`.
- Broadcasts that are not bulk sends are never returned.
- A valid JWT without tenant claims returns `400` (workspace not found), with or without a `project_uuid` query parameter, never data from an arbitrary workspace.
- `limit` above the maximum page size is capped at the maximum (100), consistent with the internal endpoint.
- A request to the endpoint without the `.json` suffix from a browser renders the documentation page without querying broadcasts, as the other public list endpoints do.
- `OPTIONS` returns `405`, as on every public v2 endpoint.
- Write methods (`POST`, `PUT`, `DELETE`) are not supported and return `405`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a read-only endpoint `GET /api/v2/broadcasts_statistics.json` under the public v2 API.
- **FR-002**: The endpoint MUST accept the same authentication methods as `/api/v2/whatsapp_broadcasts.json`: API Key (`Authorization: Token <key>`), Basic auth with API token, Connect session token, Django session, and JWT (`Authorization: Bearer <jwt>`).
- **FR-003**: For non-JWT requests, the endpoint MUST require a dedicated broadcast statistics read permission held by every workspace role (Administrator, Editor, Marketing, Agent, Viewer, Surveyor), matching the internal endpoint, which admits any workspace member. It MUST accept any valid JWT, as the public v2 API already does. Granting this permission MUST NOT give any role access to other broadcast endpoints it cannot reach today.
- **FR-004**: The endpoint MUST scope results to the workspace resolved from the credentials: the API Key's workspace, the JWT tenant claims, or the session user's workspace. A `project_uuid` query parameter MUST NOT select or override the workspace of an API Key or of a JWT.
- **FR-005**: The endpoint MUST return only bulk-send broadcasts of that workspace, ordered by creation date descending, with a stable tiebreaker.
- **FR-006**: The endpoint MUST support the optional filters `start_date` (created on or after), `end_date` (created on or before), `name` (case-insensitive contains), and `id` (exact broadcast id).
- **FR-007**: `start_date` and `end_date` MUST accept ISO 8601 dates or datetimes; any other value MUST be rejected with `400`. `start_date` later than `end_date` MUST be rejected with `400`. A non-integer `id` MUST be rejected with `400`.
- **FR-008**: The endpoint MUST paginate with `limit` and `offset`, default page size 10, maximum 100, and return `count`, `next`, `previous`, and `results`, matching the internal endpoint.
- **FR-009**: Each item in `results` MUST have exactly the fields of the internal endpoint item: `id`, `name`, `created_by`, `created_on`, `modified_on`, `text`, `media`, `broadcast_type`, `groups`, `status`, `statistics` (`processed`, `sent`, `delivered`, `failed`, `contact_count`, `read`, `cost`, `currency`, `template_price`, `created_on`, `modified_on`), and `template` (`id`, `name` or null).
- **FR-010**: The number of database queries to serve a page MUST be constant with respect to the page size.
- **FR-011**: Reads MUST use the read-only database connection, as the other public v2 list endpoints do.
- **FR-012**: The endpoint MUST be subject to the v2 API rate limit for token-authenticated requests.
- **FR-013**: The endpoint MUST be documented through its docstring, listed in the v2 root view, and listed in the API explorer with its query parameters.
- **FR-014**: `/api/v2/internals/broadcasts-statistics` MUST remain unchanged in authentication, permissions, parameters, and response.

### Key Entities

- **Broadcast**: a message sent to many contacts. Only broadcasts flagged as bulk sends are in scope. Carries name, text, media, type, status, groups, creator, and an optional template reference.
- **Broadcast statistics**: delivery counters and cost for one broadcast (processed, sent, delivered, read, failed, contact count, cost, currency, template price).
- **Workspace (org / project)**: the tenant the credentials resolve to; every result belongs to it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An integration holding an existing v2 API Key can retrieve its broadcast statistics with a single authenticated request, with no new credentials issued.
- **SC-002**: 100% of requests with credentials of workspace A return zero broadcasts of any other workspace.
- **SC-003**: 100% of malformed filter values return a client error (`400`) and none return a server error.
- **SC-004**: A consumer of the internal endpoint can switch to the public endpoint by changing only the URL and the credentials, with no change to how it reads the response.
- **SC-005**: Serving a page of 100 items takes the same number of database queries as serving a page of 1 item.

## Peak Load

- Per credential, load is capped by the existing `v2` throttle scope: 2,500 requests per hour per (workspace, user) pair for token-authenticated requests, which is about 0.7 requests per second per pair.
- Declared peak for planning: 20 requests per second across all workspaces, each returning at most 100 items. This is an assumption, since there is no current traffic on a public route; it is consistent with reporting and dashboard polling and is to be revisited with production metrics after rollout.
- Each request is served from the read-only replica with a constant number of queries per page (FR-010, FR-011), so cost grows linearly with request rate and not with page size.

## Test Strategy

All tests use `TembaTest`-based classes, following the neighboring public endpoint tests in `temba/api/v2/tests.py` (`APITest`). They run in the `api` CI group with `poetry run coverage run manage.py test`.

| Acceptance criterion | Test (flow from request to response) |
|---|---|
| AC-1 | Admin API Key request returns `200` with the workspace's bulk-send broadcasts, statistics, and most recent first; non-bulk broadcasts are excluded. |
| AC-2 | JWT request (patched decode, `JWT_PUBLIC_KEY` overridden) with `project_uuid` in the payload returns `200` with that workspace's data, even when the query points to another workspace; JWT without tenant claims returns `400` with or without a query `project_uuid`; JWT with unknown project returns `400`. |
| AC-3 | Anonymous, non-workspace user, and invalid API Key return `403`; Administrator, Editor, Agent, Viewer, and Surveyor sessions return `200`; Surveyor API Key returns `200`; `POST` returns `405` and `OPTIONS` `405`. Viewer and Surveyor still get `403` on `broadcasts.json`. |
| AC-4 | Admin API Key of workspace A with `project_uuid` of workspace B returns only workspace A broadcasts. |
| AC-5 | Each filter and `limit`/`offset` are exercised and the returned subset, `count`, `next`, and `previous` are asserted. |
| AC-6 | Invalid `start_date`, invalid `end_date`, `start_date` after `end_date`, and non-integer `id` each return `400` with an error on the offending field. |
| AC-7 | Result item keys and the `statistics` and `template` sub-objects are compared against the internal endpoint item shape, including the no-statistics, missing-template, and no-creator cases. |
| AC-8 | `assertNumQueries` gives the same count for a page with 1 item and a page with several items. |
| AC-9 | `test_root` and `test_explorer` assert the new entry; the docs page (no `.json` suffix) renders with `200`. |
| AC-10 | Existing `TestInternalBroadcastStatistics` tests stay green without modification. |

Failure paths covered: missing credentials, invalid credentials, non-member user, cross-workspace access, unknown project in JWT, each invalid filter.

## Constitution Alignment

- **I. Version Control and Review**: Delivered through a pull request from `feat/broadcasts-statistics-public-api`, gated by `.github/workflows/ci.yml` and review.
- **II. Security and Secrets**: No secrets added. Authentication and permissions are reused from `BaseAPIView` (API Key, Basic, session, Connect session, JWT); no new authentication or cryptography dependency. Least privilege: a dedicated read-only permission scoped to this endpoint, so opening it to every workspace role does not widen access to `broadcasts.json` or `whatsapp_broadcasts.json`.
- **III. Observability**: No new logging. The endpoint relies on the existing request logging and exception handler; no personal data is logged.
- **IV. Versioned Contracts**: Additive change to the public DRF surface under `temba/api`: a new endpoint, no change to existing ones. The internal endpoint is preserved (FR-014). Released in 3.105.0 (MINOR). No migration file: the new permission is created and assigned to groups by Smartmin's `post_migrate` sync, which runs on every deploy's `migrate`. No Courier or Mailroom version dependency.
- **V. Specification Traceability**: Engineering origin; the spec opens with `## Origin Without Product Spec`, and each acceptance criterion maps to a test in the Test Strategy.
- **VI. No Silent Divergence**: Not applicable, no product spec.
- **VII. Commit Messages**: Conventional Commits, atomic (spec, endpoint with tests, changelog).
- **VIII. Changelog Maintenance**: `WENI-CHANGELOG.md` entry under 3.105.0: `feat:` bullet that states the new externally reachable endpoint and its authentication methods.
- **IX. Never Trust the Client**: Query parameters are validated by a DRF serializer at the boundary (FR-007). Authorization is enforced server-side for every request, and the workspace comes from the credentials, not from a client-supplied parameter, for API Keys (FR-004). The view stays thin; no new business logic.
- **X. Fail Gracefully and Predictably**: Invalid input returns `400` with a field error, unauthorized access `403`, unsupported methods `405`. No new external dependency call. Today a non-integer `id` on the internal endpoint can raise a server error; the public endpoint does not.
- **XI. Bounded Retry Over REST**: Not applicable, no outbound REST call.
- **XII. Scalability and Peak Load**: Stateless view; reads from the read-only replica; constant queries per page; peak declared in Peak Load.
- **XIII. Diagnosable Errors**: Unexpected errors reach Sentry through the existing integration with the request context already attached; no personal data added.
- **XIV. Tests Exercise Flows**: End-to-end request tests for success and every failure path listed in Test Strategy.
- **XV. Explicit Over Clever**: Page size limits come from the existing `DefaultLimitOffsetPagination`; no new inline meaningful literals.
- **XVI. Contained Changes**: Only the new endpoint, its serializers, URL, root and explorer entries, the new permission in settings, tests, and changelog. The shared internal serializer gains two loading hooks (`load_statistics`, `load_template`) whose default implementation is the previous inline code, so the internal endpoint's behavior and existing role permissions are not modified.
- **Cycle choice**: The constitution says SDD Full SHOULD be used when a public contract listed in Principle IV changes. This change adds a new public endpoint, but it is additive, confined to `temba/api` plus a permission entry in settings, needs no migration, and needs no Courier or Mailroom coordination. SDD Lite was chosen explicitly by the requester. If implementation reveals a breaking change or a cross-app impact, the spec is promoted to SDD Full with `/speckit.plan`.

## Implementation Notes

These notes replace `plan.md` in the Lite cycle.

- **Location**: new subpackage `temba/api/v2/broadcasts_statistics/` (`views.py`, `serializers.py`, `tests.py`), following `elasticsearch/` and `templates/`. A subpackage is needed because the read serializer subclasses the internal serializer, which itself imports `temba/api/v2/serializers.py`; defining it there would create an import cycle.
- **View**: `BroadcastsStatisticsEndpoint(BaseAPIView)` in `temba/api/v2/broadcasts_statistics/views.py`. `permission = "msgs.broadcast_statistics_api"`, `model = Broadcast`, default `throttle_scope` (`v2`). Inheriting `BaseAPIView` gives the authentication classes, `SSLPermission`, `HasValidJWT | APIPermission`, workspace resolution from credentials, the read-only connection in `get_queryset`, and `405` on `OPTIONS`.
- **Permission**: add `"statistics_api"` to `PERMISSIONS["msgs.broadcast"]` in `temba/settings_common.py`, producing the codename `broadcast_statistics_api`. Administrators, Editors, and Marketing receive it through their existing `msgs.broadcast.*` wildcard; add `"msgs.broadcast_statistics_api"` explicitly to Agents, Viewers, and Surveyors in `GROUP_PERMISSIONS`. `msgs.broadcast_api` is left untouched, so Viewers and Surveyors still cannot reach `broadcasts.json` or `whatsapp_broadcasts.json`.
- **GET flow**: when there is no `format` suffix, return an empty response so the docs page does not query (same behavior as `ListAPIMixin`). Otherwise validate query params with a query serializer, filter `is_bulk_send=True` plus the filters, order by `-created_on, -id`, paginate with `DefaultLimitOffsetPagination`, and serialize.
- **Query serializer**: `BroadcastsStatisticsQuerySerializer` in the subpackage, validating `start_date`, `end_date` (ISO 8601 date or datetime), `name`, `id` (integer), and `start_date <= end_date`. Validation errors go through the existing exception handler as `400`.
- **Read serializer**: `BroadcastStatisticsReadSerializer` subclasses `BroadcastWithStatisticsSerializer` so the item shape stays identical. The internal serializer gets two hooks, `load_statistics(obj)` and `load_template(template_id)`, defaulting to the previous inline queries; the subclass overrides them to read statistics from a prefetch ordered by `pk` (same record `first()` returns today) and templates from one lookup per page, scoped to the caller's workspace, passed in serializer context. Queryset uses `select_related("created_by")` and prefetches `groups` and `statistics`.
- **URL**: `url(r"^broadcasts_statistics$", BroadcastsStatisticsEndpoint.as_view(), name="api.v2.broadcasts_statistics")` in `temba/api/v2/urls.py`, inside the block passed to `format_suffix_patterns`, so `.json` is supported. Underscore naming follows the public v2 convention (`whatsapp_broadcasts`, `contact_templates`).
- **Docs**: docstring with fields, filters, example request and response; `get_read_explorer` with the parameters; entries in `RootView` and `ExplorerView`.
- **Changelog**: `feat:` bullet under `3.105.0` in `WENI-CHANGELOG.md` (open, not yet tagged).
- **Tests**: `BroadcastsStatisticsEndpointTest(APIJSONMixin, TembaTest)` disables `ATOMIC_REQUESTS` like `APITest`, and wraps requests in `mockReadOnly` because the read-only alias is a separate connection in tests.

## Assumptions

- Read access follows the internal endpoint: any workspace role may read broadcast statistics (confirmed by the requester for Viewers; Surveyors included for the same parity). A dedicated permission is used instead of `msgs.broadcast_api` because granting the latter to Viewers and Surveyors would also open `broadcasts.json` and `whatsapp_broadcasts.json` to them.
- Viewers cannot create API Keys (`APIToken.ROLE_GRANTED_TO`), so Viewer access is through a Django session or a Connect session token. This is existing platform behavior and is not changed here.
- The JWT trust model of the public v2 API is kept as is after SEC-05: any JWT signed with the configured key is accepted, and the workspace comes only from its tenant claims.
- Exposing `created_by` (creator e-mail) to credentials of the same workspace is acceptable, since the internal endpoint already returns it and it is limited to the caller's own workspace.
- Limit/offset pagination with `count` is kept instead of the cursor pagination used by most public list endpoints, so the response matches the internal endpoint (SC-004). `EventsV2Endpoint` is a precedent of a public `.json` endpoint with limit/offset.
- Deprecating or removing the internal endpoint is out of scope; see Coexistence with the Internal Endpoint.
- The monthly summary endpoint (`/api/v2/internals/broadcasts-statistics-stats`) and the groups stats endpoint stay internal-only in this change.
