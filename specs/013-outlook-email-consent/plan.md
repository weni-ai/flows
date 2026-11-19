# Implementation Plan: Outlook consent for an email channel

**Branch**: `013-outlook-email-consent` (implementation on `fix/outlook-claim`) | **Date**: 2026-11-04 | **Updated**: 2026-11-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/013-outlook-email-consent/spec.md`

## Summary

An org admin confirms the primary mailbox address on the existing email claim page. The form navigates the top window, because Microsoft refuses to render inside a frame. Flows sends the browser through one Microsoft approval that lists the Graph scopes and the Outlook scopes together. The callback redeems that code for the Graph grant only, reads the mailbox from the Graph token or from the id token, then redeems the returned refresh token for the Outlook IMAP/SMTP grant. It creates an `EM` channel only when that mailbox is the confirmed address. The generic email form stays. Both grants live on the channel config. Courier and Mailroom do not change. Send and receive after the access tokens expire depend on a companion change in `weni-ai/email-proxy`, because that service today refreshes tokens only at Google and uses XOAUTH2 only when the IMAP host contains `gmail`.

## Technical Context

**Language/Version**: Python >=3.10,<3.12 (CI 3.11), Django ^3.2

**Primary Dependencies**: Django, existing `requests`, existing PyJWT ^2.10.1. No new dependency. Microsoft identity platform v2 (`common` tenant). Client id and secret: `APP_MICROSOFT_CLIENT_ID` and `APP_MICROSOFT_CLIENT_SECRET`.

**Storage**: PostgreSQL for the existing `channels_channel` row. Redis (`CACHES["default"]`) for the 900-second consent attempt. No migration.

**Testing**: `TembaTest` via `poetry run coverage run manage.py test temba.channels.types.email`, plus `./code_check.py`

**Target Platform**: Flows web process (admin HTML). Transport stays Courier `EM` → email-proxy.

**Performance Goals**: Admin onboarding only. The consent redirect and the callback each finish without a multi-second poll. Token exchange timeout is 10 seconds and is not retried.

**Constraints**: One authorize request. Its scope list is `CONSENT_SCOPES`: `offline_access`, `openid`, `email`, `profile`, `https://graph.microsoft.com/Mail.Send`, `https://graph.microsoft.com/Mail.ReadWrite`, `https://graph.microsoft.com/User.Read`, `https://outlook.office.com/IMAP.AccessAsUser.All`, `https://outlook.office.com/SMTP.Send`, in that order. The code exchange requests `GRAPH_SCOPES` only (the same list without the two Outlook scopes). A second, non-retried `refresh_token` grant requests `OUTLOOK_SCOPES` (`offline_access` plus the two Outlook scopes). Microsoft rejects one token request that names both resources (`AADSTS28000`), so the two grants are never requested together. No tenant-wide permissions. The secret stays on the server. Tokens are never logged or rendered. The admin confirms the primary address before the redirect; an alias or a different Microsoft account creates no channel. Generic email claim unchanged. Connect Outlook hidden while `APP_MICROSOFT_CLIENT_ID` is empty.

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
| V. Specification Traceability | No product spec. Origin, problem, and AC-1–AC-5 stay in the spec. This plan does not redefine them. |
| VI. No Silent Divergence | Not applicable. Nothing is inherited from a product spec. |
| VII. Commit Messages | Conventional Commits when implementation commits are requested. |
| VIII. Changelog | `feat:` bullet in `WENI-CHANGELOG.md` under the next version heading. Do not append to the already released `3.106.1`. The bullet states that send/receive needs the email-proxy companion. |
| IX. Never Trust the Client | The confirmed address is stored on the attempt before the redirect. The callback cannot replace it. The token mailbox must match it. State, user, org, and `channels.channel_claim` are checked before any write. Views stay thin; the exchange and the create-or-update live in `outlook.py`. |
| X. Fail Gracefully | Microsoft errors, timeout, and an access token that fails verification or has no mailbox create no channel and show a claim-page message. Token HTTP timeout is `MICROSOFT_HTTP_TIMEOUT_SECONDS` (10). No stack trace to the admin. |
| XI. Bounded Retry | The authorization-code exchange is not retried: the code is single-use, so a retry can burn a code that already succeeded. The Outlook grant is a second token request with `grant_type=refresh_token`. It is not a retry of the code, and it is not retried either. The admin starts again. Refresh retries after the channel exists belong to email-proxy and must be bounded there; Flows does not refresh. |
| XII. Scalability and Peak Load | No durable state in the worker. The attempt is in Redis. Peak remains 50 concurrent consent attempts. |
| XIII. Diagnosable Errors | The log for a failed consent is opaque org id, user id, and Microsoft's `error` code. A Sentry event also includes the opaque account id and any correlation id already on the request. No mailbox, no grant, no `error_description`. |
| XIV. Tests Exercise Flows | Flow tests from start and callback through the channel row, including the failure paths in the spec's Test Strategy. `TembaTest` in `temba/channels/types/email/tests.py`. |
| XV. Explicit Over Clever | TTL, HTTP timeout, hosts, ports, and scopes are named constants. |
| XVI. Contained Changes | Email claim, its template, settings, locales, and changelog. Other channel types and the generic POST behavior stay. |
| Channel layout | Stays under `temba/channels/types/email/` (`type.py`, `views.py`, `tests.py`, plus `outlook.py` for the consent logic). No new channel type code. |
| SDD cycle | Full. This alters how an email channel is created and the credential shape Courier's proxy consumes. |

Post-design re-check (2026-11-19): passed. No unjustified violation. The code-exchange exception under XI is the single-use authorization code. The Outlook `refresh_token` grant is a second request, not a retry of that code. Both are recorded above.

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
temba/channels/types/email/outlook.py       # authorize URL, Graph exchange, Outlook refresh, mailbox, create-or-update
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

1. The claim page shows the primary-address form only when `APP_MICROSOFT_CLIENT_ID` is non-empty. That form posts with `target="_top"`. The generic credential form stays on the same page.
2. `POST outlook_start` checks `channels.channel_claim`, stores the Redis attempt (org, user, confirmed address, PKCE verifier, 900s), and redirects the top window to Microsoft with `CONSENT_SCOPES` and `prompt=select_account`. See the authorize URL in the contract.
3. `outlook_callback` rejects a missing, expired, or mismatched attempt, a user who lost `channels.channel_claim`, and any Microsoft `error`. The page shows the case from the contract, including the admin-approval link for `AADSTS65001`. No channel write.
4. On `code`, it exchanges the code once with the client secret and `scope` set to `GRAPH_SCOPES`. A work or school Graph access token is a JWT: it is verified (`aud` is `https://graph.microsoft.com` or the Graph app id `00000003-0000-0000-c000-000000000000`) and the mailbox is read from it. A personal Graph access token is opaque. The mailbox then comes from the `id_token`, verified with `aud` equal to `APP_MICROSOFT_CLIENT_ID`. Claim order is `preferred_username`, `upn`, `email`, `unique_name`. No mailbox from either token is `token_mailbox` and creates no channel. The channel is written only when the mailbox equals the stored address.
5. It then calls the token endpoint with `grant_type=refresh_token` and `OUTLOOK_SCOPES`. That returns the IMAP/SMTP access token. When that token is a JWT, it is verified with `aud` `https://outlook.office.com`. When it is opaque, it is stored as-is. `smtp_host` is `smtp.office365.com` for a JWT and `smtp-mail.outlook.com` for an opaque token. IMAP stays `outlook.office365.com:993` for both. The refresh token written on the channel is the one this second call returns, or the Graph refresh token when Microsoft does not rotate it. That same value is stored in `refresh_token` and `graph_send_refresh_token`.
6. Under a transaction advisory lock on `(org_id, mailbox)` it either creates the `EM` row, replaces both grants and `smtp_host` on an existing Microsoft row in `needs_reconnect`, or reports that the mailbox is already connected.
7. Release goes through `EmailType.deactivate`, which drops `access_token`, `refresh_token`, `graph_send_access_token`, and `graph_send_refresh_token`, then the existing `is_active=False` save. email-proxy already skips inactive rows.

### What this repo does not build

- IMAP, SMTP, or Graph calls on the message path.
- A Celery refresh task.
- A Microsoft revoke call.
- Changes to Courier or Mailroom.
- The email-proxy XOAUTH2 and Microsoft refresh behavior. That is a release dependency, not a follow-up inside this repo. Operators leave `APP_MICROSOFT_CLIENT_ID` empty until that proxy release is deployed.
- A separate frontend that posts the authorization code. Flows is the screen.

### Constants

Named in `outlook.py`: `CONSENT_ATTEMPT_TTL_SECONDS = 900`, `MICROSOFT_HTTP_TIMEOUT_SECONDS = 10`, `IMAP_HOST`, `IMAP_PORT` 993, `SMTP_HOST` `smtp.office365.com`, `SMTP_HOST_PERSONAL` `smtp-mail.outlook.com`, `SMTP_PORT` 587, `GRAPH_SCOPES`, `OUTLOOK_SCOPES`, `CONSENT_SCOPES`, and `OAUTH_PROVIDER_MICROSOFT = "microsoft"`.

## Complexity Tracking

> No constitution violations.
