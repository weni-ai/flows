# Research: Connect a Mercado Livre seller to Flows (OAuth claim)

Phase 0 of `/speckit-plan`. The spec has no `NEEDS CLARIFICATION` marker. This file records the technical decisions the spec left to planning and the seven defaults the spec recorded in "Assumptions", each checked against the code in this repository.

## R1. Where the OAuth logic lives

- **Decision**: a module `temba/channels/types/mercadolivre/oauth.py` holds the attempt store, the ML calls, the error type and the channel creation. `views.py` holds the claim view and the two thin endpoints. `type.py` registers them.
- **Rationale**: the Outlook claim does the same (`outlook.py` for logic, `views.py` for the views). Principle IX asks for thin views, with logic in the channel type module.
- **Alternatives considered**: a `usecases/` package. Rejected because the channel types in this repository keep their logic in the type directory (`whatsapp_cloud/usecases.py`, `outlook.py`), and feature 024 already has a `usecases.py` for the fields.

## R2. Attempt store and single use

- **Decision**: the attempt is a cache entry keyed by `state` under a named prefix, with the org id, the user id and the PKCE verifier, and a lifetime of 900 seconds (named constant, the value Outlook uses). The `state` is `secrets.token_urlsafe(32)` and the verifier is `secrets.token_urlsafe(64)` (86 characters, inside the 43 to 128 that PKCE allows).
- **Single use under concurrency**: the callback reads the attempt, and if it exists, takes a second key `<state key>:used` with `cache.add`. `add` writes only if the key is absent and is atomic in Redis, so only one of two simultaneous returns gets `True`. The loser is rejected as a replay. After taking the marker the winner deletes the attempt. The marker has the same lifetime, so a replay after the attempt expired is rejected by the missing attempt.
- **Rationale**: the Outlook `pop_attempt` does `get` then `delete`, which lets two simultaneous returns both read the payload. FR-007 and SC-004 need an atomic take. `cache.delete` returns a count only on the Redis backend (Django 3.2 returns `None` on other backends), so it cannot be the guard.
- **Alternatives considered**:
  - A database row for the attempt. Rejected: a migration and a cleanup job for a 15 minute record.
  - A Lua script or `GETDEL` on the raw Redis client. Rejected: bypasses the cache abstraction the project uses and needs a Redis version check.
  - Writing the marker before reading. Rejected: random `state` values from a caller would write keys.

## R3. `state` is opaque, not signed (spec assumption 1)

- **Decision**: opaque random `state` that keys a server-side attempt. It carries no data.
- **Rationale**: it binds org, user and verifier to the request as a signed `state` would, it is single use by construction and it needs no signing key or key rotation. The Outlook claim does the same, and its tests exist as a model.
- **Alternatives considered**: a signed `state` with org, user and nonce, as the design document says. Rejected because it would still need the server-side verifier and the single-use record, so it only adds a key.

## R4. Redirect URI and routes

- **Decision**: the redirect URI is a setting, `APP_MERCADOLIVRE_REDIRECT_URI`, and is never built from the request. The type serves two routes through `get_urls`: `start` (POST) and `callback` (GET), reversed as `channels.types.mercadolivre.start` and `channels.types.mercadolivre.callback`. The path to register at ML is `/channels/types/mercadolivre/callback` on the public host.
- **Rationale**: ML compares the string exactly and the application has one registered value. A value derived from `request.build_absolute_uri` (as the Outlook flow does) changes with the host header, the brand domain or a proxy and would break the comparison. A setting makes the registered value and the sent value the same by construction.
- **Alternatives considered**: build from `settings.HOSTNAME` plus `reverse`. Rejected: `HOSTNAME` is `localhost` in some environments and brands can have other domains. The explicit setting is also what the start endpoint checks for availability (R9).

## R5. Calls to Mercado Livre

- **Decision**: two calls, both with `requests` and a timeout of 10 seconds (named constant), and no retry.
  - `POST https://api.mercadolibre.com/oauth/token`, form encoded, with `grant_type=authorization_code`, `client_id`, `client_secret`, `code`, `redirect_uri` and `code_verifier`, and the header `accept: application/json`.
  - `GET https://api.mercadolibre.com/users/me` with `Authorization: Bearer <access token>`.
- **Answer rules**: the token answer is valid only with HTTP 200, an `access_token`, a `refresh_token`, an integer `expires_in` and a `user_id`. The account answer is valid only with HTTP 200, an `id` equal to the token `user_id` (compared as text) and optionally a `nickname`.
- **Rationale**: the design document gives both calls and says the account call confirms the seller and gives the nickname. A transport error, timeout, non-JSON body, non-200 status or a missing field is one failure kind, so the user sees one message and Sentry gets one report with the ML error code.
- **Alternatives considered**: retry on 5xx. Rejected by FR-008: the code is single use at ML, so a retry after a timeout can fail for a reason the user cannot see, and the user can simply try again.

## R6. Error mapping

- **Decision**: known codes map to messages, everything else to a generic message, and provider text is never shown (FR-016).

| Source | Code | Result |
|---|---|---|
| Return query `error`, or token answer `error` | `invalid_operator_user_id` | message that asks for the seller administrator, no report |
| Return query `error` | `access_denied` | "sign-in was not completed", no report |
| Return query `error` | any other | generic message, logged at info level with the safe code |
| Return | missing, unknown, expired, replayed or foreign `state`, or missing `code` | "sign in again", no call to ML |
| Token or account call | transport error, timeout, bad status, bad body, missing field, id mismatch | "Mercado Livre did not complete the sign-in", reported |
| Channel creation | `ChannelAddressConflict` | "this seller is already connected", no report |
| Channel creation | any other `ValidationError`, or any exception from the activation (`Channel.create` releases the new channel and re-raises) | generic message, reported |

- **Rationale**: the same shape as the Outlook flow, so the reviewers know it. Reports are for unexpected failures only, so Sentry does not fill with user mistakes. The error code that is logged goes through the same "safe code" filter as Outlook (letters, digits, dot, dash and underscore, up to 80 characters) so a hostile `error` value cannot reach the log.

## R7. Channel config contract (spec assumption 2)

- **Decision**: the config written at creation:

| Key | Value |
|---|---|
| `access_token` | the access token |
| `refresh_token` | the refresh token |
| `expires_at` | absolute UTC time, RFC 3339 (for example `2026-11-28T03:00:00+00:00`), computed as the time of the exchange plus `expires_in` |
| `oauth_provider` | `mercadolivre` |
| `oauth_status` | `active` |
| `post_sale_enabled` | `false` |
| `pre_sale_enabled` | `false` |

- **Rationale**: `access_token`, `refresh_token`, `oauth_provider` and `oauth_status` are the names and the `active` value the Outlook config already uses, so the later RP-04 job can use `needs_reconnect` in the same field. An absolute time lets Courier compare with its own clock without knowing when the token was issued, and RFC 3339 parses in Go (`time.RFC3339`) and in Python. `callback_domain` is not stored, because Courier needs no callback from this channel.
- **Open dependency**: Courier task CO-02 reads these names. If Courier needs other names, only the constants of this module change.
- **Alternatives considered**: `expires_in` plus `issued_at`. Rejected: two fields to combine and an easy off-by-one in the reader.

## R8. Switches (spec assumption 3)

- **Decision**: both created `false`, as the design document says ("os dois desligados até o merchant ligar").
- **Consequence recorded**: until RP-05 gives a screen, turning one on is an operator change to the channel config. This does not block the tests of this feature, and it must be listed in the pull request so that the pilot team knows.
- **Alternatives considered**: create with post-sale on. Rejected: it contradicts the design document and would let messages be processed for a seller whose merchant never agreed.

## R9. Availability (spec assumption 6)

- **Decision**: "configured" means that `APP_MERCADOLIVRE_CLIENT_ID`, `APP_MERCADOLIVRE_CLIENT_SECRET` and `APP_MERCADOLIVRE_REDIRECT_URI` are all non-empty. The type overrides `is_available_to(user)` to return `(configured, configured)`, so the type is listed on the claim page and on the "all channels" page only when configured. The claim view always renders: when not configured it shows a short notice and no button. The start endpoint sends the user back to the claim page with a message and makes no redirect.
- **Rationale**: `Claim.channel_types_groups` already filters by `is_available_to`, and `WhatsAppCloudType` overrides it the same way to hide a type. The Outlook option uses the same idea with `outlook_enabled`.
- **Alternatives considered**: `beta_only`. Rejected: it hides by user, not by environment, and the need is "not configured here". A new feature flag. Rejected: a second switch to keep in step with the settings.

## R10. Permission and views

- **Decision**: `ClaimView(ClaimViewMixin, SmartFormView)` for the page. `MercadoLivreStart` and `MercadoLivreCallback` follow `_OutlookView`: `OrgPermsMixin`, `SmartView`, `View`, `permission = "channels.channel_claim"`. The start accepts only POST (with the CSRF token of the claim page) and the callback only GET. The callback needs a signed-in user, and the attempt must have been started by the same user and org.
- **Rationale**: Principle XVII asks for an explicit permission on each endpoint. The same permission string already guards every claim view and the Outlook endpoints. The callback is not an open endpoint: it is reached by a redirect in the user's own session, and the unguessable single-use `state` is what stops a forged return.

## R11. Logging, errors and identifiers (Principles III and XIII)

- **Decision**: logs use fixed messages with the opaque org id, user id and the safe ML error code. Sentry reports set the tags `org_id`, `user_id`, `ml_error`, and `account_id` and `correlation_id` when present. Two helpers (the project uuid of the org as account id, and the request correlation header) are written in this module, with the same logic as the Outlook ones.
- **Rationale**: the Outlook helpers are small and live in a module that belongs to another type. Importing them would couple two types, and moving them to a shared place is a refactor outside this change (Principle XVI). The duplication is two functions of three lines each, noted in the plan.
- **Never logged**: access token, refresh token, client secret, code, verifier, nickname, seller id.

## R12. Release clears the tokens (new in planning, FR-027)

- **Decision**: `MercadoLivreType.deactivate(channel)` removes `access_token` and `refresh_token` from the config in memory, as `EmailType.deactivate` does, and `Channel.release` saves the config. No call to ML.
- **Rationale**: a released channel with a live grant in its config is a leak that nobody reads. Revoking the grant at ML belongs to RP-05 and needs a call that can fail. This part is local and cannot fail.
- **Alternatives considered**: leave tokens until RP-05. Rejected: AC-7 says tokens never appear where they should not, and a released row is such a place.

## R13. Token exposure audit (spec assumption 4)

- Channel pages: `show_config_page = False` for the type, and the channel read page template does not print `config`.
- The v2 API serializers do not use channel `config` (search of `temba/api/v2/serializers.py` finds nothing).
- The internal channel endpoints (`temba/api/v2/internals/channels/views.py` and `usecases.py`) read named keys one by one (`wa_waba_id`, `wa_number`, `is_demo`, `mmlite`, `voice_mode`, `marketing_tags`, `allowed_domains`) and never return the whole `config`, so the new keys are not returned.
- The channel read page reads only `oauth_provider` and `oauth_status` from the config (for the Outlook reconnect notice).
- **Decision**: a privacy test creates a connected channel and checks the channel read page, the channel list, the v2 API channel list and the internal channel endpoint for the token values. A new surface that returns the whole `config` would fail it.

## R14. No migration, no dependency, no data change

- **Decision**: the feature stores the grant in the existing `Channel.config` JSON text field and the attempt in the cache. `requests` and `sentry_sdk` are already dependencies. There is no migration, no new table and no new package.
- **Rationale**: feature 024 already shipped the only schema change the ML channel needs (the unique constraint).

## R15. Settings

- **Decision**: three settings in `temba/settings_common.py`, read from the environment with empty defaults and a comment that says the secret is used only for the code exchange: `APP_MERCADOLIVRE_CLIENT_ID`, `APP_MERCADOLIVRE_CLIENT_SECRET`, `APP_MERCADOLIVRE_REDIRECT_URI`. The authorize and token addresses are constants of the module, not settings, because the design document fixes them for the Brazil MVP.
- **Rationale**: same names pattern as `APP_MICROSOFT_*`, and the secret never enters the repository (Principle II).

## R16. Tests

- **Decision**: add classes to `temba/channels/types/mercadolivre/tests.py`: start, callback success (full flow), state rules, failures, privacy and release, and a `TembaNonAtomicTest` with two threads for the simultaneous return. ML is mocked by patching `requests.post` and `requests.get` in the `oauth` module. The logs are captured with `assertLogs` and Sentry with a patch of `capture_message` and `push_scope`.
- **Rationale**: Principle XIV asks for a full-flow test and the failure paths. The Outlook tests are the model for the race test.

## R17. Changelog and locale

- **Decision**: one `feat` bullet in `WENI-CHANGELOG.md` under the next unreleased heading (feature 024 added `3.116.0`: if that is still unreleased, the bullet goes there, else a new heading above it). New strings in the four locales, with the `.mo` files regenerated for the translated ones.
- **Rationale**: Principle VIII and the Flows Backend Standards.
