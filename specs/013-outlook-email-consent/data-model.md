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

The channel address is the `username` stored on the attempt. It is used only when it equals the access-token mailbox. It is not taken from the callback query.

### `config` for an Outlook channel

| Key | Type | Rule |
|---|---|---|
| `username` | string | same mailbox address |
| `password` | string | empty |
| `smtp_host` | string | `smtp.office365.com` |
| `smtp_port` | int | `587` |
| `imap_host` | string | `outlook.office365.com` |
| `imap_port` | int | `993` |
| `access_token` | string | from the token response; never rendered |
| `refresh_token` | string | from the token response; never rendered |
| `oauth_provider` | string | `microsoft` |
| `oauth_status` | string | `active` or `needs_reconnect` |
| `callback_domain` | string | `settings.HOSTNAME` |

Generic claim rows do not gain `oauth_provider` or `oauth_status`.

## Validation rules

- The callback creates or updates a channel only when the signed-in user still has `channels.channel_claim` on the org stored in the attempt.
- The confirmed address is empty, is not an email address, or differs from the access-token mailbox (`upn`, then `preferred_username`, then `unique_name`): no channel.
- Microsoft `error` query parameter, including `access_denied`, `consent_required`, and a description that contains `AADSTS65001`: no channel. The page explains the case. `error_description` is shown for any other `error` and is not logged.
- Access token fails `aud`, `iss`, `exp`, or signature: no channel.
- Token response has no `access_token` or no `refresh_token`: no channel.
- Active `EM` channel in the same org with the same address, and it is not a Microsoft channel in `needs_reconnect`: no new channel.
- Active `EM` channel in another org with the same address: allowed. Each org has its own row and its own grant.

## State transitions

```text
(no row)
    -- successful consent --> EM active, oauth_status=active

EM active, oauth_status=active
    -- consent again for the same address --> no write; admin is told it is already connected
    -- email-proxy sees invalid_grant --> oauth_status=needs_reconnect (proxy write, not Flows)
    -- admin releases the channel --> is_active=false, access_token and refresh_token removed

EM active, oauth_status=needs_reconnect
    -- successful consent for the same address --> same row, new tokens, oauth_status=active
    -- admin releases the channel --> is_active=false, tokens removed

EM inactive
    -- not a target. A later consent creates a new active row and requires a new Microsoft approval
```

The duplicate check and the insert-or-update run in one transaction after `pg_advisory_xact_lock` on the org id and the lowercased address, so two completions for a new address produce one row.

## Who writes what

| Writer | Writes |
|---|---|
| Flows consent callback | new row, or token replacement on `needs_reconnect` |
| Flows `EmailType.deactivate` | removes `access_token` and `refresh_token` during release |
| email-proxy (companion change) | refreshed `access_token`, and `oauth_status=needs_reconnect` on `invalid_grant` |
| Generic email claim | unchanged; does not set `oauth_provider` |
