---

description: "Task list for the Mercado Livre OAuth claim in Flows"
---

# Tasks: Connect a Mercado Livre seller to Flows (OAuth claim)

**Input**: Design documents from `/specs/025-mercadolivre-oauth-claim/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/claim-and-config.md](contracts/claim-and-config.md), [quickstart.md](quickstart.md)

**Tests**: Included. The spec has a Test Strategy and constitution Principle XIV requires a full-flow test plus failure paths. In each story, write the tests of the story first and run them, then implement.

**Organization**: Tasks are grouped by user story. The stories edit the same files (`temba/channels/types/mercadolivre/oauth.py`, `views.py`, `type.py` and `tests.py`), so work them in the order below, not in parallel. The attempt store (T005) is built in Phase 2 because US1 needs it to run at all. US2 proves its rules at the endpoint level. If a US2 test fails, fix `take_attempt` in T005's code.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story the task serves (US1 to US4)
- Paths are relative to the repository root
- Test commands use the environment described in [quickstart.md](quickstart.md)

---

## Phase 1: Setup

**Purpose**: the configuration and the test helpers every later task uses.

- [ ] T001 [P] Add the three settings after the Outlook ones in `temba/settings_common.py`: `APP_MERCADOLIVRE_CLIENT_ID`, `APP_MERCADOLIVRE_CLIENT_SECRET` and `APP_MERCADOLIVRE_REDIRECT_URI`, each `os.environ.get(..., "")`. Add a comment that the secret is used only for the code exchange and that the redirect URI must equal, character by character, the one registered at ML (FR-021)
- [ ] T002 [P] In `temba/channels/types/mercadolivre/tests.py` add a test mixin `MercadoLivreOAuthTestMixin` (no test methods yet) with: `override_settings` values for the three settings (redirect URI `https://flows.example.com/channels/types/mercadolivre/callback`), `mock_token_answer(...)` and `mock_account_answer(...)` builders that return `requests`-like response objects (status, json), a helper that patches `requests.post` and `requests.get` in `temba.channels.types.mercadolivre.oauth` and returns both mocks, and `start_connection()` and `finish_connection(state, code)` helpers that call the two endpoints with the Django test client. The constants of the mixin (seller id `415458330`, nickname `SELLER_X`, token values) are module-level names

---

## Phase 2: Foundational (blocks all user stories)

**Purpose**: the `oauth.py` module core: constants, the failure type, the logging helpers and the attempt store.

**⚠️ CRITICAL**: no user story work can begin until this phase is complete.

- [ ] T003 Create `temba/channels/types/mercadolivre/oauth.py` with named constants (FR-023) and `ConnectionFailure` (FR-023, FR-024):
  - Addresses: `AUTHORIZE_URL`, `TOKEN_URL`, `ACCOUNT_URL`. Scopes `OAUTH_SCOPES = "offline_access read write"`. `ATTEMPT_KEY_PREFIX`, `ATTEMPT_LIFETIME_SECONDS = 900`, `CALL_TIMEOUT_SECONDS = 10`, `CHANNEL_NAME_MAX_LENGTH = 128`
  - Config keys and values: `CONFIG_ACCESS_TOKEN`, `CONFIG_REFRESH_TOKEN`, `CONFIG_EXPIRES_AT`, `CONFIG_OAUTH_PROVIDER`, `CONFIG_OAUTH_STATUS`, `CONFIG_POST_SALE_ENABLED`, `CONFIG_PRE_SALE_ENABLED`, `OAUTH_PROVIDER = "mercadolivre"`, `OAUTH_STATUS_ACTIVE = "active"`
  - Failure codes from [contracts/claim-and-config.md](contracts/claim-and-config.md) section 5 (`state_invalid`, `access_denied`, `invalid_operator_user_id`, `provider_error`, `exchange_failed`, `seller_mismatch`, `already_connected`, `channel_invalid`, `not_configured`)
  - `FAILURE_MESSAGES`: one dictionary from code to a `gettext_lazy` message, with the texts of that table
  - `ConnectionFailure(Exception)` with `code` and `report` (whether to send to Sentry). The `report` default comes from a named set of the codes that are reported
  - `is_configured()` returns true only when the three settings are non-empty (R9)
- [ ] T004 In `oauth.py` add the logging and reporting helpers (FR-019, Principle XIII), modeled on the helpers in `temba/channels/types/email/outlook.py` and not imported from it (the repetition is accepted, see the risks of the plan, because moving them to a shared place is outside this change):
  - `safe_error_code(value)`: returns the value only if it matches letters, digits, dot, dash and underscore and has at most 80 characters, else `"unknown"`
  - `account_id_for(org)` (project uuid as text, empty if none) and `correlation_id_for(request)` (`request.META["HTTP_X_REQUEST_ID"]`, else `request.META["HTTP_X_CORRELATION_ID"]`, else empty, as `correlation_identifier` in `outlook.py` does)
  - `report_failure(failure, org, user, request)`: logs a fixed message with org id, user id, correlation id and the safe code, and when `failure.report` is true sends one Sentry event through `sentry_sdk.push_scope` with the tags `org_id`, `user_id`, `ml_error`, and `account_id` and `correlation_id` when known. It never receives tokens, the code, the verifier, the nickname or the seller id
- [ ] T005 In `oauth.py` add the attempt store (FR-004 to FR-007, R2, R3):
  - `start_attempt(org, user)`: creates `state = secrets.token_urlsafe(32)` and `verifier = secrets.token_urlsafe(64)`, stores `{org_id, user_id, code_verifier}` in the cache under the prefix and `state` with the attempt lifetime, computes the S256 challenge (`base64url` of the SHA-256 of the verifier, no padding), and returns the authorize address with `response_type=code`, `client_id`, `redirect_uri` (the setting, untouched), `state`, `code_challenge`, `code_challenge_method=S256` and `scope`. Nothing else is in the address
  - `take_attempt(state, org, user)`: raises `ConnectionFailure(state_invalid)` for an empty or unknown state, and for an attempt of another org or user (leaving it in place for its owner). Otherwise takes the marker `<key>:used` with `cache.add` (lifetime equal to the attempt), raises `ConnectionFailure(state_invalid)` if `add` returns false, deletes the attempt, and returns the verifier

**Checkpoint**: the module imports, and the helpers and the store can be called. No endpoint exists yet.

---

## Phase 3: User Story 1 - The seller administrator connects the seller (Priority: P1) 🎯 MVP

**Goal**: a channel admin opens the claim page, goes to ML, comes back and gets one active `ML` channel for the confirmed seller.

**Independent Test**: with ML mocked, start the flow as a channel admin, return with a valid code and the state, and check the channel, its config and the redirect to the channel page.

### Tests for User Story 1

- [ ] T006 [US1] In `temba/channels/types/mercadolivre/tests.py` add `MercadoLivreOAuthStartTest` (mixin from T002), for FR-001 to FR-005: the claim URL answers 200 for a channel admin and its page holds the sentence about the seller administrator and a POST form to the start route; start by POST answers 302 to `https://auth.mercadolivre.com.br/authorization` with the query of FR-005, where `redirect_uri` equals the setting, the `state` has a cache entry, and neither the verifier nor the secret nor an org or user id is in the address; start by GET answers 405; two starts create two different states
- [ ] T007 [US1] In the same file add `MercadoLivreOAuthConnectTest`, for FR-008 and FR-011 to FR-013, with the full flow: start, then callback with the returned `state` and a code, ML mocked for seller `415458330` and nickname `SELLER_X`. Assert: the answer is a 302 to the channel page (`channels.channel_read`), one active `ML` channel exists with address `415458330` and name `SELLER_X`, the config has exactly the seven keys of the contract with `oauth_provider="mercadolivre"`, `oauth_status="active"`, both switches `False` and an `expires_at` that parses as RFC 3339 UTC and equals the exchange time plus `expires_in` (patch `django.utils.timezone.now` as seen by `oauth.py` with `unittest.mock.patch`, because the project does not use `freezegun`), the config has no client id or secret, the seven `ml_*` contact fields exist, the token call was one POST with `grant_type=authorization_code`, the client id and secret, the code, the redirect URI and a `code_verifier`, both calls got `timeout=10`, and the account call carried `Authorization: Bearer <access token>`. Add cases: no nickname gives the seller id as name, and a 200 character nickname gives a 128 character name

### Implementation for User Story 1

- [ ] T008 [US1] In `oauth.py` add `exchange_code(code, verifier)`, `confirm_seller(access_token, token_user_id)` and `connect(org, user, state, code)` (FR-008 to FR-013, FR-022):
  - `exchange_code`: `requests.post(TOKEN_URL, data=..., headers={"accept": "application/json"}, timeout=CALL_TIMEOUT_SECONDS)`. Accepts only HTTP 200 with `access_token`, `refresh_token`, integer `expires_in` and `user_id`. A transport error, a non-JSON body, another status or a missing field raises `ConnectionFailure(exchange_failed)` with report. Returns the tokens, `expires_at` (now in UTC plus `expires_in`, `isoformat`) and the seller id as text
  - `confirm_seller`: `requests.get(ACCOUNT_URL, headers={"Authorization": "Bearer ..."}, timeout=...)`. Accepts only HTTP 200 whose `id` equals the token `user_id` as text. Otherwise raises `ConnectionFailure(seller_mismatch)` with report. Returns the nickname, or the seller id when it is empty, cut to `CHANNEL_NAME_MAX_LENGTH`
  - `connect`: calls `take_attempt`, `exchange_code`, `confirm_seller` in this order, then `Channel.create(org, user, None, "ML", name=..., address=seller_id, config={...})` with the contract config, and returns the channel. Nothing is created before both calls pass
- [ ] T009 [US1] In `temba/channels/types/mercadolivre/views.py` add `ClaimView(ClaimViewMixin, SmartFormView)` with an empty form and the title and blurb, `MercadoLivreStart` and `MercadoLivreCallback` (FR-001, FR-018, R10). Both endpoints use `OrgPermsMixin`, `SmartView`, `View` and `permission = "channels.channel_claim"`, in the shape of `_OutlookView` in `temba/channels/types/email/views.py`. `MercadoLivreStart` allows only POST and redirects to the address from `start_attempt`. `MercadoLivreCallback` allows only GET, reads `state` and `code` (and `error`, handled in T023), calls `connect`, and redirects to the channel page on success. A `ConnectionFailure` becomes one `messages.error` with `FAILURE_MESSAGES[code]` and a redirect to the claim page, and goes through `report_failure`
- [ ] T010 [US1] In `temba/channels/types/mercadolivre/type.py` set `claim_view = ClaimView`, add `claim_blurb`, and add `get_urls()` that returns `self.get_claim_url()` and two `re_path` routes named `start` and `callback` for the two views (path `^start$` and `^callback$`). Import the views inside the method or at the top, whichever avoids a circular import, as `email/type.py` does
- [ ] T011 [US1] Create `templates/channels/types/mercadolivre/claim.haml`, extending `channels/channel_claim_form.html`. It shows the sentence that the account used at ML must be the administrator of the seller account, and a POST form to the start route with the CSRF token and one button, and no other field (FR-002). Overrides `block form` without `block.super`, because the claim form has no fields
- [ ] T012 [US1] Run `poetry run coverage run manage.py test temba.channels.types.mercadolivre.tests.MercadoLivreOAuthStartTest temba.channels.types.mercadolivre.tests.MercadoLivreOAuthConnectTest` and the existing ML tests of feature 024, and confirm all pass

**Checkpoint**: a seller administrator can connect a seller with ML mocked. This is the MVP.

---

## Phase 4: User Story 2 - The attempt cannot be hijacked or replayed (Priority: P1)

**Goal**: the return works once, only for the user and org that started it, and only for 15 minutes.

**Independent Test**: start an attempt, then return with a replayed, expired, unknown, missing and foreign `state`, and check that ML was never called and no channel exists.

### Tests for User Story 2

- [ ] T013 [US2] In `tests.py` add `MercadoLivreOAuthStateTest` for FR-006 and SC-002: replayed state (first return succeeds, second is rejected with the `state_invalid` message), expired state (the cache is Redis with a real TTL, so a frozen clock cannot expire it: assert that `start_attempt` stores the attempt with the 900 second lifetime by patching `cache.set` as `temba/channels/types/email/tests.py` does, and simulate the expiry by deleting the entry), unknown state, missing `state`, missing `code`. Each rejected case asserts that the `requests.post` and `requests.get` mocks were not called and that no `ML` channel exists
- [ ] T014 [US2] In the same class add the foreign cases: a return made by user B of the same org, and by the same user with another org as the current org, are rejected with no call to ML; the attempt of its owner then still completes the connection
- [ ] T015 [US2] Add `MercadoLivreOAuthRaceTest(TembaNonAtomicTest)` for FR-007 and SC-004, modeled on `OutlookConsentRaceTest` in `temba/channels/types/email/tests.py`: two threads on a barrier return with the same state. Assert exactly one `requests.post` call, exactly one active channel, and one rejected return. Run it five times in a loop in the test, to expose a window
- [ ] T016 [US2] Add `MercadoLivreOAuthPkceTest` for FR-005 and AC-4: the `code_challenge` of the start equals the S256 of the `code_verifier` sent in the token call, the verifier is not in any redirect, message or page of the flow, and `start_attempt` produces a verifier of 43 to 128 characters

### Implementation for User Story 2

- [ ] T017 [US2] Run the four test groups of this phase. If any fails, fix `take_attempt` or `start_attempt` in `oauth.py` (for example the order of the checks, or the marker lifetime) until all pass, then run the US1 tests again

**Checkpoint**: US1 and US2 pass together.

---

## Phase 5: User Story 3 - A failed connection says what to do and leaves nothing behind (Priority: P1)

**Goal**: each failure gives one clear message, consumes the attempt and creates no channel and no contact field.

**Independent Test**: for each failure, run the flow with ML mocked to fail that way and check the message, the empty database and the consumed attempt.

### Tests for User Story 3

- [ ] T018 [US3] In `tests.py` add `MercadoLivreOAuthErrorReturnTest` for FR-015 and FR-016: a return with `error=access_denied` shows the "not completed" message; `error=invalid_operator_user_id` shows the message that asks for the administrator; `error=server_error` shows the generic message and no provider text; a hostile `error` value (newlines, markup, 500 characters) shows only the generic message and puts no raw text in the log. Each case asserts no channel, no `ml_*` field, no call to ML, and that a second return with the same state is rejected. Add a unit test of `safe_error_code`
- [ ] T019 [US3] Add `MercadoLivreOAuthExchangeFailureTest` for FR-009, FR-022 and SC-007: the token call times out, answers 400, answers 500, answers a body that is not JSON, and answers 200 without each of `access_token`, `refresh_token`, `expires_in` and `user_id`; and `error=invalid_operator_user_id` inside the token answer. Each case asserts the generic message (or the administrator message for the last), one Sentry report for the unexpected ones and none for the collaborator one, no channel, no `ml_*` field, no account call, and the attempt consumed
- [ ] T020 [US3] Add `MercadoLivreOAuthSellerCheckTest` for FR-010: the account answer has an `id` different from the token `user_id`, the account call answers 401, times out, and answers a body that is not JSON. Each asserts no channel, a Sentry report and the consumed attempt
- [ ] T021 [US3] Add `MercadoLivreOAuthConflictTest` for FR-014 and AC-6: the seller already has an active channel in the same org, and in another org. Assert the message "already connected", that it contains neither an org name nor a user name nor a channel name, no second channel, and no Sentry report. Add the case that releases the first channel and connects again with success. Add the case where the activation of the new channel raises (patch `ensure_mercadolivre_contact_fields` to raise): the message is the generic one, one Sentry report is sent, no active `ML` channel remains, the released row has no tokens in its config, and the attempt is consumed

### Implementation for User Story 3

- [ ] T022 [US3] In `oauth.py` extend `connect` (FR-014, FR-017): catch `ChannelAddressConflict` from `Channel.create` and raise `ConnectionFailure(already_connected)` with no report; catch any other exception from `Channel.create` (a `ValidationError` from `clean_address`, or an exception from the activation, after which `Channel.create` has already released the channel) and raise `ConnectionFailure(channel_invalid)` with report. Catch `ChannelAddressConflict` first, because it is a `ValidationError`. Make sure no code path after `take_attempt` can leave the attempt usable
- [ ] T023 [US3] In `views.py` handle the `error` query parameter in `MercadoLivreCallback` (FR-015, FR-016): when `error` is present, first call `take_attempt` so that the attempt is consumed and the user and org are checked, then raise `ConnectionFailure` with the code `access_denied` or `invalid_operator_user_id` for those values and `provider_error` for any other, using `safe_error_code` for the logged value. The user sees only `FAILURE_MESSAGES[code]`
- [ ] T024 [US3] In `oauth.py` read `error` from a failed token answer (FR-015): when the body has `error == "invalid_operator_user_id"`, raise `ConnectionFailure(invalid_operator_user_id)` with no report, before the generic `exchange_failed` path
- [ ] T025 [US3] Run `poetry run coverage run manage.py test temba.channels.types.mercadolivre` and confirm all tests of US1 to US3 pass

**Checkpoint**: every failure path leaves nothing behind.

---

## Phase 6: User Story 4 - Tokens stay private and the option appears only when it can work (Priority: P2)

**Goal**: the grant is not exposed anywhere, the option is shown only in a configured environment, and a released channel keeps no token.

**Independent Test**: create a connected channel and look for the token values on every surface and in the logs, and open the claim page with and without the settings.

### Tests for User Story 4

- [ ] T026 [US4] In `tests.py` add `MercadoLivreOAuthPrivacyTest` for FR-020 and SC-005: with a connected channel, request the channel read page, the channel list, the v2 API channel list (`api.v2.channels`) and the internal channel endpoint (route name `channels-by-project`, class `InternalChannelView` in `temba/api/v2/internals/channels/views.py`, called with the `project_uuid` of the org and the authentication that the tests of that app use for `WeniAuthentication` or `InternalOIDCAuthentication`), and assert that neither token value nor the client secret appears in any body
- [ ] T027 [US4] In the same class add the log test for FR-019 and AC-7: capture the logs (`assertLogs`) and the Sentry calls (patch `sentry_sdk.capture_message` and `push_scope` in `oauth`) of a success run and of a failed run, and assert that the values of the access token, refresh token, client secret, code, verifier, nickname and seller id are absent, and that org id, user id and the ML error code are present in the failed run
- [ ] T028 [US4] Add `MercadoLivreOAuthAvailabilityTest` for FR-003 and SC-006: with each of the three settings empty in turn, the type is not listed on the claim page and on the "all channels" page, the claim page shows the notice and no button, and a POST to start answers 302 to the claim page with the `not_configured` message and no redirect to ML; with all three set the type is listed
- [ ] T029 [US4] Add `MercadoLivreOAuthPermissionTest` for FR-018 and SC-008: a user without `channels.channel_claim` (viewer) is denied on start and on callback, a signed-out client is sent to sign in, and no attempt is created in either case. Add the sign-in case: start as the admin, sign out, call the callback with the valid `state` and a code (expect a redirect to sign in whose `next` is the callback address with its query), sign in as the same admin and call that address, and expect the channel to be created; the same call after signing in as another user is rejected as foreign

### Tests for release

- [ ] T030 [US4] Add `MercadoLivreOAuthReleaseTest` for FR-027: connect a channel, release it with `channel.release(user)`, reload it, and assert that `access_token` and `refresh_token` are not in its config, the other keys remain, and no mock of ML was called by the release

### Implementation for User Story 4

- [ ] T031 [US4] In `type.py` add `is_available_to(self, user)` returning `(is_configured(), is_configured())` (R9, FR-003)
- [ ] T032 [US4] In `views.py` and the template: `MercadoLivreStart` checks `is_configured()` first and, when false, adds the `not_configured` message and redirects to the claim page with no attempt; `ClaimView.get_context_data` passes `configured`, and `claim.haml` shows the notice and no button when it is false
- [ ] T033 [US4] In `type.py` add `deactivate(self, channel)` that copies the config, removes `access_token` and `refresh_token`, and assigns it back, with no other effect and no network call (FR-027, R12), as `EmailType.deactivate` does. Also correct the comment of `activate` in the same file: `Channel.create` releases the channel when the activation raises, so only the field-limit case (log and skip) leaves the channel in place
- [ ] T034 [US4] Run `poetry run coverage run manage.py test temba.channels.types.mercadolivre` and confirm all tests of US1 to US4 pass. If T026 finds a surface that returns a token, fix that surface in the smallest way and note it in the pull request

**Checkpoint**: all four stories pass.

---

## Phase 7: Polish & cross-cutting concerns

- [ ] T035 [P] Add the new strings (the blurb, the notice for the seller administrator, the button, the not-available notice and the failure messages) to `locale/en_US/LC_MESSAGES/django.po`, `locale/es/LC_MESSAGES/django.po`, `locale/pt_BR/LC_MESSAGES/django.po` and `locale/ro/LC_MESSAGES/django.po`, then regenerate the tracked `django.mo` of es, pt_BR and ro (no `msgfmt` here, use `polib` as in feature 024) (FR-026)
- [ ] T036 [P] Add one `feat` bullet to `WENI-CHANGELOG.md` under the next unreleased heading. If `3.116.0` (feature 024) is already released, add a new heading above it. The bullet names the config contract version 1 and says that Courier reads its keys. Do not extend a released heading and do not rewrite `CHANGELOG.md` (FR-025)
- [ ] T037 Search `temba/channels/types/mercadolivre/oauth.py`, `views.py` and `type.py` for literal ML addresses, scopes, config keys and error codes outside the constants block, and move any to a named constant (FR-023). Confirm that `views.py` holds no business logic
- [ ] T038 Run `./code_check.py` and fix every Black (line length 119), flake8 and isort finding. Confirm it reports no missing migration, and that no new `# pragma: no cover` was added
- [ ] T039 Run `poetry run coverage run manage.py test temba.channels` and `poetry run coverage run manage.py test temba.api.v2.internals`, matching the groups of `.github/workflows/ci.yml`, and compare any failure with the known failures that need Mailroom or network (feature 024 notes)
- [ ] T040 In the pull request description state the cycle (SDD Full), how tests and the changelog were addressed, that there is no migration, the three settings and the redirect URI to register at ML, the open dependencies (Courier CO-02 reads the config keys, RP-04 refreshes the tokens, RP-05 gives the screens), the known gap that the two switches are created `false` and need an operator change until RP-05, and that the single-use attempt uses an atomic marker instead of the get-then-delete of the Outlook flow
- [ ] T041 After the ML application exists (FND-01) and the settings are set in a test environment, run the manual check of [quickstart.md](quickstart.md) section 3 and record the result in the pull request

---

## Requirement coverage

| Requirement | Tasks |
|---|---|
| FR-001 claim view | T006, T009, T010, T011 |
| FR-002 administrator notice | T006, T011 |
| FR-003 availability | T028, T031, T032 |
| FR-004, FR-005 attempt and redirect | T005, T006, T016 |
| FR-006 state rejected | T005, T013, T014 |
| FR-007 single use | T005, T015 |
| FR-008, FR-009 code exchange | T007, T008, T019 |
| FR-010 seller confirmation | T008, T020 |
| FR-011 channel creation | T007, T008 |
| FR-012, FR-013 config contract | T003, T007, T008 |
| FR-014 seller conflict | T021, T022 |
| FR-015, FR-016 provider errors | T018, T019, T023, T024 |
| FR-017 nothing left behind | T018 to T022 |
| FR-018 permission | T009, T029 |
| FR-019 no secrets in logs | T004, T027 |
| FR-020 no grant exposed | T026, T034 |
| FR-021 settings | T001 |
| FR-022 timeouts | T008, T019, T020 |
| FR-023 named constants | T003, T037 |
| FR-024 layout | T003, T009 |
| FR-025 changelog | T036 |
| FR-026 locale | T035 |
| FR-027 release clears tokens | T030, T033 |

This table shows that each requirement has a task and a test task. It does not show that the tests are complete.

---

## Dependencies & execution order

### Phase dependencies

- **Setup (Phase 1)**: no dependency. T001 and T002 touch different files and can run together.
- **Foundational (Phase 2)**: depends on Phase 1 and blocks every story. T003, T004, T005 edit one file, so run them in order.
- **User stories (Phases 3 to 6)**: depend on Phase 2 and run in order, because they share `oauth.py`, `views.py`, `type.py` and `tests.py`:
  - US1 first: it creates the views, the template and the routes.
  - US2 after US1: its tests need the callback endpoint.
  - US3 after US1: it extends `connect` and the callback.
  - US4 after US1: it extends `type.py`, `views.py` and the template.
- **Polish (Phase 7)**: depends on the stories being complete. T035 and T036 can run at any time after the strings and the behavior are fixed.

### Within each story

- Write the tests, run them and see them fail (or, for US2, see what the Phase 2 code already satisfies), then implement, then run the story tests.
- In `oauth.py`: T003, T004, T005, then T008, then T022 and T024.
- In `views.py`: T009, then T023, then T032.
- In `type.py`: T010, then T031, then T033.
- In `tests.py`: T002, T006, T007, T013 to T016, T018 to T021, T026 to T030, in this order.

### Parallel opportunities

- T001 and T002 (settings and test helpers).
- T035 and T036 (locale and changelog) beside each other, and beside T037 to T039.

### Parallel example

```bash
# Phase 1, in parallel (different files):
Task: "T001 Add the three APP_MERCADOLIVRE_* settings in temba/settings_common.py"
Task: "T002 Add the test mixin in temba/channels/types/mercadolivre/tests.py"

# Phase 7, in parallel (different files):
Task: "T035 Add the new strings to the four django.po files and regenerate the .mo files"
Task: "T036 Add the feat bullet to WENI-CHANGELOG.md"
```

---

## Implementation strategy

### MVP first (User Story 1)

1. Phase 1 and Phase 2.
2. Phase 3 (US1): the connection works with ML mocked.
3. Stop and validate with T012. Do not ship alone: US2 and US3 are P1 and close the replay and failure gaps.

### Incremental delivery

1. Add US2 (replay and hijack protection), then US3 (failures), then US4 (privacy, availability, release).
2. Each step ends with its own test run, and the earlier tests stay green.
3. Finish with Phase 7 before opening the pull request. Leave the three settings empty in production until the ML application exists, so the option stays hidden.

### Note on the settings

With the three settings empty the type is not listed, so merging the code does not expose a broken button. That is the rollback too ([quickstart.md](quickstart.md) section 4).

---

## Notes

- Commit after each task or logical group, with Conventional Commits and a description of 50 characters or fewer.
- Do not edit the Courier, Mailroom or DevCenter repositories. The config keys are in [contracts/claim-and-config.md](contracts/claim-and-config.md).
- Do not change `temba/channels/types/email/`. The helpers of the Outlook flow are copied in shape, not imported.
- Tokens, the client secret, the code and the verifier must never appear in a log, a message, a redirect or a test failure output.
