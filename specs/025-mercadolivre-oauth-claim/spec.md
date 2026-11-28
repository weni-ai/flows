# Engineering Specification: Connect a Mercado Livre seller to Flows (OAuth claim)

**Repository**: weni-ai/flows — backend

**Feature Branch**: `feat/meli-oauth`

**Created**: 2026-11-27

**Status**: Planned (spec, plan and tasks analyzed, ready for implementation)

**Input**: User description: "Connect a Mercado Livre seller to Flows with an OAuth claim. The claim page offers Mercado Livre. The project admin authorizes the seller account at Mercado Livre with the Authorization Code grant and PKCE S256, run on the server. The channel is created only after Mercado Livre confirms the seller. The channel address is the seller id, its name is the nickname, and the token grant is kept in the channel config. Out of scope: refresh job, reconnect, disconnect, switches as screens, and everything in Courier and Mailroom."

**Suggested cycle**: SDD Full. The change adds a claim flow that stores third-party tokens, adds a settings contract and a channel config contract that Courier reads (Principle IV).

**Source**: "Integração Mercado Livre — desenho técnico e tasks", Flows task RP-03 (phase F1, post-sale pilot). It builds on `specs/024-mercadolivre-channel` (RP-01, RP-02, RP-06 and RP-07), already implemented in this repository, and it depends on FND-01 (the application in the Mercado Livre DevCenter) to be exercised against the real service.

## Origin Without Product Spec

- Product Spec: none
- Problem: a project cannot connect its Mercado Livre (ML) seller. The channel type `ML` exists, but nothing creates it from the interface, and a plain "type the seller id" form would let any organization take a seller it does not own. The rule of one active channel per seller is platform-wide, so a seller held by the wrong organization blocks the real owner.
- Acceptance criteria:
  - AC-1: A project admin who is the ML seller administrator completes the flow and gets one active `ML` channel whose address is the seller id confirmed by ML and whose name is the nickname.
  - AC-2: The channel is created only after the token exchange and the seller confirmation succeed. Any earlier failure creates no channel.
  - AC-3: The `state` is single use and short lived, belongs to the org and user that started it, and a replayed, expired, unknown or foreign `state` is rejected without calling ML.
  - AC-4: PKCE S256 is always used, and the verifier never leaves the server.
  - AC-5: A collaborator who is not the seller administrator (`invalid_operator_user_id`) sees an error that asks for the administrator, and no channel is created.
  - AC-6: A seller that already has an active channel is rejected with the conflict error of feature 024 (`ChannelAddressConflict`), which this feature shows as its own message and which names no other organization or user.
  - AC-7: Tokens and the client secret never appear in logs, error messages, Sentry events, redirects or pages. Errors carry only opaque identifiers.
  - AC-8: Only a user who may create channels in the org can start the flow or finish it.

## Scope in This Repository

**This repository implements**:

- The claim view for the `ML` type and its place on the channel claim page (blurb, icon, a warning that the account must be the seller administrator).
- The start endpoint and the callback endpoint, with one fixed callback URL.
- The attempt store (state, PKCE verifier, org, user) with a short lifetime and single use.
- The token exchange and the seller confirmation call, with a timeout and no retry loop.
- Channel creation with the token grant in the channel config.
- Settings for the ML application (client id, client secret, redirect URI), read from the environment.
- Error handling for the cases listed in the edge cases.
- Tests for each acceptance criterion, one `feat` bullet in `WENI-CHANGELOG.md` and locale strings for EN, ES, PT and RO.

**Out of scope here**:

- Token refresh job, the "needs reconnect" state, send suspension and the merchant alert (RP-04).
- Reconnect, disconnect with revoke at ML, and the `post_sale_enabled` and `pre_sale_enabled` switches as screens (RP-05).
- Copying ML context into outbound messages (RP-08).
- Anything in Courier or Mailroom, including webhook handling and reading the tokens.
- Creating the ML application, the test seller and the test buyer (FND-01 to FND-03).
- Pre-sale behavior (F2). The same channel serves it later.
- Encrypting the tokens at rest beyond what the channel config already does for other channel types.
- Other ML countries. Only the Brazil authorize address is used.

## Current State

- Feature 024 registered the channel type `ML` (`temba/channels/types/mercadolivre/`), the `mercadolivre` URN scheme, the seven `ml_*` contact fields and a database rule of one active `ML` channel per address, across all organizations. `Channel.create` returns `ChannelAddressConflict` (code `address_conflict`) for a second one.
- The `ML` type has no claim view, so `has_claim_view()` is false and the claim page does not list it. `views.py` holds only a docstring that says the claim view arrives with this feature.
- `ChannelType.activate` of the `ML` type creates the seven contact fields after the channel exists. It makes no external call.
- The Outlook email claim (`temba/channels/types/email/outlook.py` and `views.py`) is the closest precedent in this repository for a server-side OAuth Authorization Code grant with PKCE S256:
  - The start step creates a one-time attempt in the cache, keyed by a random `state`, with org id, user id and the PKCE verifier, and a lifetime of 900 seconds.
  - The callback pops the attempt (single use), checks that org and user match, exchanges the code with a 10 second timeout, creates the channel and stores the tokens in the channel config.
  - The views use the permission `channels.channel_claim` through `OrgPermsMixin`.
  - Provider errors are mapped to short user messages, and failures are logged with opaque org and user identifiers and reported to Sentry without personal data.
  - The client id and secret come from environment settings (`APP_MICROSOFT_CLIENT_ID`, `APP_MICROSOFT_CLIENT_SECRET`), and the claim page offers the OAuth path only when the client id is set.
- `Channel.name` allows 128 characters. `Channel.address` allows 255.
- The channel claim page lists only channel types that have a claim view, and the claim view of a type is a class registered through `claim_view` on the type (see `ClaimViewMixin` in `temba/channels/views.py`).
- The v2 API serializers do not mention the channel `config` (a search of `temba/api/v2/serializers.py` finds no use of it), and the `ML` type has `show_config_page = False`. Other surfaces are checked in planning.
- The ML application, its client id, client secret and registered redirect URI do not exist in any environment yet (FND-01).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The seller administrator connects the seller (Priority: P1)

A project admin opens the channel claim page, picks Mercado Livre and sees that the account used must be the administrator of the seller account. They continue, sign in at ML, approve the application, and come back to Flows. Flows confirms the seller with ML and creates the channel. The project now has one active `ML` channel for that seller.

**Why this priority**: This is the only way to create the channel from the interface. Without it the work of feature 024 cannot be used.

**Independent Test**: With ML mocked, start the flow as a channel admin, return with a valid code and state, and check that one active `ML` channel exists with the confirmed seller id as address, the nickname as name and the grant in its config.

**Acceptance Scenarios**:

1. **Given** the ML application is configured and the user may create channels, **When** the user opens the claim page, **Then** Mercado Livre is offered with the note that the account must be the seller administrator.
2. **Given** the user starts the connection, **When** Flows redirects, **Then** the redirect goes to the ML authorize address with the client id, the fixed redirect URI, a `state`, a PKCE S256 challenge and the scopes `offline_access read write`, and the redirect contains no verifier, no secret and no org or user data.
3. **Given** ML returns a valid code and the `state` of this user and org, **When** Flows finishes the connection, **Then** the code is exchanged, the seller is confirmed, and one active `ML` channel is created with the seller id as address, the nickname as name, and the access token, refresh token and expiry in its config.
4. **Given** the channel was created, **When** the flow ends, **Then** the user lands on the new channel page, the seven `ml_*` fields exist (feature 024) and the page shows no token.
5. **Given** the seller confirmed by ML, **When** the channel is created, **Then** the address is the `user_id` that ML returned for the token and the `/users/me` answer agrees with it.

---

### User Story 2 - The attempt cannot be hijacked or replayed (Priority: P1)

The return from ML is a request that anyone can try to forge or repeat. The attempt must belong to the org and user that started it, must work once, and must expire.

**Why this priority**: The channel holds a grant to a seller account, and the platform-wide rule means a wrongly created channel blocks the real owner. This is the security core of the feature.

**Independent Test**: Start an attempt, then return with a replayed `state`, an expired `state`, an unknown `state`, and a `state` started by another user or org. Check that each is rejected before any call to ML and that no channel exists.

**Acceptance Scenarios**:

1. **Given** a `state` already used, **When** it comes back again, **Then** it is rejected without a call to ML.
2. **Given** a `state` older than its lifetime, **When** it comes back, **Then** it is rejected without a call to ML.
3. **Given** a `state` that was never issued, or a missing `state` or `code`, **When** it comes back, **Then** it is rejected without a call to ML.
4. **Given** a `state` started by user A in org X, **When** user B, or the same user acting in org Y, finishes it, **Then** it is rejected without a call to ML.
5. **Given** two returns with the same `state` at the same time, **When** both run, **Then** at most one reaches ML and at most one channel is created.
6. **Given** the PKCE verifier, **When** the start and the callback run, **Then** the verifier exists only on the server (in the attempt) and is sent to ML only in the code exchange.

---

### User Story 3 - A failed connection says what to do and leaves nothing behind (Priority: P1)

Connections fail for ordinary reasons: the signed-in ML user is a collaborator and not the administrator, the user cancels at ML, the seller is already connected, or ML is down. Each failure must give a clear message and create nothing.

**Why this priority**: Most first attempts in a real project will hit one of these, especially the collaborator case. A vague error here is a support ticket.

**Independent Test**: For each failure, run the flow with ML mocked to fail in that way and check the message shown, that no channel and no contact field was created, and that no token reached any log.

**Acceptance Scenarios**:

1. **Given** the ML user is a collaborator, **When** ML answers `invalid_operator_user_id` (on the return or in the token exchange), **Then** the user sees a message that asks for the seller administrator and no channel is created.
2. **Given** the user cancels at ML, **When** ML returns `access_denied`, **Then** the user goes back to the claim page with a message that the connection was not completed and can try again.
3. **Given** the seller already has an active channel in any organization, **When** the connection finishes, **Then** the user sees the "already connected" message of this feature (the callback maps `ChannelAddressConflict` to it), which names no organization, user or channel, and no second channel exists.
4. **Given** the code exchange fails, the answer is not valid, or ML does not answer in time, **When** the connection finishes, **Then** the user sees a message that ML did not complete the sign-in, the failure is reported with opaque identifiers, and no channel is created.
5. **Given** the exchange works but the seller confirmation fails or disagrees with the token `user_id`, **When** the connection finishes, **Then** no channel is created.
6. **Given** a failure in any step after the attempt is taken, **When** the user is sent back to the claim page, **Then** the attempt is already consumed, so a later return with the same `state` is rejected.

---

### User Story 4 - Tokens stay private and the option appears only when it can work (Priority: P2)

The channel config holds a grant to a third-party account. It must not leak through any page, API or log, and the claim option must not appear in an environment where the ML application is not configured.

**Why this priority**: The first part protects a real account. The second avoids a button that fails in environments without the ML application, such as staging before FND-01.

**Independent Test**: Create a channel through the flow and look for the token and the client secret in every response a channel admin can reach, in the captured logs and in the captured Sentry events. Open the claim page with and without the ML settings.

**Acceptance Scenarios**:

1. **Given** an `ML` channel with a grant in its config, **When** the channel page, the channel list and the v2 API channel endpoints are requested, **Then** no response contains the access token, the refresh token or the client secret.
2. **Given** the ML client id or client secret is not configured, **When** the claim page opens, **Then** Mercado Livre is not offered, and a direct call to the start endpoint sends the user back to the claim page without a redirect to ML.
3. **Given** a user without the permission to claim channels, **When** they call the start or the callback endpoint, **Then** access is denied.
4. **Given** a successful or a failed connection, **When** the logs and error reports are inspected, **Then** they contain opaque org, user and correlation identifiers and the ML error code, and never a token, the client secret, the code, the verifier or the nickname.

---

### Edge Cases

- **Seller already connected in the same organization**: the conflict error is shown. Replacing the grant of an existing channel is reconnect (RP-05) and is not done here.
- **Nickname**: the channel name is the nickname. If ML gives none, the seller id is the name. A name longer than the channel name limit (128) is cut to that limit.
- **Seller id from two answers**: the `user_id` of the token answer and the id of the seller confirmation must be the same. If they differ, the connection is refused.
- **Missing refresh token**: if ML does not return a refresh token, the connection is refused, because without it the grant cannot be kept (the scope `offline_access` was asked).
- **Token lifetime**: the config keeps an absolute expiry computed from `expires_in` at the moment of the exchange, not the relative value.
- **Released channel**: a released `ML` channel keeps no token in its config. The seller can be connected again, because released channels do not count for the rule of feature 024.
- **Failure in the activation of the new channel**: the contact fields are created by the type activation (feature 024), inside `Channel.create`. The activation does not raise when the organization is at its field limit (it logs and skips), and the channel stays. Any other exception from the activation makes `Channel.create` release the new channel and re-raise. The callback treats that as a failed connection (`channel_invalid`, reported, one message), and no active channel remains. The release clears the tokens from the released row (FR-027).
- **Redirect URI**: it is one fixed value from configuration, with no query string, and it is not derived from the request host. All variable data lives in the attempt, not in the URL.
- **Browser back and double click**: starting twice creates two attempts, and only the last return that matches finishes. Each attempt works once.
- **User session ends in the middle**: the callback needs a signed-in user. Without one the user is sent to sign in, with the callback address (and its query) as the return address. If the same user signs in and the attempt is still valid, the return completes the connection. A different user who signs in is rejected as foreign, and the old attempt is not completed by anyone else.
- **ML answers 4xx or 5xx on the confirmation call**: no channel is created, the failure is reported, and the user can try again.
- **Concurrent connections for the same seller from two organizations**: the database rule of feature 024 lets one win. The other gets the conflict error.
- **Reserved characters in the ML error text**: provider messages are not shown to the user as they come. Only known codes map to messages, and unknown codes get a generic message.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `ML` channel type MUST have a claim view, so it is listed on the channel claim page and reachable through its claim URL, with a blurb and the existing default icon.
- **FR-002**: The claim page MUST tell the user, before any redirect, that the Mercado Livre account used must be the administrator of the seller account.
- **FR-003**: The claim page MUST offer Mercado Livre, and the start endpoint MUST redirect to ML, only when the ML client id, client secret and redirect URI are configured. Otherwise the start endpoint MUST send the user back to the claim page without a redirect.
- **FR-004**: The start endpoint MUST create one attempt that holds the org id, the user id and a PKCE verifier, with a random unguessable `state` as key and a short, named lifetime. The start endpoint MUST NOT put the verifier, the secret or any org or user data in the redirect.
- **FR-005**: The redirect to ML MUST be the Brazil authorize address with `response_type=code`, the client id, the fixed redirect URI, the `state`, a `code_challenge` computed with S256 and the scopes `offline_access read write`.
- **FR-006**: The callback endpoint MUST consume the attempt exactly once and MUST reject, without any call to ML, a missing, unknown, expired, replayed or foreign `state`, and a missing `code`. Foreign means started by another user or for another org.
- **FR-007**: The attempt MUST be single use even when two returns with the same `state` arrive at the same time.
- **FR-008**: The callback MUST exchange the code at the ML token address with the grant type `authorization_code`, the client id, the client secret, the code, the redirect URI and the PKCE verifier, with an explicit timeout and no retry.
- **FR-009**: The callback MUST accept the answer only when it has an access token, a refresh token, a lifetime and a seller `user_id`. Any other answer MUST be a failed connection.
- **FR-010**: The callback MUST confirm the seller with the ML account call using the new access token, and MUST refuse the connection when the confirmed seller id differs from the `user_id` of the token answer. It MUST read the nickname from that answer.
- **FR-011**: The callback MUST create the channel only after FR-008 to FR-010 succeed, with `Channel.create`, type `ML`, the seller id as a numeric string for address, the nickname for name (seller id when there is no nickname, cut to the name limit), and the grant in the channel config.
- **FR-012**: The channel config MUST hold the access token, the refresh token, the absolute expiry and the state of the grant, under the key names fixed in the contract, and MUST NOT hold the client id or the client secret.
- **FR-013**: The channel config MUST hold the switches `post_sale_enabled` and `pre_sale_enabled`, both false, so that no inbound processing happens until a merchant turns them on (RP-05).
- **FR-014**: A seller that already has an active `ML` channel MUST be rejected with the conflict error of feature 024 (`ChannelAddressConflict`). The callback MUST map it to its own "already connected" message, which names no organization, user or channel.
- **FR-015**: A collaborator that is not the seller administrator (`invalid_operator_user_id`, on the return or in the token exchange) MUST get a message that asks for the seller administrator, and no channel MUST be created.
- **FR-016**: A cancelled authorization (`access_denied`) MUST send the user back to the claim page with a message that the connection was not completed. Any other provider error MUST map to a known message or to a generic one. Provider error text MUST NOT be shown to the user as it comes.
- **FR-017**: Every failure after the attempt is taken MUST leave the attempt consumed, leave no active channel, create no contact field when the failure happens before the channel is created, and send the user back to the claim page with one message. A return with an unknown, expired or foreign `state` takes no attempt: an unknown or expired one has none to consume, and a foreign one MUST leave the attempt of its owner usable until it expires.
- **FR-018**: The start and the callback endpoints MUST declare an explicit permission, `channels.channel_claim`, and MUST deny a user without it (Principle XVII). The callback MUST also require the signed-in user to be the one who started the attempt.
- **FR-019**: Tokens, the client secret, the code and the verifier MUST NOT appear in logs, error messages, Sentry events, redirects, pages or API answers. Failures MUST be logged and reported with opaque org id, user id, correlation id and the ML error code only, and MUST NOT carry the nickname or the seller id.
- **FR-020**: No page, list, export or v2 API answer of the channel MUST return the `config` grant.
- **FR-021**: The settings for the ML application MUST be read from the environment and MUST have empty defaults. No secret MUST be in the repository.
- **FR-022**: All calls to ML MUST have an explicit timeout, and a timeout or a transport error MUST be a failed connection, not a crash.
- **FR-023**: All the identifiers of this feature (authorize address, token address, account address, scopes, lifetime of the attempt, timeout, config keys, state values and error codes) MUST be named constants.
- **FR-024**: The type MUST keep the layout of the other types (`type.py`, `views.py`, `tests.py`, `__init__.py`), with the OAuth logic outside the view in a module of the type, as the Outlook flow does.
- **FR-025**: `WENI-CHANGELOG.md` MUST gain one `feat` bullet under the next unreleased version heading. A released heading MUST NOT be extended. `CHANGELOG.md` MUST NOT be rewritten.
- **FR-026**: New user-facing strings MUST be added for EN, ES, PT and RO.
- **FR-027**: Releasing an `ML` channel MUST remove the access token and the refresh token from its config, without any call to ML. Revoking the grant at ML is disconnect (RP-05) and is not done here.

### Key Entities

- **Connection attempt**: a short-lived record of one start. It holds the org, the user and the PKCE verifier, and it is found by a random `state`. It works once.
- **ML channel**: the channel of feature 024. After this feature its config holds the grant for one seller and the two switches.
- **Seller grant**: the access token, the refresh token, the absolute expiry and the state of the grant of one seller, kept in the channel config.
- **ML application settings**: the client id, client secret and redirect URI of the one VTEX application that serves every seller. They live in the environment and never in a channel.

## Fixed Identifiers

These values are decided here and read by Courier and by the later RP-04 job.

| Item | Value |
|---|---|
| Authorize address | `https://auth.mercadolivre.com.br/authorization` (Brazil) |
| Token address | `https://api.mercadolibre.com/oauth/token` |
| Seller confirmation call | `GET https://api.mercadolibre.com/users/me` with the access token |
| Grant type | `authorization_code`, with PKCE `S256` |
| Scopes | `offline_access read write` |
| Channel address | The `user_id` returned by ML, as a numeric string |
| Channel name | The ML nickname |
| Permission | `channels.channel_claim` |
| Config keys (fixed here, version 1 of the contract, pending confirmation by Courier CO-02 and RP-04) | `access_token`, `refresh_token`, `expires_at` (absolute UTC time), `oauth_provider` (`mercadolivre`), `oauth_status` (`active`), `post_sale_enabled` (false), `pre_sale_enabled` (false) |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of runs where the seller administrator completes the flow, exactly one active `ML` channel exists for that seller afterwards, with the confirmed seller id as address.
- **SC-002**: In 100% of runs with a replayed, expired, unknown, missing or foreign `state`, no call to ML is made and no channel is created.
- **SC-003**: In 100% of runs where ML fails in any step (collaborator, cancel, bad answer, timeout, seller mismatch), no channel and no contact field is created, and the user sees exactly one message that says what to do.
- **SC-004**: When two returns with the same `state` arrive at the same time, at most one reaches ML and at most one channel exists, in 100% of repeated runs.
- **SC-005**: Across the channel page, the channel list, the v2 API channel endpoints, the captured logs and the captured error reports of a full connection, 0 occurrences of the access token, the refresh token, the client secret, the code or the verifier.
- **SC-006**: In an environment without the ML application settings, 0 users are sent to ML, and the claim page does not offer Mercado Livre.
- **SC-007**: 100% of calls to ML in this feature have a timeout, and a timeout always ends as a failed connection with a message, never as a server error.
- **SC-008**: A user without the permission to claim channels is denied on both endpoints in 100% of tests.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|---|---|
| AC-1 connection works | A full-flow test with ML mocked: claim page, start, return with a valid code and state, then check the channel (type, address, name, config keys and expiry), the redirect to the channel page and the seven fields. |
| AC-2 channel only after success | Tests where the exchange fails, the answer lacks a refresh token, the confirmation fails and the ids differ. Each asserts no channel and no field. |
| AC-3 state rules | Tests for replayed, expired, unknown, missing and foreign `state` (other user, other org), each asserting that the ML mock was not called. A non-atomic test with two simultaneous returns for one `state` asserts at most one ML call and one channel. |
| AC-4 PKCE | Test that the redirect carries a S256 challenge and no verifier, and that the verifier sent in the exchange is the one whose challenge was sent, and that the verifier never appears in a redirect or page. |
| AC-5 collaborator | Tests of `invalid_operator_user_id` on the return and in the exchange, asserting the message that asks for the administrator and no channel. |
| AC-6 seller conflict | Test with an existing active channel in the same org and in another org, asserting the conflict message names neither organization nor user, and no second channel. |
| AC-7 no secrets | Tests that capture logs and error reports of success and failure runs and assert the absence of token, secret, code and verifier. Tests that the channel page, list and v2 API answers do not contain the config grant. |
| AC-8 permission | Tests that a user without `channels.channel_claim` is denied on the start and the callback, and that a user who did not start the attempt cannot finish it. |
| Availability | Test that the claim page and the start endpoint behave as in FR-003 with and without the ML settings. |
| Release | Test that releasing a connected channel leaves no access token and no refresh token in its config and makes no call to ML (FR-027). |

**Flow coverage**: the complete use case is a channel admin connecting a seller and getting the channel. The state, failure, privacy and availability cases are sibling tests, with their failure paths each covered.

**Gates**: `poetry run coverage run manage.py test`, clean `./code_check.py`, green `.github/workflows/ci.yml`. Tests use `TembaTest`, and `TembaNonAtomicTest` only for the simultaneous-return case. ML is always mocked, and no test calls the real service. No new `# pragma: no cover`.

## Assumptions

- **State (decided in planning, research R3)**: the `state` is a random opaque value that keys a server-side attempt in the shared cache, as in the Outlook flow, and it carries no data. This gives the same protection as the signed `state` in the design document (org, user and nonce bound to the request) without a signing key, and it is single use by construction. The attempt lifetime is a named constant, 900 seconds as in Outlook.
- **Config contract (decided in planning, research R7, open with Courier CO-02)**: the key names and the absolute expiry format are fixed in `contracts/claim-and-config.md` as version 1. Only the Courier confirmation is pending, and a change of names would touch the constants of the module only. `oauth_provider` and `oauth_status` reuse the names and the `active` value used by the Outlook config, so the later "needs reconnect" state (RP-04) can use the same value. The expiry is an absolute UTC time written as RFC 3339, which Courier can parse.
- **Switches (decided in planning, research R8)**: the channel is created with both switches false, as the design document says. Until RP-05 gives a screen to turn them on, turning them on needs an operator change of the channel config. This is a known gap of this slice.
- **Token exposure (checked in planning, research R13)**: the channel page, the channel list, the v2 API and the internal channel endpoints do not return the grant, and a privacy test guards each of them.
- **Availability (decided in planning, research R9)**: the option is offered when the ML application settings are present, as the Outlook option is offered when its client id is present. No separate beta flag is added.
- **Seller already connected in the same organization**: the conflict error is enough for this slice. Replacing the grant is RP-05.
- **Only Brazil**: the authorize address is the Brazil one, as the design document says for the MVP. The seller id and the nickname come from the ML account call, and no site filter is applied.
- **Redirect URI**: it is one value in configuration that must match the one registered in the ML application, character by character. It is not built from the request.
- **Who may connect**: Flows checks the Flows permission `channels.channel_claim`. Whether the ML user is the seller administrator is decided by ML, and Flows reacts to the answer.
- **The ML application exists in test only**: until FND-01, the whole feature is tested with ML mocked and nothing in it calls the real service.
- **Tokens at rest**: the grant is stored in the channel config like the Outlook grant. Encrypting it is not in this slice.
- **Peak load (Principle XII)**: connecting a seller is a rare, human-triggered action, at most a few per minute across the platform. Each connection makes 2 calls to ML and 1 channel creation. The attempt lives in the shared cache with a short lifetime, not in process memory, so web processes stay stateless. The feature adds no queue, process or migration.
- **Contracts (Principle IV)**: the settings, the channel config keys and the redirect URI are new identifiers that Courier and the RP-04 job read later. No existing endpoint, channel config or event payload changes. The release note names the Courier and Mailroom versions that read the config once they exist.
- **Security (Principles II, IX, X, XIII and XVII)**: secrets come from the environment. Everything from ML and from the browser (`state`, `code`, error codes, answers) is validated at the server boundary. Calls to ML have timeouts. Errors carry opaque identifiers only. Both endpoints declare an explicit permission and are not open endpoints.
