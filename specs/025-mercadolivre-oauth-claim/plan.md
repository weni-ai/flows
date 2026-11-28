# Implementation Plan: Connect a Mercado Livre seller to Flows (OAuth claim)

**Branch**: `feat/meli-oauth` | **Date**: 2026-11-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/025-mercadolivre-oauth-claim/spec.md`

**Cycle**: SDD Full. The change adds an authentication flow with an external provider, stores credentials in the channel config and fixes a config contract that Courier and the later refresh job read.

## Summary

The `ML` channel type of feature 024 gets its claim. A channel admin opens the claim page, starts the connection with a POST, signs in at Mercado Livre and comes back to a callback. Flows exchanges the code with PKCE, confirms the seller with the ML account call and only then creates the channel, with the seller id as address, the nickname as name and the grant in the channel config.

Technical approach, from [research.md](research.md):

- **Module**: `oauth.py` in the type directory holds the attempt store, the two ML calls, the error type and the channel creation. `views.py` holds the claim view and two thin endpoints, `start` (POST) and `callback` (GET), both with `channels.channel_claim`.
- **Attempt**: a cache entry keyed by an opaque random `state`, with org, user and PKCE verifier, for 900 seconds. A second key written with `cache.add` makes the take atomic, so two simultaneous returns cannot both pass.
- **Redirect URI**: a setting, never built from the request.
- **Calls to ML**: token exchange and account confirmation with `requests`, a 10 second timeout and no retry. Any bad answer is one failure kind.
- **Config contract**: `access_token`, `refresh_token`, `expires_at` (RFC 3339 UTC), `oauth_provider`, `oauth_status`, `post_sale_enabled`, `pre_sale_enabled` ([contracts/claim-and-config.md](contracts/claim-and-config.md)).
- **Availability**: the type is listed only when the three ML settings are set.
- **Release**: `deactivate` removes the two tokens from the config, with no call to ML.
- **No migration, no new dependency.**

## Technical Context

**Language/Version**: Python `>=3.10,<3.12` (CI uses 3.11)

**Primary Dependencies**: Django `^3.2.6`, `requests` and `sentry_sdk` (both already used by the Outlook claim), Poetry. No new dependency.

**Storage**: the existing `Channel.config` for the grant, and the Django cache (Redis in production) for the attempt. No table, no migration.

**Testing**: Django test runner through `poetry run coverage run manage.py test`. `TembaTest` for the views, `TembaNonAtomicTest` for the simultaneous return. ML is mocked in the `oauth` module. No test calls the network.

**Target Platform**: Flows backend service (Linux, web processes and Celery workers, stateless). The attempt is in the shared cache, so any web process can serve the return.

**Project Type**: Web service (Django monolith, `temba/<app>/`).

**Performance Goals**: not a hot path. Each connection makes two outbound calls of at most 10 seconds each.

**Constraints**:
- The code is single use at ML, so no retry after the token call (FR-008).
- The redirect URI is one fixed string with no query (FR-004, edge case "Redirect URI").
- No token, secret, code or verifier in any log, report, page or answer (FR-019, FR-020).
- The connection fails closed: no channel and no contact field unless both calls are valid (FR-011, FR-017).
- The config key names are a contract with Courier CO-02 and RP-04.
- Scope is Flows only. No refresh, no reconnect, no disconnect, no screens for the switches, no change to Courier, Mailroom or the DevCenter.

**Scale/Scope**: one claim page, two endpoints, one module, three settings, one config contract.

### Peak Load (Principle XII)

Declared peak: a few connections per minute across the platform, each started by a person. Per connection: two cache writes at the start, two cache operations and two outbound HTTP calls at the return, and one channel insert. The attempt is in the shared cache with a lifetime, so memory is bounded by the starts of the last 15 minutes (a few hundred bytes each). The processes keep no local state, so adding web workers needs no change. The outbound calls run in the request, with a total worst case of about 20 seconds. This is acceptable for a human flow that happens once per seller, and it is the same shape as the Outlook claim. A worker pool problem would show as slow returns, not as lost data, because nothing is created before both calls end.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Before Phase 0

| Principle | Result | Note |
|---|---|---|
| I. Version control and review | Pass | Branch `feat/meli-oauth`, PR to `main` with green `ci.yml` |
| II. Security and secrets | Pass | Client id, secret and redirect URI come from the environment with empty defaults. The secret is used only in the code exchange. Tokens go only to the channel config |
| III. Observability | Pass | Fixed log messages with opaque ids and the safe ML error code. Unexpected failures are reported to Sentry |
| IV. Versioned contracts | Pass with note | The config keys are new and are read by Courier CO-02 and RP-04. They are listed in [contracts/claim-and-config.md](contracts/claim-and-config.md) and the PR names the dependency. Nothing existing changes |
| V. Specification traceability | Pass | Spec opens with `Origin Without Product Spec`. Each acceptance criterion maps to a test in Test Strategy |
| VI. No silent divergence | Not applicable | No product spec |
| VII. Commit messages | Pass | Atomic conventional commits, description of 50 characters or fewer |
| VIII. Changelog | Pass | One `feat` bullet in `WENI-CHANGELOG.md` under the next unreleased heading (FR-025) |
| IX. Never trust the client | Pass | `state` is checked against the server-side attempt, the seller id comes from ML and is checked twice, the ML error text is never shown |
| X. Fail gracefully | Pass | Explicit timeouts, no retry, every failure maps to one message and leaves nothing behind |
| XI. Bounded retry over REST | Not applicable | No REST propagation. The one retry rule, none, is stated in FR-008 |
| XII. Scalability and peak load | Pass | Declared above |
| XIII. Diagnosable errors | Pass | Opaque org id, user id, correlation id and ML error code. No nickname or seller id |
| XIV. Tests exercise flows | Pass | A full-flow test, the failure paths and a race test (see Tests) |
| XV. Explicit over clever | Pass | Named constants for every address, scope, key and value (FR-023). Comments state why |
| XVI. Contained changes | Pass with note | Edits are in the type directory, `settings_common.py`, the locale files and the changelog. The OAuth helpers of the Outlook type are not moved or changed. Two small helpers are repeated instead (see Risks) |
| XVII. Explicit, scoped authorization | Pass | Both endpoints declare `channels.channel_claim`. The callback also checks that the user started the attempt |
| Backend standards | Pass | Layout `type.py`, `views.py`, `tests.py`, `__init__.py`, plus `oauth.py`. `./code_check.py`. Locale strings for EN, ES, PT and RO |

No violation. No `NEEDS CLARIFICATION` marker remains in the spec.

### After Phase 1

| Principle | Result | Note |
|---|---|---|
| IV | Pass | The contract file fixes the keys, the types, the time format, the error codes and the settings. Courier CO-02 and RP-04 are the open consumers |
| IX | Pass | [research.md](research.md) R2 closes the replay window of the get-then-delete pattern with an atomic marker |
| XIV | Pass | [quickstart.md](quickstart.md) maps each scenario to a test and an expected result |
| XVII | Pass | Both endpoints and the claim view use one permission string, already used by every claim view |
| Others | Unchanged | No design decision changed an earlier result |

## Project Structure

### Documentation (this feature)

```text
specs/025-mercadolivre-oauth-claim/
├── plan.md                       # This file (/speckit-plan command output)
├── research.md                   # Phase 0 output
├── data-model.md                 # Phase 1 output
├── quickstart.md                 # Phase 1 output
├── contracts/
│   └── claim-and-config.md       # Phase 1 output
├── checklists/
│   └── requirements.md           # /speckit-specify output
└── tasks.md                      # Phase 2 output (/speckit-tasks command)
```

### Source Code (repository root)

```text
temba/
├── settings_common.py                          # APP_MERCADOLIVRE_CLIENT_ID, _CLIENT_SECRET, _REDIRECT_URI
└── channels/
    └── types/
        └── mercadolivre/
            ├── type.py                         # claim_view, get_urls, is_available_to, deactivate
            ├── oauth.py                        # NEW: constants, attempt, PKCE, ML calls, error, create channel
            ├── views.py                        # ClaimView, MercadoLivreStart, MercadoLivreCallback
            └── tests.py                        # new classes for the flow
templates/
└── channels/
    └── types/
        └── mercadolivre/
            └── claim.haml                      # NEW: notice, blurb and the start form
locale/
├── en_US/LC_MESSAGES/django.po                 # new strings
├── es/LC_MESSAGES/django.po
├── pt_BR/LC_MESSAGES/django.po
└── ro/LC_MESSAGES/django.po
WENI-CHANGELOG.md                               # one feat bullet
```

**Structure Decision**: a single Django project. The type keeps the layout of the other types, plus `oauth.py` for the logic as the Outlook claim has `outlook.py`. No shared file outside the type changes except the settings, the locale files and the changelog.

## Design by component

### `oauth.py`

- Named constants: authorize, token and account addresses, scopes, attempt prefix and lifetime, call timeout, config keys and values, error codes, the cap on the logged error code.
- `ConnectionFailure`: an exception with a `code` (one of the named codes), a user message key, and `report` (whether to send it to Sentry).
- `start_attempt(org, user) -> authorize_url`: creates `state` and verifier, stores the attempt, and returns the authorize address with the query of FR-005.
- `take_attempt(state, org, user) -> verifier`: reads the attempt, checks org and user, takes the `used` marker with `cache.add`, deletes the attempt, and returns the verifier. Every failed check raises `ConnectionFailure`.
- `exchange_code(code, verifier) -> grant`: the token call and the validation of its answer (FR-008, FR-009). Returns the tokens, the expiry and the seller id.
- `confirm_seller(grant) -> (seller_id, nickname)`: the account call and the comparison of ids (FR-010).
- `connect(org, user, state, code) -> Channel`: the sequence take, exchange, confirm and create. Creates the channel with `Channel.create` and the config of the contract. Maps `ChannelAddressConflict` to a `ConnectionFailure` without a report.
- Logging and reporting helpers: the safe error code filter and the Sentry scope, with the org id, user id, correlation id and error code.

### `views.py`

- `ClaimView(ClaimViewMixin, SmartFormView)`: renders the notice for the seller administrator, the blurb and a form that posts to `start`. When not configured, renders a notice and no button (FR-002, FR-003). The form has no fields, only the CSRF token.
- `MercadoLivreStart`: POST only. Checks the settings, calls `start_attempt`, returns a redirect to ML. If not configured, redirects to the claim page with a message.
- `MercadoLivreCallback`: GET only. Reads `state`, `code` and `error` from the query. A return with `error` and a valid attempt consumes the attempt and maps the code. Calls `connect`, and on success redirects to the channel page. Every `ConnectionFailure` becomes a message and a redirect to the claim page (FR-017).
- Both endpoints: `OrgPermsMixin`, `SmartView`, `View` and `permission = "channels.channel_claim"`, the same shape as `_OutlookView`.

### `type.py`

- `claim_view = ClaimView`, `claim_blurb` and `claim_view_kwargs` as needed.
- `get_urls()` returns the claim URL, `start` and `callback`.
- `is_available_to(user)` returns `(configured, configured)` (R9).
- `deactivate(channel)` removes the two tokens from `channel.config` and does nothing else (R12).
- `activate` and `clean_address` from feature 024 are not changed.

### `templates/channels/types/mercadolivre/claim.haml`

- Extends the claim form template. Shows the sentence about the seller administrator before the button, a button inside a POST form, and the "not available" notice when `configured` is false.

### `settings_common.py`

- The three settings (R15), next to the Outlook ones, with a comment that the secret is used only for the code exchange.

### Locale and changelog

- New strings (blurb, notice, button, the failure messages) in the four locales, `.mo` regenerated for ES, PT and RO. One `feat` bullet in `WENI-CHANGELOG.md` (R17).

### Tests

Mapped one-to-one with the spec Test Strategy and the scenarios in [quickstart.md](quickstart.md). They live in `temba/channels/types/mercadolivre/tests.py`, in new classes: start, callback (success), state rules, failures, privacy and release, and a non-atomic race test with two threads.

## Implementation risks

| Risk | Consequence | Handling |
|---|---|---|
| Two returns with the same `state` at the same time | Two token exchanges, one possibly accepted twice | `cache.add` marker (R2). A non-atomic test with a barrier asserts one channel and one rejected return |
| The test cache is not Redis | `cache.add` could behave differently | The tests run on the project settings. The marker uses only `add`, which has the same meaning on every Django backend |
| ML changes the error codes or the answer shape | A real failure shows the generic message | Unknown codes go to the generic path and to Sentry with the code. The map is one dictionary of named constants |
| The redirect URI at ML differs from the setting by one character | Every connection fails at ML | The quickstart lists the exact path to register. The start endpoint sends the setting value untouched |
| The ML account call is slow | The request holds a web worker for up to 20 seconds | Peak load is a few per minute. The timeout is a named constant. No retry |
| The switches are created `false` and there is no screen until RP-05 | A pilot seller receives nothing until an operator edits the config | Recorded in the contract and in the PR description for the pilot team |
| Two helpers repeat the Outlook ones (account id, correlation id) | Two copies to keep | Moving them to a shared place is outside this change (Principle XVI). A follow-up can unify them |
| `ChannelAddressConflict` message does not fit the claim page | The user sees a technical text | The callback maps the error to its own message (R6) |
| The same user starts in two tabs | Two attempts | Each works once. The last matching return wins, the other is rejected as a replay |

## Complexity Tracking

No Constitution Check violation. The one non-obvious choice is the second cache key for single use. It is the smallest change that gives FR-007 on the shared cache without a table or a Lua script, as explained in [research.md](research.md) R2.
