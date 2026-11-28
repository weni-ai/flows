# Contract: ML claim endpoints, settings, config and errors

**Contract version**: 1 (first release of the `ML` channel config). Adding a key is a minor change. Renaming or removing a key, or changing the `expires_at` format, is a breaking change and needs a new version agreed with Courier (Principle IV).

Interfaces that this feature exposes or fixes. The rules behind them are in [../data-model.md](../data-model.md) and [../research.md](../research.md).

## 1. Settings (environment)

| Setting | Default | Use |
|---|---|---|
| `APP_MERCADOLIVRE_CLIENT_ID` | empty | the application id sent to ML |
| `APP_MERCADOLIVRE_CLIENT_SECRET` | empty | used only in the code exchange, never logged |
| `APP_MERCADOLIVRE_REDIRECT_URI` | empty | the exact string registered at ML, `https://<public host>/channels/types/mercadolivre/callback`, no query string |

The feature is available only when all three are non-empty. Otherwise the type is not listed, the claim page shows a notice and the start endpoint redirects back without calling ML.

## 2. Flows endpoints

| Route name | Path | Method | Permission | Answer |
|---|---|---|---|---|
| `channels.types.mercadolivre.claim` | `/channels/types/mercadolivre/claim` | GET | `channels.channel_claim` | the claim page |
| `channels.types.mercadolivre.start` | `/channels/types/mercadolivre/start` | POST (CSRF) | `channels.channel_claim` | 302 to the ML authorize address, or 302 to the claim page with a message |
| `channels.types.mercadolivre.callback` | `/channels/types/mercadolivre/callback` | GET | `channels.channel_claim`, and the user must be the one who started | 302 to the new channel page, or 302 to the claim page with a message |

Other methods answer 405. A user without the permission is denied by the permission mixin. A signed-out user is sent to sign in.

### Callback query

| Parameter | Meaning |
|---|---|
| `state` | the key of the attempt, required |
| `code` | the authorization code, required for success |
| `error` | the ML error code, present when the seller did not finish |

Any other parameter is ignored.

## 3. Calls to Mercado Livre

| Call | Address | Sent | Accepted answer |
|---|---|---|---|
| Authorize (browser redirect) | `https://auth.mercadolivre.com.br/authorization` | `response_type=code`, `client_id`, `redirect_uri`, `state`, `code_challenge`, `code_challenge_method=S256`, `scope=offline_access read write` | not read by Flows. The return arrives at the callback |
| Token | `POST https://api.mercadolibre.com/oauth/token`, 10 s timeout | form: `grant_type=authorization_code`, `client_id`, `client_secret`, `code`, `redirect_uri`, `code_verifier` | HTTP 200 with `access_token`, `refresh_token`, integer `expires_in`, `user_id` |
| Account | `GET https://api.mercadolibre.com/users/me`, 10 s timeout, `Authorization: Bearer <access token>` | none | HTTP 200 with `id` equal to the token `user_id`, and optional `nickname` |

No retry for either call.

## 4. Channel created

| Field | Value |
|---|---|
| type | `ML` |
| address | seller id, digits |
| name | nickname, or the seller id when absent, at most 128 characters |
| config | table below |

### Channel config (consumed by Courier CO-02 and the refresh job RP-04)

```json
{
  "access_token": "<text>",
  "refresh_token": "<text>",
  "expires_at": "2026-11-28T03:00:00+00:00",
  "oauth_provider": "mercadolivre",
  "oauth_status": "active",
  "post_sale_enabled": false,
  "pre_sale_enabled": false
}
```

| Key | Type | Notes |
|---|---|---|
| `access_token` | string | removed on release |
| `refresh_token` | string | single use at ML, replaced by RP-04, removed on release |
| `expires_at` | string | RFC 3339, UTC, exchange time plus `expires_in` |
| `oauth_provider` | string | always `mercadolivre` |
| `oauth_status` | string | `active` at creation. RP-04 may write `needs_reconnect` |
| `post_sale_enabled` | boolean | `false` at creation, changed by RP-05 |
| `pre_sale_enabled` | boolean | `false` at creation, changed by RP-05 |

The client id and the client secret are never in the config. No other API of Flows returns this config.

## 5. Failure codes and messages

Codes are named constants. The user sees only the message, never the provider text.

| Code | Cause | User message (EN) | Reported to Sentry |
|---|---|---|---|
| `state_invalid` | missing, unknown, expired, replayed or foreign `state`, or no `code` | "Your Mercado Livre sign-in expired or is not valid. Start the connection again." | no |
| `access_denied` | the seller cancelled | "The Mercado Livre connection was not completed. You can try again." | no |
| `invalid_operator_user_id` | the account is a collaborator | "Connect with the administrator account of the Mercado Livre seller. Collaborator accounts cannot connect it." | no |
| `provider_error` | any other `error` on the return | "Mercado Livre could not complete the connection. Try again." | no, logged at info level |
| `exchange_failed` | token call failed, timed out or answered badly | "Mercado Livre could not complete the connection. Try again." | yes |
| `seller_mismatch` | account `id` differs from token `user_id`, or the account call failed | "Mercado Livre could not complete the connection. Try again." | yes |
| `already_connected` | `ChannelAddressConflict` | "This Mercado Livre seller is already connected." | no |
| `channel_invalid` | any other `ValidationError` at creation, or an exception from the activation of the new channel (`Channel.create` releases the channel and re-raises) | "Mercado Livre could not complete the connection. Try again." | yes |
| `not_configured` | settings empty | "Connecting Mercado Livre is not available in this environment." | no |

Every failure after the attempt is taken leaves the attempt consumed and no active channel. A failure before the channel is created creates no contact field. A return with an unknown, expired or foreign `state` takes no attempt, and the attempt of its owner stays usable until it expires.

## 6. Logs and reports

- Fixed messages. Fields: org id, user id, correlation id, the safe ML error code.
- Sentry tags: `org_id`, `user_id`, `ml_error`, `account_id` and `correlation_id` when known.
- Never: tokens, secret, code, verifier, nickname, seller id.

## 7. Open dependencies

| Consumer | Needs | Owner |
|---|---|---|
| Courier | the config keys of section 4 and `expires_at` as RFC 3339 | Courier task CO-02 |
| Refresh job | the same keys, and the rule that the refresh token is single use | RP-04 |
| Merchant screens | the two switches | RP-05 |
| Operators | the three settings, and the redirect URI registered at ML | deploy |
