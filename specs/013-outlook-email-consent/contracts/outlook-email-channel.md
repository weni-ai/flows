# Contract: Outlook email channel

Flows exposes two admin URLs and writes a channel config that Courier and email-proxy already read. Courier's HTTP contract does not change. email-proxy's behavior for `oauth_provider=microsoft` is the companion contract this repo does not implement.

## Admin URLs

Both require a signed-in user with `channels.channel_claim` on the current org. Anyone else gets the existing permission failure and no channel is written.

| Name | Method | Path |
|---|---|---|
| `channels.types.email.claim` | GET, POST | existing email claim |
| `channels.types.email.outlook_start` | GET | start Connect Outlook |
| `channels.types.email.outlook_callback` | GET | Microsoft returns here |

`GET outlook_start` renders the primary-address form when `APP_MICROSOFT_CLIENT_ID` is set. It does not render it, and it does not redirect, when that setting is empty. `POST outlook_start` accepts only that address. A non-empty address is stored on the attempt and the browser is redirected, as a full page, to:

```text
https://login.microsoftonline.com/common/oauth2/v2.0/authorize
  ?client_id={APP_MICROSOFT_CLIENT_ID}
  &response_type=code
  &redirect_uri={absolute URI of outlook_callback}
  &response_mode=query
  &scope=offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send
  &state={unguessable}
  &prompt=select_account
  &code_challenge={S256}
  &code_challenge_method=S256
```

`redirect_uri` and `scope` are query-encoded. The redirect URI registered on the Microsoft app, platform Web, must match that callback URI exactly. The same value is sent on the token request. The client secret is not in this URL.

`GET outlook_callback` accepts `code`, `state`, `error`, and `error_description`. It creates or updates a channel only when `state` matches an unexpired attempt for this user and this org, the code exchange succeeds, and the access-token mailbox equals the address stored on the attempt. Every other return sends the admin back to the email claim page and writes nothing.

| Return | Page |
|---|---|
| `error=access_denied`, or the admin leaves before approving | The form, with no channel |
| `error=consent_required`, or `error_description` contains `AADSTS65001` | The form, telling a Microsoft 365 admin to allow the app, with `https://login.microsoftonline.com/common/adminconsent?client_id={APP_MICROSOFT_CLIENT_ID}` |
| `state` missing or not the stored attempt | The form, telling the admin to start the login again |
| Any other `error` | The form, showing `error_description`, with no channel |

The generic claim POST body is unchanged: `username`, `password`, `smtp_host`, `smtp_port`, `imap_host`, `imap_port`, `access_token`, `refresh_token`. Connect Outlook does not submit that form.

## Token exchange (Flows → Microsoft)

```text
POST https://login.microsoftonline.com/common/oauth2/v2.0/token
Content-Type: application/x-www-form-urlencoded

client_id={APP_MICROSOFT_CLIENT_ID}
client_secret={APP_MICROSOFT_CLIENT_SECRET}
code
redirect_uri={the same callback URI}
grant_type=authorization_code
code_verifier
```

Timeout is 10 seconds. This call is not retried. The access token is verified with PyJWT (RS256, JWKS from `https://login.microsoftonline.com/common/discovery/v2.0/keys`, `aud` is `https://outlook.office.com`, issuer is a `https://login.microsoftonline.com/{tenant}/v2.0` issuer, `exp` is in the future). Mailbox is the first of `upn`, `preferred_username`, and `unique_name` that contains `@`. The channel address is that mailbox only when it equals the attempt's `username`. There is no ID token, because `openid` is not requested.

## Channel config written by Flows

See [data-model.md](../data-model.md). Consumers:

| Consumer | What it reads | This change |
|---|---|---|
| Courier `EM` handler | `config.username` as the sender. Inbound is still `POST /c/em/{uuid}/receive` from the proxy. | No Courier release required. |
| email-proxy | `imap_*`, `smtp_*`, `username`, `password`, `access_token`, `refresh_token` on active `EM` rows. | Must gain the behavior below before Outlook send/receive works. |
| Channel read page | `name` and `address`. Does not render `config`. | Adds a reconnect notice when `oauth_status=needs_reconnect`. |

`access_token` and `refresh_token` are not returned in HTML, messages, or logs.

## Companion contract for email-proxy

Not implemented in this repository. Required before an operator sets `APP_MICROSOFT_CLIENT_ID` in production. The proxy reads the same client id and `APP_MICROSOFT_CLIENT_SECRET` from its environment.

When `config.oauth_provider` is `microsoft`:

1. IMAP authenticates with XOAUTH2 (`user={username}\x01auth=Bearer {access_token}\x01\x01`) against `imap_host`. Do not use password login, and do not require the host to contain `gmail`.
2. SMTP keeps the existing empty-password bearer path against `smtp_host`.
3. Refresh is `POST https://login.microsoftonline.com/common/oauth2/v2.0/token` with `grant_type=refresh_token`, the Outlook client id and secret from the proxy environment, and the stored refresh token. Do not call `https://accounts.google.com/o/oauth2/token` for these rows.
4. On a successful refresh, persist the new `access_token`. If Microsoft returns a new `refresh_token`, persist that too.
5. On `invalid_grant`, set `oauth_status` to `needs_reconnect`, stop the watcher, and do not send. Do not delete the row.
6. Transient refresh failures (timeout, HTTP 429, HTTP 5xx) retry with a bounded backoff. They do not flip `oauth_status`.

Rows without `oauth_provider=microsoft` keep today's Gmail-or-password behavior.

## Removal

Releasing the channel sets `is_active=false` and removes `access_token` and `refresh_token`. email-proxy already ignores inactive rows. Flows does not call a Microsoft revoke URL.
