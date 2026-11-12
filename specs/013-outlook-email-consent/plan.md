# Implementation Plan: Outlook consent for an email channel

**Branch**: `013-outlook-email-consent` (no git branch created) | **Date**: 2026-11-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/013-outlook-email-consent/spec.md`

## Summary

An org admin confirms the primary mailbox address on the existing email claim page. Flows redirects the browser to Microsoft, takes the authorization code on its own callback, and creates an `EM` channel only when that code belongs to the same address. The generic email form stays. Tokens live on the channel config the email proxy already reads. Courier and Mailroom do not change. Send and receive after the access token expires depend on a companion change in `weni-ai/email-proxy`, because that service today refreshes tokens only at Google and uses XOAUTH2 only when the IMAP host contains `gmail`.

## Technical Context

**Language/Version**: Python >=3.10,<3.12 (CI 3.11), Django ^3.2

**Primary Dependencies**: Django, existing `requests`, existing PyJWT ^2.10.1. No new dependency. Microsoft identity platform v2 (`common` tenant). Client id and secret: `APP_MICROSOFT_CLIENT_ID` and `APP_MICROSOFT_CLIENT_SECRET`.

**Storage**: PostgreSQL for the existing `channels_channel` row. Redis (`CACHES["default"]`) for the 900-second consent attempt. No migration.

**Testing**: `TembaTest` via `poetry run coverage run manage.py test temba.channels.types.email`, plus `./code_check.py`

**Target Platform**: Flows web process (admin HTML). Transport stays Courier `EM` → email-proxy.

**Performance Goals**: Admin onboarding only. The consent redirect and the callback each finish without a multi-second poll. Token exchange timeout is 10 seconds and is not retried.

**Constraints**: Consent scopes are only `offline_access`, `IMAP.AccessAsUser.All`, and `SMTP.Send`, in that order. No Graph scopes. No tenant-wide permissions. The secret stays on the server. Tokens are never logged or rendered. The admin confirms the primary address before the redirect; an alias or a different Microsoft account creates no channel. Generic email claim unchanged. Connect Outlook hidden while `APP_MICROSOFT_CLIENT_ID` is empty.

**Scale/Scope**: Peak of 50 concurrent consent attempts (start or return) across all orgs, as declared in the spec. One new path under `temba/channels/types/email/`. Message volume is unchanged.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Pre-research gate passed. The unknowns (which Microsoft audience, who refreshes, whether Courier must change) were resolved in research without a principle exception.

| Principle | Result |
|---|---|
| I. Version Control and Review | Pull request, review, green `.github/workflows/ci.yml`. This plan does not open the branch. |
| II. Security and Secrets | `APP_MICROSOFT_CLIENT_ID` and `APP_MICROSOFT_CLIENT_SECRET` come from the environment. The secret is used only on the token request. The grant is stored only on channel config. No new dependency. PyJWT is already in `pyproject.toml`. |
| III. Observability | Consent failures log opaque org id, user id, and Microsoft's `error` code. No mailbox address, no `error_description`, no tokens. |
| IV. Versioned Contracts | Generic claim POST is unchanged. New config keys are additive and ignored by today's Courier. Courier version: none. Mailroom version: none. email-proxy needs a companion release before production use; documented in [contracts/outlook-email-channel.md](./contracts/outlook-email-channel.md). |
| V. Specification Traceability | No product spec. Origin, problem, and AC-1–AC-4 stay in the spec. This plan does not redefine them. |
| VI. No Silent Divergence | Not applicable. Nothing is inherited from a product spec. |
| VII. Commit Messages | Conventional Commits when implementation commits are requested. |
| VIII. Changelog | `feat:` bullet in `WENI-CHANGELOG.md` under the next version heading. Do not append to the already released `3.106.1`. The bullet states that send/receive needs the email-proxy companion. |
| IX. Never Trust the Client | The confirmed address is stored on the attempt before the redirect. The callback cannot replace it. The token mailbox must match it. State, user, org, and `channels.channel_claim` are checked before any write. Views stay thin; the exchange and the create-or-update live in `outlook.py`. |
| X. Fail Gracefully | Microsoft errors, timeout, and an access token that fails verification or has no mailbox create no channel and show a claim-page message. Token HTTP timeout is `MICROSOFT_HTTP_TIMEOUT_SECONDS` (10). No stack trace to the admin. |
| XI. Bounded Retry | The authorization-code exchange is not retried: the code is single-use, so a retry can burn a code that already succeeded. The admin starts again. Refresh retries belong to email-proxy and must be bounded there; Flows does not refresh. |
| XII. Scalability and Peak Load | No durable state in the worker. The attempt is in Redis. Peak remains 50 concurrent consent attempts. |
| XIII. Diagnosable Errors | The log for a failed consent is opaque org id, user id, and Microsoft's `error` code. A Sentry event also includes the opaque account id and any correlation id already on the request. No mailbox, no grant, no `error_description`. |
| XIV. Tests Exercise Flows | Flow tests from start and callback through the channel row, including the failure paths in the spec's Test Strategy. `TembaTest` in `temba/channels/types/email/tests.py`. |
| XV. Explicit Over Clever | TTL, HTTP timeout, hosts, ports, and scopes are named constants. |
| XVI. Contained Changes | Email claim, its template, settings, locales, and changelog. Other channel types and the generic POST behavior stay. |
| Channel layout | Stays under `temba/channels/types/email/` (`type.py`, `views.py`, `tests.py`, plus `outlook.py` for the consent logic). No new channel type code. |
| SDD cycle | Full. This alters how an email channel is created and the credential shape Courier's proxy consumes. |

Post-design re-check: passed. No unjustified violation. The code-exchange exception under XI is the single-use authorization code, recorded above.

## Project Structure

### Documentation (this feature)

```text
specs/013-outlook-email-consent/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/outlook-email-channel.md
├── checklists/requirements.md
└── tasks.md              # /speckit-tasks, not this command
```

### Source Code (repository root)

```text
temba/channels/types/email/type.py          # get_urls, deactivate clears tokens
temba/channels/types/email/views.py         # start + callback; claim page unchanged on POST
temba/channels/types/email/outlook.py       # authorize URL, token exchange, access token, create-or-update
temba/channels/types/email/tests.py
temba/settings_common.py                    # APP_MICROSOFT_CLIENT_ID / APP_MICROSOFT_CLIENT_SECRET
templates/channels/types/email/claim.haml   # primary address, then the existing generic form
templates/channels/channel_read.haml        # reconnect notice when oauth_status=needs_reconnect
locale/                                      # new strings in en, es, pt, ro
WENI-CHANGELOG.md
```

**Structure Decision**: Extend the existing `EM` channel type. Consent logic lives in `outlook.py` so the views stay thin, matching Principle IX. There is no new app and no `usecases/` package because this app does not use that layer.

## Design

### Flow

1. The claim page shows the primary-address form only when `APP_MICROSOFT_CLIENT_ID` is non-empty. The generic credential form stays on the same page.
2. `POST outlook_start` checks `channels.channel_claim`, stores the Redis attempt (org, user, confirmed address, PKCE verifier, 900s), and redirects the whole page to Microsoft. See the authorize URL in the contract.
3. `outlook_callback` rejects a missing, expired, or mismatched attempt, a user who lost `channels.channel_claim`, and any Microsoft `error`. The page shows the case from the contract, including the admin-approval link for `AADSTS65001`. No channel write.
4. On `code`, it exchanges the code once with the client secret, verifies the access token, and reads the mailbox from `upn`, then `preferred_username`, then `unique_name`. The channel is written only when that mailbox equals the stored address.
5. Under a transaction advisory lock on `(org_id, mailbox)` it either creates the `EM` row, replaces tokens on an existing Microsoft row in `needs_reconnect`, or reports that the mailbox is already connected.
6. Release goes through `EmailType.deactivate`, which drops both tokens, then the existing `is_active=False` save. email-proxy already skips inactive rows.

### What this repo does not build

- IMAP, SMTP, or Graph calls on the message path.
- A Celery refresh task.
- A Microsoft revoke call.
- Changes to Courier or Mailroom.
- The email-proxy XOAUTH2 and Microsoft refresh behavior. That is a release dependency, not a follow-up inside this repo. Operators leave `APP_MICROSOFT_CLIENT_ID` empty until that proxy release is deployed.
- A separate frontend that posts the authorization code. Flows is the screen.

### Constants

Named on the email type module: `CONSENT_ATTEMPT_TTL_SECONDS = 900`, `MICROSOFT_HTTP_TIMEOUT_SECONDS = 10`, the two hosts, ports `993` and `587`, the scope list, and `OAUTH_PROVIDER_MICROSOFT = "microsoft"`.

## Complexity Tracking

> No constitution violations.
