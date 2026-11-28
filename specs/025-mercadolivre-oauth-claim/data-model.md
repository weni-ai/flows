# Data Model: Connect a Mercado Livre seller to Flows (OAuth claim)

This feature changes no table and adds no migration. It writes the existing `Channel` row (feature 024 schema) and keeps one short-lived record in the cache.

## Connection attempt (cache, not persisted)

One record per click on "Connect". It exists only between the start and the return, or until it expires.

| Field | Type | Rule |
|---|---|---|
| key | text | `mercadolivre-oauth-attempt:` plus the `state` value |
| `state` | text | `secrets.token_urlsafe(32)`, never reused, carries no data |
| `org_id` | integer | the org of the user at the start |
| `user_id` | integer | the user who started |
| `code_verifier` | text | `secrets.token_urlsafe(64)`, 86 characters, never leaves the server except in the token call |
| lifetime | seconds | 900 |
| used marker | key `<attempt key>:used` | written with `cache.add` by the first return, lifetime 900 |

State transitions:

```text
(none) --start--> pending --return, first, user and org match--> consumed --> (deleted)
pending --lifetime ends--> (gone)
pending --return, user or org differ--> pending (rejected, attempt stays for its owner until it expires)
consumed --return again--> rejected
```

Rules:
- A return with an unknown, expired, consumed or foreign `state` is rejected before any call to ML (FR-006, FR-007).
- The verifier is read from the attempt and is not logged (FR-019).
- A rejected return of a different user or org does not delete the attempt of its owner.

## Channel (existing table `channels_channel`)

Created at the end of a successful return through `Channel.create`, inside the transaction that feature 024 already puts around the insert for this type.

| Column | Value |
|---|---|
| `channel_type` | `ML` |
| `address` | the seller id from ML (digits), `clean_address` of feature 024 applies |
| `name` | the nickname from ML, or the seller id when the nickname is empty, cut to 128 characters |
| `schemes` | `["mercadolivre"]` |
| `role` | `SR` (send and receive) |
| `org`, `created_by`, `modified_by` | the org and user of the attempt |
| `config` | the contract below |
| `country` | not set |

The channel is created only after both ML calls are valid (FR-011). The activation of feature 024 creates the seven `ml_*` contact fields.

## Channel config contract (read by Courier and by RP-04)

| Key | Type | Value | Written by |
|---|---|---|---|
| `access_token` | text | ML access token | this feature, refreshed by RP-04 |
| `refresh_token` | text | ML refresh token, single use | this feature, replaced by RP-04 |
| `expires_at` | text | RFC 3339 UTC time of expiry | this feature, replaced by RP-04 |
| `oauth_provider` | text | `mercadolivre` | this feature |
| `oauth_status` | text | `active` (RP-04 may set `needs_reconnect`) | this feature |
| `post_sale_enabled` | boolean | `false` | this feature, changed by RP-05 |
| `pre_sale_enabled` | boolean | `false` | this feature, changed by RP-05 |

Rules:
- The tokens are never written to a log, to a Sentry event or to any answer (FR-019, FR-020).
- On release the two tokens are removed from the config in the same save that deactivates the channel (FR-027). The other keys stay.
- A new key added later is a change of this contract and must be agreed with Courier (Principle IV).

## Contact fields

No change. Feature 024 owns the seven `ml_*` fields and their creation on activation.

## Existing rule used here

The partial unique constraint of feature 024 (`channels_channel_ml_active_address_uniq`) makes the second connection of the same seller fail with `ChannelAddressConflict`, in the same org or in another. This feature maps that error to the message of FR-014 and writes nothing else.
