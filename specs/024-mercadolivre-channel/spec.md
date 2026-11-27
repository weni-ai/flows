# Engineering Specification: Create the Mercado Livre channel in Flows

**Repository**: weni-ai/flows — backend

**Feature Branch**: `feat/meli-channel`

**Created**: 2026-11-27

**Status**: Draft

**Input**: User description: "Create the Mercado Livre channel in Flows. Register the channel type with address equal to the seller_id and align the type code and the `mercadolivre` scheme with Courier and Mailroom. The identity is `mercadolivre:{buyer_id}` with a numeric path and the nickname as label. Expose the contact fields ml_kind, ml_buyer_id, ml_nickname, ml_pack_id, ml_order_ids, ml_item_id and ml_question_id. Prevent two active channels for the same seller, including concurrent connections. Acceptance: the same buyer keeps one contact per organization, and the webhook can resolve a single channel per seller."

**Suggested cycle**: SDD Full. The change adds a channel type, ships a migration and introduces identifiers (channel type code, URN scheme, contact field keys) that Courier and Mailroom adopt later.

**Source**: "Integração Mercado Livre — desenho técnico e tasks", Flows tasks RP-01, RP-02, RP-06 and RP-07 (phase F1 is the post-sale pilot; the channel is built for both post-sale and pre-sale).

## Origin Without Product Spec

- Product Spec: none
- Problem: Flows cannot represent a Mercado Livre (ML) seller connection. There is no channel type, no URN scheme for the ML buyer, no contact fields to carry the order or question context, and nothing prevents the same seller from being connected twice. The ML notification endpoint is shared by every seller and identifies only the seller, so two active channels for one seller would make the lookup ambiguous.
- Acceptance criteria:
  - AC-1: The buyer identity `mercadolivre:{buyer_id}` is valid and is one identity per organization, and the nickname is not part of it.
  - AC-2: The webhook can resolve one single channel per seller, including when two connections for the same seller are attempted at the same time.
  - AC-3: The buyer URN accepts only a path made of digits. Validation checks the format only.
  - AC-4: The seven `ml_*` contact fields exist in the organization after its ML channel is created, as text fields.
  - AC-5: The channel type and scheme are registered, and a type without a claim view does not break the channel pages.
  - AC-6: The channel does not depend on any flow, trigger or campaign.

## Scope in This Repository

**This repository implements**:

- The URN scheme `mercadolivre` with numeric path validation and a human label.
- The channel type `ML` whose address is the seller id, following the pattern of the existing channel types (WhatsApp Cloud `WAC` is the model).
- The seven org-level text contact fields, created when the ML channel is created.
- The platform-wide rule of at most one active ML channel per seller, enforced by the database, with a clear conflict error.
- Tests for each acceptance criterion and one `feat` bullet in `WENI-CHANGELOG.md`.

The channel serves **both post-sale and pre-sale**. Flows creates one channel per seller for both, and keeps the identifiers and fields needed by both. Behavior that differs between the two is decided and built in other services.

**Out of scope here**:

- OAuth connection, PKCE, `state`, tokens, refresh and the "needs reconnect" state (RP-03, RP-04).
- Reconnect, disconnect and the `post_sale_enabled` and `pre_sale_enabled` switches (RP-05).
- Copying ML context into outbound messages (RP-08).
- Any pre-sale or post-sale behavior that lives in Courier or Mailroom: receiving, publishing, handoff, and building the order or item context. This feature only keeps the channel ready for both.
- Any change in Courier or Mailroom, including how the contact is found or created from the URN.
- Creating contacts or writing the `ml_*` values. This feature only makes the scheme, the validation and the fields exist.
- Flow engine changes. There is no new node.
- A new channel icon glyph. The existing default icon is used.
- Adding `mercadolivre` to `SCHEMES_SUPPORTING_NEW_CONVERSATION`. The seller cannot start conversations in the MVP.

## Current State

- `URN.SCHEME_CHOICES` in `temba/contacts/models.py` has no ML scheme. `URN.VALID_SCHEMES` is derived from it, and `Contact.RESERVED_FIELD_KEYS` includes every valid scheme. Other schemes (`instagram`, `slack`, `teams`) were added the same way, with a constant and a `SCHEME_CHOICES` entry.
- Neighboring social schemes (`instagram`, `telegram`) validate the path as digits only.
- `URN.identity()` drops the display, and `ContactURN` has `unique_together = ("identity", "org")`, so one identity is one contact per organization.
- No channel type uses the code `ML` or the scheme `mercadolivre`. `Channel.channel_type` allows at most 3 characters.
- `Channel` has no uniqueness rule on `address`. `Channel.address` only has a plain index (migration `0136_add_adress_index`). The latest channels migration is `0138_auto_20260910_2044`.
- Duplicate-connection checks today live in each type's claim form and are per organization (Telegram, Slack, Discord, Line, Rocket.Chat, Android). The phone-number claim also checks across organizations, and its message names the other organization and user.
- WhatsApp Cloud (`WAC`) keeps the default activation: `Channel.create` creates the channel row first and then calls the type's `activate` after commit. A failure in `activate` does not remove the channel.
- `ChannelType.claim_view` is optional, and the claim page lists only types that have one.
- Text contact fields are created with `ContactField.get_or_create` and `value_type=TYPE_TEXT` from constants of key and label in `temba/projects/usecases/contact_field_creation.py`. The internal contact fields fallback checks the org field limit (250 by default), and when the limit is reached it logs a warning and skips the creation, without raising an error.
- The directory name of a channel type is its slug (`types/__init__.py`). Neighbors use short lowercase names, often equal to the scheme (`instagram`, `slack`, `teams`, `weniwebchat`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A seller maps to exactly one active channel (Priority: P1)

A project connects its Mercado Livre seller account. Every ML notification identifies only the seller, so the platform must find exactly one active channel for that seller, in any organization.

**Why this priority**: Without a single channel per seller, the shared notification endpoint cannot route a message, and a message could reach the wrong project. Checks inside one organization's claim form are not enough, because the webhook looks the channel up without knowing the organization.

**Independent Test**: Create an ML channel for seller `415458330`, then try to create a second active one for the same seller, sequentially and from two simultaneous attempts. Only one active channel exists at the end.

**Acceptance Scenarios**:

1. **Given** no active ML channel for a seller, **When** a channel is created with that seller id as address, **Then** it is created and is the only active ML channel for that address.
2. **Given** an active ML channel for a seller, **When** another channel is created for the same seller in the same organization, **Then** it is rejected with an error that explains the seller is already connected, and no channel is left behind.
3. **Given** an active ML channel for a seller in organization A, **When** organization B tries to connect the same seller, **Then** it is rejected with the same kind of error, and the error does not name organization A or its owner.
4. **Given** two creation attempts for the same seller at the same time, **When** both run, **Then** exactly one succeeds and the other gets the conflict error, with no extra channel and no extra fields.
5. **Given** an ML channel that was released, **When** the same seller is connected again, **Then** the new channel is created.
6. **Given** two different sellers, **When** both are connected, **Then** both channels are created and do not conflict.

---

### User Story 2 - A buyer is one contact identity per organization (Priority: P1)

A buyer writes about different orders, products or questions. The contact is the buyer, not the order or the pack, so the identity is the same each time and the platform keeps one contact and one history per buyer in each organization.

**Why this priority**: The agent and the Live Desk rely on one stable contact per buyer. An identity based on the order would split the history.

**Independent Test**: Validate and persist `mercadolivre:162981404` in one organization with two different nicknames, and in a second organization. Check that the identity is the same in the first organization and that the second organization has its own.

**Acceptance Scenarios**:

1. **Given** the identity `mercadolivre:162981404`, **When** it is stored, **Then** it is valid and unique per organization and identity.
2. **Given** a stored buyer URN, **When** the same URN is stored again with another nickname as display, **Then** the identity is the same and only the label differs.
3. **Given** another organization, **When** the same buyer id is stored there, **Then** that organization has its own contact.
4. **Given** a path with any character that is not a digit (letters, symbols, an empty path, or the composite format `buyer_id:pack_id`), **When** the URN is validated, **Then** it is rejected. Validation checks the format only. Whether the number is really the buyer id is the responsibility of the service that builds the URN.

---

### User Story 3 - The order and question context fields exist in the organization (Priority: P1)

When an organization gets its ML channel, the contact fields that carry the context become available as text fields: `ml_kind`, `ml_buyer_id`, `ml_nickname`, `ml_pack_id`, `ml_order_ids`, `ml_item_id` and `ml_question_id`. They cover post-sale (`ml_pack_id`, `ml_order_ids`) and pre-sale (`ml_item_id`, `ml_question_id`), and `ml_kind` tells which one a conversation is.

**Why this priority**: Other services write and read these fields to keep the reply going to the right order chat or question. If they do not exist, the reply cannot be delivered.

**Independent Test**: Create an ML channel in an organization that has no flows and check that the seven fields exist as text fields. Create a second ML channel in the same organization and check that nothing is duplicated.

**Acceptance Scenarios**:

1. **Given** an organization without the fields, **When** its ML channel is created, **Then** the seven text fields exist.
2. **Given** an organization that already has some of these fields active, **When** an ML channel is created, **Then** they are reused with their label, type and values unchanged, and the missing ones are created.
3. **Given** an organization with two ML channels for two sellers, **When** the second is created, **Then** the fields are not duplicated.
4. **Given** an organization that has no room under its field limit for the missing fields, **When** an ML channel is created, **Then** the channel is still created, the missing fields are skipped and a warning is logged with opaque identifiers only.
5. **Given** an ML channel that is released, **When** the organization is checked, **Then** the fields and their values are still there.

---

### User Story 4 - The channel type works without flows and without a claim screen (Priority: P2)

The ML channel type is registered with the seller id as address. It has no connection screen yet, and the organization may not use flows at all.

**Why this priority**: The channel must exist as a valid type for the later connection feature and for the agent journey. It must not depend on flows or break existing pages.

**Independent Test**: Register the type, create a channel with a numeric address in an organization with no flow, trigger or campaign, and open the channel list and the channel claim page.

**Acceptance Scenarios**:

1. **Given** the registered type, **When** a channel is created with a numeric address, **Then** it is created with the `mercadolivre` scheme.
2. **Given** a blank, missing or non-numeric address, **When** a channel is created, **Then** it is rejected.
3. **Given** an address with surrounding whitespace, **When** a channel is created, **Then** the stored address has the whitespace removed.
4. **Given** the type has no claim view, **When** the channel claim page and the channel list are opened, **Then** both work and the type does not appear as a broken option.
5. **Given** an organization with no flow, trigger or campaign, **When** its ML channel is created, **Then** the channel and the fields exist.

---

### Edge Cases

- **Address normalization**: the uniqueness rule compares the normalized address, so `" 415458330 "` and `"415458330"` are the same seller.
- **Inactive channels**: a released channel does not count for uniqueness and can be followed by a new one for the same seller.
- **Conflict across organizations**: the error text explains the conflict without revealing which organization or owner holds the seller. This differs on purpose from the phone-number claim, whose message names the other organization and user.
- **Concurrent attempts**: the database rejects the loser before any channel row exists, so no channel and no fields are left.
- **Failure after the channel exists**: if ensuring the fields fails, the channel is not removed, as for the existing channel types whose activation runs after the channel exists. The failure is logged with opaque identifiers. Ensuring the fields is idempotent, so it can be run again.
- **Existing field with the same key**: it is reused as it is, whatever its label or type. Mailroom checks that it can write to it (see Assumptions).
- **Reserved key**: adding the scheme makes `mercadolivre` a reserved contact-field key. This is the same effect as for every other scheme and gets no special handling.
- **Scheme path format**: the numeric path rule is in one place, so a later change to `mercadolivre:{buyer_id}:{pack_id}` would touch only that place.
- **Other creation paths**: the uniqueness guarantee comes from the database, so it holds for any code that creates an ML channel, not only for a future screen.
- **Pre-sale and post-sale**: the channel, the address and the buyer identity are the same for both. Pre-sale data uses `ml_item_id` and `ml_question_id`, and post-sale data uses `ml_pack_id` and `ml_order_ids`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST register the URN scheme `mercadolivre` with a human-readable label, so URNs with this scheme are valid.
- **FR-002**: The system MUST accept a `mercadolivre` URN only when its path is made of digits only. The path rule MUST live in one place.
- **FR-003**: The system MUST show the URN display (the buyer nickname) as the label when present. The display MUST NOT be part of the identity.
- **FR-004**: The buyer identity MUST be `mercadolivre:{buyer_id}`, unique per organization, whatever the order, pack, item or question.
- **FR-005**: The system MUST register the channel type with the code `ML`, the scheme `mercadolivre`, the social-media category, an initial maximum message length of 350 and attachment support on. The channel is one type for both post-sale and pre-sale.
- **FR-006**: The channel type MUST expose one webhook path shared by all sellers, with no channel identifier in it. The exact path is set during planning.
- **FR-007**: The channel address MUST be the seller id. It MUST be required, numeric, normalized by removing surrounding whitespace, and at most 255 characters.
- **FR-008**: The channel type MUST NOT require a claim view in this feature. The channel claim page and the channel list MUST keep working.
- **FR-009**: When an ML channel is created, the system MUST ensure the org-level **text** fields `ml_kind`, `ml_buyer_id`, `ml_nickname`, `ml_pack_id`, `ml_order_ids`, `ml_item_id` and `ml_question_id` exist, creating only the missing ones. The fields are created after the channel exists, the way other channel types run their activation.
- **FR-010**: An existing active field with one of these keys MUST be reused unchanged: label, type and values are not modified.
- **FR-011**: Releasing an ML channel MUST NOT remove the fields or their values.
- **FR-012**: If the organization has no room under its field limit for the missing fields, the system MUST still create the channel, skip the missing fields and log a warning that carries opaque identifiers only.
- **FR-013**: The system MUST allow at most one active ML channel per address across all organizations. Released channels MUST NOT count.
- **FR-014**: The one-active-channel rule MUST hold under concurrent creation. It MUST be guaranteed by the database, not only by a check before creating.
- **FR-015**: A rejected creation, sequential or concurrent, MUST return the same explanatory conflict error and MUST leave no channel and no fields.
- **FR-016**: The conflict error MUST NOT reveal which organization, user or channel already holds the seller.
- **FR-017**: The conflict MUST be reported where the channel is created, so any creation path gets a clear error. A later claim form MAY also check first, as other types do.
- **FR-018**: The channel MUST be creatable and usable in an organization with no flow, trigger or campaign.
- **FR-019**: The migration MUST ship in the same change set, MUST be backward compatible within the release cycle, and MUST NOT fail on existing data.
- **FR-020**: `WENI-CHANGELOG.md` MUST gain one `feat` bullet under the next unreleased version heading. A released heading MUST NOT be extended. `CHANGELOG.md` MUST NOT be rewritten.
- **FR-021**: The channel type directory, class and file layout MUST follow the existing channel types, with the constitution layout (`type.py`, `views.py`, `tests.py`, `__init__.py`).

### Key Entities

- **ML channel**: a Flows channel of type `ML` that represents one connected seller, for post-sale and pre-sale. Its address is the seller id. There is at most one active channel per seller on the platform.
- **Seller**: the Mercado Livre account that owns the sales. Its id identifies the channel and is the only thing the shared notification carries.
- **Buyer contact identity**: the identity `mercadolivre:{buyer_id}` in one organization. Its label is the nickname. Creating the contact from it is done outside Flows.
- **Context fields**: seven org-level text fields that keep the last context of a buyer conversation (kind, buyer id, nickname, pack id, order ids, item id, question id).

## Fixed Identifiers

These values are decided here and adopted by other services later.

| Item | Value |
|---|---|
| Channel type code | `ML`. It is not in use in Flows today. `MLB` is avoided because it is also the ML Brazil site id. |
| URN scheme | `mercadolivre` |
| Identity | `mercadolivre:{buyer_id}`, numeric path, display is the nickname |
| Channel address | The seller id as a numeric string |
| Contact field keys | `ml_kind`, `ml_buyer_id`, `ml_nickname`, `ml_pack_id`, `ml_order_ids`, `ml_item_id`, `ml_question_id` |
| Contact field type | Text, all seven |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every seller id, 100% of lookups by channel type and address find at most one active channel, and exactly one when the seller is connected.
- **SC-002**: When two connections for the same seller start at the same time, exactly one succeeds, in 100% of repeated runs, and the other gets the explanatory conflict error.
- **SC-003**: 100% of buyer identities for the same buyer in one organization are the same identity, whatever the order, pack, item or question, and a nickname change does not change it.
- **SC-004**: 100% of buyer URNs whose path has a non-digit character, including the composite `buyer_id:pack_id`, are rejected, and 100% of digit-only paths are accepted.
- **SC-005**: Right after an ML channel is created in an organization with room under its field limit, 100% of the seven `ml_*` fields exist as text fields, with no duplicates after a second channel.
- **SC-006**: An organization with no flow, trigger or campaign completes channel creation with no extra setup.
- **SC-007**: The channel list and the channel claim page work with the new type, with no new error.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|---|---|
| AC-1 buyer identity per org | Test that `mercadolivre:{buyer_id}` is valid, that two URNs with different displays have the same identity, and that two organizations each store their own. |
| AC-2 one channel per seller | Test sequential duplicate in one org, duplicate across two orgs, re-connection after release, and two sellers. Test two simultaneous creations and assert exactly one active channel remains. The concurrent case may need a non-atomic test base. |
| AC-3 numeric path | Test that digit-only paths are valid and that letters, symbols, an empty path and `buyer_id:pack_id` are invalid. No test claims that a number is a buyer id. |
| AC-4 fields exist | Test field creation as text, reuse of existing fields, no duplication on a second channel, and the field-limit case, where the channel is created and the missing fields are skipped with a warning. |
| AC-5 type registration | Test the type in the pattern of `temba/channels/types/whatsapp_cloud/tests.py`, plus the claim page and the channel list. |
| AC-6 no flow dependency | Test channel creation in an organization with no flow, trigger or campaign. |
| Conflict error | Test that the cross-organization error does not contain the other organization or user. |
| Migration | `./code_check.py` reports no missing migration. The new rule is checked against existing data by a migration test or a manual check recorded in the plan. |

**Flow coverage**: the complete use case is creating an ML channel for a seller, checking the fields and the rule that a second connection for the same seller is rejected. The URN, field and edge cases are sibling tests.

**Gates**: `poetry run coverage run manage.py test`, clean `./code_check.py`, green `.github/workflows/ci.yml`. Tests use `TembaTest` unless the concurrent case needs another approved base. No new `# pragma: no cover`.

## Assumptions

- Uniqueness is platform-wide, not per organization, because the notification endpoint is shared by all organizations and identifies only the seller. This goes beyond the usual per-organization check in other channel types, which cannot meet AC-2. The owner decided on 2026-11-27 to keep it, after seeing that WhatsApp Cloud and Instagram have no such rule.
- **Seller ownership (risk for later features)**: with a platform-wide rule and no proof of ownership in this feature, whoever creates the channel first holds the seller id. Today there is no claim screen, so nothing is exposed. The OAuth connection feature (RP-03) MUST create the channel only after Mercado Livre has confirmed the `seller_id`.
- The exact webhook path is defined during planning, together with the Courier receive endpoint. It is not a product decision.
- The ML seller id is numeric and has no leading zeros in practice. Normalization only removes surrounding whitespace.
- Validation of the path only checks the format. Telling a buyer id from an order id or a pack id is not possible in Flows, since all are numbers. Courier decides which id goes where, because it handles the buyer, pack and order ids. Flows only stores the channel data (the address and the config, if any) and validates formats.
- The contact is created and found from the URN in Mailroom. Whether a repeated buyer resolves to one contact, and how a nickname change is applied, is checked there.
- Contact fields are text fields, as in the existing project fields (Live Desk copilot) and the internal contact fields fallback. Mailroom checks later how it writes to a field that already exists with another type, and the format of `ml_order_ids`.
- The type directory is `temba/channels/types/mercadolivre/`, equal to the scheme like `instagram`, `slack` and `teams`, with the class named in the same style as its neighbors.
- The channel is for both post-sale and pre-sale. The `ml_item_id` and `ml_question_id` fields and `ml_kind` exist from the start, even though only post-sale is used in phase F1.
- The maximum length of 350 is an initial value. The real limit is read by the service that sends messages.
- **Peak load (Principle XII)**: channel creation is a rare, human or system-triggered write, with at most a few creations per minute across the platform. The webhook lookup by type and address is served by the existing address index and the new unique index. The feature adds no process, queue or in-memory state.
- **Contracts (Principle IV)**: the type code, the scheme and the field keys are new identifiers that other services adopt later. No existing endpoint, channel config or event payload changes. The release note names the Courier and Mailroom versions that adopt the identifiers once they exist.
- **Security (Principles II, IX and XIII)**: this feature stores no secret. The address is validated on the server at creation. The conflict error does not reveal other organizations, and the field-limit warning carries only opaque identifiers.
