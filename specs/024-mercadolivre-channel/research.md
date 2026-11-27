# Research: Create the Mercado Livre channel in Flows

Phase 0 of `/speckit-plan`. The spec has no `NEEDS CLARIFICATION` marker. This file records the technical decisions the spec left to planning, each checked against the code in this repository.

## R1. Where the one-active-channel-per-seller rule lives

- **Decision**: a partial unique constraint on `Channel`, declared in `Channel.Meta.constraints` and shipped by one migration:
  - fields `("channel_type", "address")`
  - condition `channel_type = 'ML' AND is_active = true`
  - a named constant for the constraint name, used by the model and by the type.
- **Rationale**:
  - FR-014 asks for a database guarantee under concurrent creation. Only the database can serialize two inserts: the second insert waits for the first transaction and then fails.
  - `Channel` has no uniqueness rule today (verified: no `UniqueConstraint` or `unique_together` in `temba/channels`). The index on `address` from migration `0136_add_adress_index` is a plain index.
  - The condition on `channel_type = 'ML'` leaves every other type untouched. Existing duplicates of other types (for example phone numbers) cannot make the migration fail.
  - `is_active = true` matches `Channel.release`, which sets `is_active = False` (`temba/channels/models.py`). A released channel frees the seller (spec scenario 5).
  - A Django constraint is tracked by `makemigrations`, so `./code_check.py` catches a missing migration. `temba/sql/current_indexes.sql` documents only hand-written indexes and is not needed.
- **Alternatives considered**:
  - A check in the claim form, as Telegram, Slack and Discord do. It is per organization and has no concurrency guarantee. It also does not exist yet, because this feature has no claim view.
  - An advisory lock plus a query, as the Outlook consent flow does (`_lock_mailbox` in `types/email/outlook.py`). It only protects code that takes the lock, and a creation path that skips it would still create a duplicate.
  - A non-partial unique index on `(channel_type, address)`. It would count released channels and block reconnecting a seller.
  - One generic constraint for all channel types. Out of scope (Principle XVI) and unsafe on existing data.

## R2. How the conflict reaches the caller

- **Decision**: `Channel.create` translates the constraint violation into one dedicated exception, `ChannelAddressConflict`, a subclass of Django's `ValidationError` with code `address_conflict` and a generic message that names no organization, user or channel.
  - The insert for a type that declares the constraint runs inside `transaction.atomic()`, so the failed insert is a savepoint and does not break the caller's transaction.
  - The violation is identified by the constraint name (`diag.constraint_name` of the driver error), not by matching message text. The implementation confirms with a test that the driver reports the index name.
  - Other `IntegrityError`s are re-raised unchanged.
- **Rationale**:
  - FR-015, FR-016 and FR-017: the same error for a sequential and a concurrent duplicate, no tenant information, reported where the channel is created.
  - `ValidationError` is what claim forms and the WAC `activate` already use, so a later claim view can show it without a new mapping.
  - Wrapping only the types that declare the constraint keeps the transaction behavior of every other type as it is.
- **Alternatives considered**:
  - A pre-check query before the insert. It adds a second code path that the database rule makes redundant, and it still needs the constraint for the race.
  - Reusing the phone claim message. It names the other organization and user, which the spec forbids (FR-016).

## R3. Address validation and normalization

- **Decision**: a new optional hook on `ChannelType`, `clean_address(address)`, with a default that returns the address as it is. `Channel.create` calls it before building the row. `MercadoLivreType.clean_address` removes surrounding whitespace, requires a non-empty value of digits only, requires at most 255 characters, and raises `ValidationError` otherwise.
- **Rationale**:
  - FR-007 needs normalization before the insert. If the address were cleaned later (for example in `activate`), `" 123 "` and `"123"` would be two different values for the constraint.
  - There is no claim form in this feature, so validation cannot live in a form as in other types.
  - The default keeps every existing type unchanged.
- **Alternatives considered**: validating inside `activate` (too late, row and constraint value already written); validating only in the future claim form (leaves `Channel.create` open to bad addresses).

## R4. Contact fields

- **Decision**: a use case `ensure_mercadolivre_contact_fields(org, user)` in `temba/channels/types/mercadolivre/usecases.py`, called from `MercadoLivreType.activate(channel)` with `channel.org` and `channel.created_by`.
  - For each of the seven keys, an existing active user field with that key is reused without any change.
  - A missing key is created with `ContactField.get_or_create(..., value_type=ContactField.TYPE_TEXT)` from a constant of key and label. `get_or_create` already takes the per-key org lock.
  - Before each creation the use case compares the active user field count with `org.get_limit(Org.LIMIT_FIELDS)`. If there is no room it logs a warning with the org id only, sends the same Sentry warning as the internal contact fields fallback, and skips the remaining fields. It does not raise.
- **Rationale**:
  - Text fields are the established pattern: `temba/projects/usecases/contact_field_creation.py` (Live Desk copilot fields) and the internal fallback in `temba/api/v2/internals/contacts/serializers.py` both create text fields from constants.
  - `ContactField.get_or_create` does not check the field limit (verified), so the check is explicit. The internal fallback is the precedent for "log and skip" at the limit.
  - `get_or_create` updates label and type of an existing field when they differ. Calling it only for missing keys is what makes FR-010 (reuse unchanged) true.
  - A use case in the type directory has a precedent: `types/whatsapp_cloud/usecases.py`.
  - Labels are plain words that pass `ContactField.is_valid_label` (letters, digits, spaces), for example `ML Pack ID`. Keys pass `ContactField.is_valid_key` and are not reserved.
- **Alternatives considered**: creating the fields in `Channel.create` for all types (not generic); creating them lazily when Mailroom first writes (the reply cannot be delivered if they are missing, which is the point of the spec); raising an error at the limit (the channel row already exists by then, see R5).

## R5. Failure after the channel row exists

- **Decision**: follow the existing types. `MercadoLivreType` keeps the default `async_activation = True`, like `WhatsAppCloudType`. `Channel.create` inserts the row and runs `activate` through `on_transaction_commit`. A failure in `activate` does not remove the channel.
- **Rationale**:
  - Verified in `Channel.create`: with `async_activation` the activation runs after commit, and only the synchronous mode releases the channel on failure.
  - `on_transaction_commit` runs the function at once when `CELERY_TASK_ALWAYS_EAGER` is set, so tests see the fields right after `Channel.create`.
  - The field use case is idempotent, so running it again repairs a partial result. The limit case does not raise, so the usual failure is only a database error.
- **Alternatives considered**: synchronous activation (the failure path calls `release`, which leaves an inactive row and queues interrupts and failed-message tasks); creating the fields before the row (needs the org and user before the channel exists and breaks the type's `activate` contract).

## R6. URN scheme and path rule

- **Decision**: in `temba/contacts/models.py`:
  - a `MERCADOLIVRE_SCHEME = "mercadolivre"` constant and a `SCHEME_CHOICES` entry with the label `Mercado Livre identifier`;
  - a named constant for the digits-only path pattern, used by one branch in `URN.validate`;
  - no other change. `URN.identity()` already drops the display and `ContactURN` already has `unique_together = ("identity", "org")`.
- **Rationale**: verified that the `weniwebchat`, `slack` and `teams` schemes touch only these places. The pattern lives in one constant, so a later change to `mercadolivre:{buyer_id}:{pack_id}` touches one place (spec edge case). `URN.format` already shows the display when present (FR-003).
- **Migration**: the new scheme needs none. `ContactURN.scheme` is a plain `CharField(max_length=128)` without `choices` (`temba/contacts/models.py`), so changing `SCHEME_CHOICES` does not change the schema. The only migration of this feature is the constraint in R1.
- **Alternatives considered**: sharing the existing `telegram`/`instagram` branch (it would hide the rule inside another scheme's branch and make a later change riskier).
- **Locale**: the label is a new string. `locale/en_US`, `locale/es`, `locale/pt_BR` and `locale/ro` already carry the neighboring `... identifier` strings, so the same four files receive the new entry.

## R7. Channel type registration and layout

- **Decision**:
  - Directory `temba/channels/types/mercadolivre/` with `__init__.py`, `type.py`, `views.py`, `usecases.py` and `tests.py`. The directory name is the slug (`types/__init__.py` takes it from the module name) and equals the scheme, like `instagram`, `slack` and `teams`.
  - Class `MercadoLivreType`, registered in `CHANNEL_TYPES` in `temba/settings_common.py`.
  - Attributes: `code = "ML"`, social-media category, `name = "Mercado Livre"`, `schemes = [URN.MERCADOLIVRE_SCHEME]`, `max_length = 350`, `attachment_support = True`, `show_config_page = False`, no `claim_view`, default icon.
  - `views.py` holds no view. It stays as a module with a docstring that says the claim view arrives with the OAuth feature, because the constitution lists `views.py` in the minimum layout.
- **Rationale**: verified that `channel_claim.haml` lists a type only when `has_claim_view` is true, and `ChannelType.get_urls` returns no URL without a claim view. `get_configuration_template` falls back to an empty string when the type has no config template, and `show_config_page = False` follows WAC and Instagram.
- **Alternatives considered**: directory `ml` (code-like, hides the product name) or `mercado_livre` (neighbors usually match the scheme).

## R8. Courier placeholder URL

- **Decision**: `courier_url = r"^ml/receive"`, one path for all sellers with no channel UUID.
- **Rationale**: `temba/channels/urls.py` registers every type's `courier_url` under `^c/` as a placeholder that errors if reached directly, and neighbors without a UUID use the same shape (`^ig/receive`, `^wac/receive`). The code `ML` lowercased gives the prefix.
- **Open dependency**: the real route is served by Courier. The Courier handler for this type must use the same path (Courier task CO-01). This is recorded in the contract file and in the release note. It does not block this repository.

## R9. Test approach

- **Decision**:
  - `temba/channels/types/mercadolivre/tests.py`: a `TembaTest` class for the type (create, address cleaning, conflict in one org and across orgs, reconnect after release, two sellers, fields created, reused, limit, kept after release, claim page and list, no flow) and a `TembaNonAtomicTest` class for two simultaneous creations.
  - URN cases added to the existing `URNTest` in `temba/contacts/tests.py`.
- **Rationale**:
  - The constitution asks for `TembaTest` and a channel-type test in the pattern of a neighbor (`whatsapp_cloud/tests.py`).
  - `TembaTest` is atomic, so two real concurrent transactions need `TembaNonAtomicTest`. `OutlookConsentRaceTest` in `types/email/tests.py` is the model: two threads, a barrier, `connections.close_all()` in each worker, then an assertion that exactly one channel exists.
- **Migration check**: `./code_check.py` reports a missing migration. Because the ML type is new, no `ML` row can exist before release. The quickstart adds a read-only SQL check to confirm it on each environment before deploy.

## R10. Peak load and migration cost

- **Decision**: no throttling, queue or cache.
- **Rationale**: channel creation is a rare write. The lookup by type and address uses the existing `address` index and the new partial index. `AddConstraint` builds a unique index with a short write lock on `channels_channel`, a small table, and the index has zero rows at creation.
- **Rollback**: reverse the migration to drop the constraint, then revert the code. ML channels created meanwhile would then lose the guarantee, so rollback is only safe before the first real seller is connected.
