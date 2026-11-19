# Data model: Outlook consent for an email channel

No new table and no migration. The consent attempt is cache state. The channel is the existing `channels_channel` row of type `EM`.

## Consent attempt

Stored in the Redis cache used by `CACHES["default"]`. Not stored in the database and not stored in process memory.

| Field | Rule |
|---|---|
| Key | `outlook-email-consent:{state}` where `state` is `secrets.token_urlsafe(32)` |
| TTL | 900 seconds (`CONSENT_ATTEMPT_TTL_SECONDS`) |
| `org_id` | Org the admin belonged to when they started |
| `user_id` | Admin who started |
| `username` | Primary mailbox address the admin confirmed, stripped and lowercased |
| `code_verifier` | PKCE verifier for this attempt |

The callback reads the key, checks org and user, then deletes it before any channel write. A second use of the same state finds nothing and creates nothing. A return after 900 seconds finds nothing and creates nothing.

## Email channel (existing row)

`Channel` with `channel_type="EM"`, `schemes=["mailto"]`, `is_active=True`.

| Field | Outlook consent | Generic claim |
|---|---|---|
| `name` | mailbox address | unchanged (the submitted username) |
| `address` | mailbox address | unchanged |
| `config` | shape below | unchanged |

The channel address is the `username` stored on the attempt. It is used only when it equals the mailbox read from the Graph access token, or from the `id_token` when that access token is opaque or has no mailbox claim. It is not taken from the callback query.

### `config` for an Outlook channel

| Key | Type | Rule |
|---|---|---|
| `username` | string | same mailbox address |
| `password` | string | empty |
| `smtp_host` | string | `smtp.office365.com` when the Outlook access token is a JWT; `smtp-mail.outlook.com` when it is opaque |
| `smtp_port` | int | `587` |
| `imap_host` | string | `outlook.office365.com` |
| `imap_port` | int | `993` |
| `access_token` | string | Outlook access token from the refresh-token grant; never rendered |
| `refresh_token` | string | refresh token from that grant, or the Graph refresh token when Microsoft does not rotate it; never rendered |
| `graph_send_access_token` | string | Graph access token from the code exchange; never rendered |
| `graph_send_refresh_token` | string | the same value as `refresh_token`; never rendered |
| `oauth_provider` | string | `microsoft` |
| `oauth_status` | string | `active` or `needs_reconnect` |
| `callback_domain` | string | `settings.HOSTNAME` |

Generic claim rows do not gain `oauth_provider` or `oauth_status`.

## Validation rules

- The callback creates or updates a channel only when the signed-in user still has `channels.channel_claim` on the org stored in the attempt.
- The confirmed address is empty, is not an email address, or differs from the mailbox claim: no channel. The claim is the first of `preferred_username`, `upn`, `email`, and `unique_name` that contains `@`. It is read from the Graph access token when that token is a JWT and has such a claim, and otherwise from the `id_token`.
- Microsoft `error` query parameter, including `access_denied`, `consent_required`, and a description that contains `AADSTS65001`: no channel. The page explains the case. `error_description` is shown for any other `error` and is not logged.
- A JWT Graph token, id token, or Outlook token fails `aud`, `iss`, `exp`, or signature: no channel. An opaque Graph token is not a failure by itself. An opaque Outlook token is stored after the mailbox has already been accepted.
- Neither the Graph token nor the id token yields a mailbox: no channel. The log code is `token_mailbox`.
- The code exchange has no `access_token` or no `refresh_token`: no channel. The Outlook grant has no `access_token`: no channel. It may omit `refresh_token`; the Graph refresh token is kept in that case.
- Active `EM` channel in the same org with the same address, and it is not a Microsoft channel in `needs_reconnect`: no new channel.
- Active `EM` channel in another org with the same address: allowed. Each org has its own row and its own grant.

## State transitions

```text
(no row)
    -- successful consent --> EM active, oauth_status=active

EM active, oauth_status=active
    -- consent again for the same address --> no write; admin is told it is already connected
    -- email-proxy sees invalid_grant --> oauth_status=needs_reconnect (proxy write, not Flows)
    -- admin releases the channel --> is_active=false, both grants removed

EM active, oauth_status=needs_reconnect
    -- successful consent for the same address --> same row, both grants replaced, smtp_host replaced, oauth_status=active
    -- admin releases the channel --> is_active=false, both grants removed

EM inactive
    -- not a target. A later consent creates a new active row and requires a new Microsoft approval
```

The duplicate check and the insert-or-update run in one transaction after `pg_advisory_xact_lock` on the org id and the lowercased address, so two completions for a new address produce one row.

## Who writes what

| Writer | Writes |
|---|---|
| Flows consent callback | new row, or replacement of both grants and `smtp_host` on `needs_reconnect` |
| Flows `EmailType.deactivate` | removes `access_token`, `refresh_token`, `graph_send_access_token`, and `graph_send_refresh_token` during release |
| email-proxy (companion change) | refreshed Outlook and Graph access tokens, the newest refresh token written to both refresh keys, and `oauth_status=needs_reconnect` on `invalid_grant` |
| Generic email claim | unchanged; does not set `oauth_provider` |
