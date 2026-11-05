# Tasks: Outlook consent for an email channel

**Input**: Design documents from `/specs/013-outlook-email-consent/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/outlook-email-channel.md](./contracts/outlook-email-channel.md), [quickstart.md](./quickstart.md)

**Tests**: Included. The spec Test Strategy and constitution XIV require flow tests from the admin action to the channel row. Write each story's tests first and confirm they fail before that story's implementation.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

- Flows code: `temba/channels/types/email/`
- Templates: `templates/channels/`
- Settings: `temba/settings_common.py`
- Locales: `locale/*/LC_MESSAGES/django.po`
- Changelog: `WENI-CHANGELOG.md`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Environment settings the consent flow reads

- [x] T001 Add `APP_MICROSOFT_CLIENT_ID` and `APP_MICROSOFT_CLIENT_SECRET` from the environment, defaulting to empty strings, in `temba/settings_common.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Constants and the one-time consent attempt every story uses

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T002 Add named constants and the Redis consent-attempt helpers in `temba/channels/types/email/outlook.py`: `CONSENT_ATTEMPT_TTL_SECONDS` 900, `MICROSOFT_HTTP_TIMEOUT_SECONDS` 10, IMAP host `outlook.office365.com` port 993, SMTP host `smtp.office365.com` port 587, scopes in order `offline_access`, `https://outlook.office.com/IMAP.AccessAsUser.All`, and `https://outlook.office.com/SMTP.Send`, `oauth_provider` `microsoft`, statuses `active` and `needs_reconnect`. `put_attempt` stores org id, user id, the confirmed primary address, and the PKCE verifier under `outlook-email-consent:{state}` with that TTL. `pop_attempt` returns the payload once and deletes the key. No Microsoft call and no channel write in this task.

**Checkpoint**: Settings and the attempt store exist. User stories can start.

---

## Phase 3: User Story 1 - Connect an Outlook mailbox (Priority: P1) 🎯 MVP

**Goal**: An org admin confirms a primary mailbox address, approves Microsoft for that same address, and gets exactly one `EM` channel, without typing a password or mail-server settings.

**Independent Test**: `poetry run coverage run manage.py test temba.channels.types.email.EmailTypeTest` posts a primary address and an approved consent for that mailbox. The channel address is that address. The response HTML does not contain either token.

### Tests for User Story 1

- [x] T003 [US1] Add failing flow tests in `temba/channels/types/email/tests.py` that mock the token endpoint and JWKS and never call `login.microsoftonline.com`. Assert: empty `APP_MICROSOFT_CLIENT_ID` does not show the primary-address form and does not redirect; a blank address or one without `@` does not redirect and does not store an attempt; posting a primary address redirects with the scopes from T002 in that order and with PKCE; an approved consent whose token mailbox equals that address creates one `EM` channel for a work mailbox and for an Outlook.com mailbox, including a refresh token; a different token mailbox creates none; config matches `specs/013-outlook-email-consent/data-model.md`; the HTML does not contain `access_token` or `refresh_token`; the start form does not submit a password or server fields. Do not assert an IMAP or SMTP send.

### Implementation for User Story 1

- [x] T004 [US1] Implement the authorize URL (`prompt=select_account`, PKCE S256, scopes from T002), the single 10-second code exchange with `APP_MICROSOFT_CLIENT_SECRET` and no retry, access-token verification (`aud` `https://outlook.office.com`, v2 issuer, `exp`, RS256 against the Microsoft JWKS), and create-under-`pg_advisory_xact_lock` only when the token mailbox equals the stored address, in `temba/channels/types/email/outlook.py`
- [x] T005 [US1] Add a start view that accepts the primary address and redirects, and a callback view that calls `outlook.py` on the happy path, in `temba/channels/types/email/views.py`. A blank address or one without `@` is rejected on the form and does not redirect. Leave `ClaimView.form_valid` unchanged.
- [x] T006 [US1] Register `outlook_start` and `outlook_callback` beside the existing claim URL in `EmailType.get_urls` in `temba/channels/types/email/type.py`
- [x] T007 [US1] Add the primary-address form, rendered only when `APP_MICROSOFT_CLIENT_ID` is non-empty, and keep the generic credential form, in `templates/channels/types/email/claim.haml`

**Checkpoint**: User Story 1 is testable on its own. A successful consent creates one email channel. The generic form still posts as it does today.

---

## Phase 4: User Story 2 - A failed consent creates nothing (Priority: P2)

**Goal**: Deny, cancel, expiry, mismatch, a missing mailbox, a missing permission, and a duplicate address create no new channel, and the admin can start again.

**Independent Test**: Each failure in `temba/channels/types/email/tests.py` leaves the org's email-channel count unchanged. The existing generic claim test still passes.

### Tests for User Story 2

- [x] T008 [US2] Add failing tests in `temba/channels/types/email/tests.py` for deny (`access_denied`), `consent_required` or `AADSTS65001` showing the admin-approval link, another Microsoft `error` showing `error_description` without logging it, expired or unknown `state`, a return whose user or org does not match the attempt, a token mailbox that is not the confirmed address, a user without `channels.channel_claim`, a second consent for an address that already has an active email channel in that org, and two concurrent completions for one new address. Assert no new row except the single row from the concurrent pair. Do not rewrite the existing generic claim test.

### Implementation for User Story 2

- [x] T009 [US2] Reject those returns before any channel write, treat an already-active mailbox as already connected, and log the opaque org id, user id, and the Microsoft `error` code in `temba/channels/types/email/outlook.py`. If the failure is sent to Sentry, also attach the opaque account id and the correlation id already on the request. Do not log or attach `error_description`, the authorization code, either token, or the mailbox address.
- [x] T010 [US2] Return the admin to the email claim page with the message for that case, including the admin-approval link for `AADSTS65001` and `error_description` for any other Microsoft error, and no new channel, in `temba/channels/types/email/views.py`

**Checkpoint**: User Stories 1 and 2 both hold. Failed and duplicate attempts do not add a channel.

---

## Phase 5: User Story 3 - The permission stays usable, and removal stops it (Priority: P3)

**Goal**: A Microsoft channel already marked `needs_reconnect` is updated in place. Releasing the channel drops the tokens. The channel page shows that reconnect state and never the grant.

**Independent Test**: A `needs_reconnect` consent keeps the same channel id and sets `oauth_status=active`. Release leaves `is_active` false and both tokens absent. The channel read page shows the reconnect notice and not the tokens.

### Tests for User Story 3

- [x] T011 [US3] Add failing tests in `temba/channels/types/email/tests.py` for in-place token replacement when `oauth_status` is `needs_reconnect`, for `EmailType.deactivate` clearing `access_token` and `refresh_token` on release, and for the reconnect notice on the channel read page. Assert the notice and the page do not contain either token.

### Implementation for User Story 3

- [x] T012 [US3] After T009, on consent for an existing Microsoft channel with `oauth_status=needs_reconnect`, replace the tokens and set `oauth_status` to `active` on that same row in `temba/channels/types/email/outlook.py`
- [x] T013 [P] [US3] Remove `access_token` and `refresh_token` in `EmailType.deactivate` in `temba/channels/types/email/type.py` so `Channel.release` saves the row without them
- [x] T014 [P] [US3] Show a reconnect notice when `oauth_provider` is `microsoft` and `oauth_status` is `needs_reconnect`, with no token output, in `templates/channels/channel_read.haml`

**Checkpoint**: All three stories work. Removal stops use of the grant. A later connect needs a new consent.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Locales, changelog, and the quickstart check

- [x] T015 [P] Add the new Connect Outlook, failure, and reconnect strings to `locale/en_US/LC_MESSAGES/django.po`, `locale/es/LC_MESSAGES/django.po`, `locale/pt_BR/LC_MESSAGES/django.po`, and `locale/ro/LC_MESSAGES/django.po`
- [x] T016 [P] Add a `feat:` bullet under the next version heading in `WENI-CHANGELOG.md`. Do not append it to `3.106.1`. State that send and receive need the email-proxy companion before `APP_MICROSOFT_CLIENT_ID` is set in production.
- [x] T017 Run the checks in `specs/013-outlook-email-consent/quickstart.md`: `poetry run coverage run manage.py test temba.channels.types.email` and `./code_check.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on T001. Blocks every user story.
- **User Story 1 (Phase 3)**: Depends on Phase 2. No dependency on US2 or US3.
- **User Story 2 (Phase 4)**: Depends on Phase 3, because the failure tests extend the callback and the same test module.
- **User Story 3 (Phase 5)**: T011, T013, and T014 depend on Phase 3. T012 edits `outlook.py` and starts after T009.
- **Polish (Phase 6)**: Depends on the stories being implemented. T017 is last.

### User Story Dependencies

- **User Story 1 (P1)**: Starts after T002. Delivers the MVP.
- **User Story 2 (P2)**: Starts after T007. Same callback, additional rejection behavior.
- **User Story 3 (P3)**: T013 and T014 start after T011 and can run together. T012 starts after T009 because it also edits `outlook.py`.

### Within Each User Story

- The story test task is first and must fail before that story's implementation tasks.
- `outlook.py` behavior lands before the view that calls it.
- URLs land before the template that links to them.

### Parallel Opportunities

- T013 and T014 can run in parallel after T011. T012 waits for T009.
- T015 and T016 can run in parallel after the stories they describe are in place.
- US2 and US3 are not parallel with US1: they edit `outlook.py`, `views.py`, and `tests.py` after the happy path exists.

---

## Parallel Example: User Story 3

```bash
# After T011 is written and failing, these two files can be edited together.
# T012 waits until T009 has finished with outlook.py.
Task: "T013 Clear tokens in EmailType.deactivate in temba/channels/types/email/type.py"
Task: "T014 Reconnect notice in templates/channels/channel_read.haml"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Finish T001 and T002.
2. Finish T003 through T007.
3. Stop and run `poetry run coverage run manage.py test temba.channels.types.email`.
4. The admin can complete a consent and see one email channel. Failure handling and reconnect are not in this slice yet.

### Incremental Delivery

1. Setup + foundation.
2. User Story 1 → one channel from an approved consent.
3. User Story 2 → failed and duplicate attempts create nothing.
4. User Story 3 → reconnect updates the same channel, and release drops the tokens.
5. Polish → locales, changelog, quickstart commands.

### Out of scope for every task

Do not add a Celery refresh task, a Microsoft revoke call, IMAP or SMTP inside Flows, or a Courier or Mailroom change. email-proxy support for `oauth_provider=microsoft` is a separate repository.

---

## Notes

- [P] tasks use different files and do not wait on each other.
- Commit after each task or logical group when a commit is requested.
- The generic email claim POST stays as it is. T008 keeps that existing test green without changing its expected config.
