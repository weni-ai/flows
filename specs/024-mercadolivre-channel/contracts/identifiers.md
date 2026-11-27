# Contract: Mercado Livre identifiers in Flows

This feature adds no endpoint, no event and no channel config key. The contract is the set of identifiers and behaviors that Courier and Mailroom adopt later. It follows Principle IV (versioned contracts): the identifiers are new, so nothing existing changes.

## Identifiers

| Item | Value | Notes |
|---|---|---|
| Channel type code | `ML` | Must be the same text in Flows, Courier and Mailroom. `MLB` is not used because it is the ML Brazil site id |
| URN scheme | `mercadolivre` | Must be the same text in Flows, the Courier `urns` package and any Mailroom scheme list |
| URN identity | `mercadolivre:{buyer_id}` | Path is digits only. The display is the buyer nickname and is not part of the identity |
| Channel address | The seller id as a numeric string | Whitespace removed. At most 255 characters |
| Contact field type | Text | All seven fields |
| Contact field keys | `ml_kind`, `ml_buyer_id`, `ml_nickname`, `ml_pack_id`, `ml_order_ids`, `ml_item_id`, `ml_question_id` | Created per organization when its ML channel is created |
| Courier placeholder path | `/c/ml/receive` | One path for all sellers. The Courier handler must serve the same path (Courier task CO-01) |

## What Flows validates and what it does not

| Item | Flows | Other services |
|---|---|---|
| URN path | Checks the format only (digits only) | Courier decides which id is the buyer, pack or order |
| Channel address | Checks the format only (digits only, length) | Courier resolves the channel by type and address |
| Contact fields | Creates the fields as text | Mailroom writes the values and checks how it writes to a field that already exists with another type. The format of `ml_order_ids` is decided with Mailroom |

## Channel lookup guarantee

For every seller id there is at most one active channel of type `ML` with that address, in any organization. A lookup by channel type and address therefore returns zero or one active channel.

The guarantee comes from a database constraint, so it also holds for two connections created at the same time and for any code that creates the channel.

Because the rule is platform-wide and Flows does not prove who owns a seller id, the feature that connects a seller (OAuth, RP-03) must create the channel only after Mercado Livre has confirmed the `seller_id`. Otherwise an organization could hold a seller id that is not its own.

## Errors

| Situation | Result |
|---|---|
| Second active channel for the same seller | `ChannelAddressConflict` (a `ValidationError`, code `address_conflict`). The message names no organization, user or channel |
| Blank, missing or non-numeric address | `ValidationError` from the address check |
| Organization at its contact field limit | The channel is created, the missing fields are skipped, a warning with the org id is logged. No error is raised |

## Release note (Principle IV)

The release note for this change states that the identifiers above are new and that Courier and Mailroom adopt them in their own releases. It names the Courier and Mailroom versions once those releases exist.
