# Data Model: Create the Mercado Livre channel in Flows

Entities touched by this feature and the rules the spec attaches to them. Names of constants are listed so tasks and tests use the same ones.

## Channel (changed)

| Field | Rule for type `ML` | Source |
|---|---|---|
| `channel_type` | `"ML"`, at most 3 characters | FR-005 |
| `address` | The seller id. Required, digits only, surrounding whitespace removed, at most 255 characters | FR-007 |
| `schemes` | `["mercadolivre"]` | FR-005 |
| `config` | Empty. This feature stores no token and no switch | Out of scope (RP-03, RP-04, RP-05) |
| `country` | None | Channel.create rule |
| `is_active` | `False` after `release`. An inactive row does not count for uniqueness | FR-013 |

**Constraint (new)**: one partial unique constraint.

| Property | Value |
|---|---|
| Fields | `(channel_type, address)` |
| Condition | `channel_type = 'ML' AND is_active = true` |
| Name | A named constant shared by the model and the type, for example `channels_channel_ml_active_address_uniq` |
| Scope | The whole platform, all organizations |
| Effect | A second active `ML` channel with the same address fails at insert, for sequential and concurrent creation |

**Migration**: one `AddConstraint`, depending on `0138_auto_20260910_2044`. No data step. It cannot fail on existing data, because no `ML` row exists before this feature.

**State transitions**

```text
(no channel) --create--> active --release--> inactive
                 |                              |
                 | same address, active exists  | same address again
                 v                              v
        ChannelAddressConflict               allowed (new active channel)
```

## ChannelType `ML` (new)

| Attribute | Value |
|---|---|
| `code` | `ML` |
| `slug` | `mercadolivre` (from the directory name) |
| `category` | Social media |
| `schemes` | `[URN.MERCADOLIVRE_SCHEME]` |
| `courier_url` | `^ml/receive` |
| `max_length` | 350 (initial value) |
| `attachment_support` | True |
| `show_config_page` | False |
| `claim_view` | None |
| `async_activation` | Default (True), as WhatsApp Cloud |
| `unique_active_address_constraint` | The constraint name above |

**Shared base class additions** (`ChannelType`, no behavior change for existing types):

| Addition | Default | Used by ML |
|---|---|---|
| `clean_address(address)` | Returns the address unchanged | Strips, checks digits only and length |
| `unique_active_address_constraint` | `None` | The constraint name, so `Channel.create` can translate its violation |

## ChannelAddressConflict (new exception)

- Subclass of Django `ValidationError`, code `address_conflict`.
- Generic message. It never contains an organization, user or channel name.
- Raised by `Channel.create` only when the violated constraint is the one declared by the type.

## URN scheme `mercadolivre` (new)

| Property | Value |
|---|---|
| Constant | `URN.MERCADOLIVRE_SCHEME = "mercadolivre"` |
| Label | `Mercado Livre identifier` (translated in `en_US`, `es`, `pt_BR`, `ro`) |
| Path rule | Digits only, held in one named pattern constant used by `URN.validate` |
| Identity | `mercadolivre:{path}`. `URN.identity()` drops the display |
| Display | The nickname. A label only, not part of the identity |
| Uniqueness | `ContactURN` `unique_together = ("identity", "org")`, unchanged |

Side effect: `mercadolivre` becomes a reserved contact field key, as every other scheme is (`Contact.RESERVED_FIELD_KEYS`). No special handling.

## ContactField (seven new text fields per organization)

All are user fields of type text, created only when missing.

| Key | Label | Used for |
|---|---|---|
| `ml_kind` | `ML Kind` | Post-sale or pre-sale |
| `ml_buyer_id` | `ML Buyer ID` | Buyer |
| `ml_nickname` | `ML Nickname` | Buyer nickname |
| `ml_pack_id` | `ML Pack ID` | Post-sale conversation |
| `ml_order_ids` | `ML Order IDs` | Post-sale orders |
| `ml_item_id` | `ML Item ID` | Pre-sale item |
| `ml_question_id` | `ML Question ID` | Pre-sale question |

**Rules**

- An existing active user field with the same key is reused without any change to label, type or values (FR-010).
- The number of active user fields is compared with `Org.LIMIT_FIELDS` (250 by default) before each creation. At the limit, the remaining fields are skipped and a warning with the org id only is logged (FR-012).
- Fields are never removed when the channel is released (FR-011).
- Creation is idempotent and can be repeated.

## Not changed

- `ContactURN`, `Contact`, `Org`, flows, triggers and campaigns.
- Message, ticket and channel log models.
- Any API endpoint, serializer or permission.
