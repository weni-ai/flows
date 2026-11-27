---

description: "Task list for the Mercado Livre channel in Flows"
---

# Tasks: Create the Mercado Livre channel in Flows

**Input**: Design documents from `/specs/024-mercadolivre-channel/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/identifiers.md](contracts/identifiers.md), [quickstart.md](quickstart.md)

**Tests**: Included. The spec has a Test Strategy and constitution Principle XIV requires a full-flow test plus failure paths. Write each test group first and confirm it fails before the implementation tasks of the same story.

**Organization**: Tasks are grouped by user story. The stories behave independently, but they edit some of the same files (`temba/channels/models.py`, `temba/channels/types/mercadolivre/type.py` and `temba/channels/types/mercadolivre/tests.py`), so work them in the order below, not in parallel.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story the task serves (US1 to US4)
- Paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: the type directory the later tasks fill.

- [ ] T001 Create `temba/channels/types/mercadolivre/__init__.py` empty for now (T004 adds the `MercadoLivreType` export, because the class does not exist yet) and `temba/channels/types/mercadolivre/views.py` holding only a docstring that says the claim view arrives with the OAuth connection feature (RP-03)

---

## Phase 2: Foundational (blocks all user stories)

**Purpose**: the scheme and the registered type that every story needs.

**⚠️ CRITICAL**: no user story work can begin until this phase is complete.

- [ ] T002 Add `MERCADOLIVRE_SCHEME = "mercadolivre"` and its `SCHEME_CHOICES` entry with the label `_("Mercado Livre identifier")` in `temba/contacts/models.py` (FR-001). No migration is needed: `ContactURN.scheme` has no `choices`
- [ ] T003 [P] Add `msgid "Mercado Livre identifier"` with a translation after the `Teams identifier` entry in `locale/en_US/LC_MESSAGES/django.po`, `locale/es/LC_MESSAGES/django.po`, `locale/pt_BR/LC_MESSAGES/django.po` and `locale/ro/LC_MESSAGES/django.po`, then regenerate the tracked `django.mo` file of each of the four locales
- [ ] T004 Create `temba/channels/types/mercadolivre/type.py` with `MercadoLivreType` and named constants (FR-005, FR-008, FR-021):
  - the type-code constant (value `"ML"`) is defined once in `temba/channels/models.py` in this task, and `code` in `type.py` is set from it. T008 reuses it in the constraint condition
  - social-media category, `name = "Mercado Livre"`
  - export `MercadoLivreType` in `temba/channels/types/mercadolivre/__init__.py`, same style as `temba/channels/types/whatsapp_cloud/__init__.py`
  - `schemes = [URN.MERCADOLIVRE_SCHEME]`, `courier_url = r"^ml/receive"`, `max_length = 350`, `attachment_support = True`, `show_config_page = False`
  - no `claim_view`, default icon, default `async_activation`

  Then register `"temba.channels.types.mercadolivre.MercadoLivreType"` in the channel types list of `temba/settings_common.py`
- [ ] T005 Run `poetry run coverage run manage.py test temba.channels.types.whatsapp_cloud temba.channels.tests` and confirm that registering the new type breaks no existing channel test

**Checkpoint**: the scheme and the `ML` type exist. User stories can start.

---

## Phase 3: User Story 1 - A seller maps to exactly one active channel (Priority: P1) 🎯 MVP

**Goal**: at most one active `ML` channel per address, across all organizations, including two simultaneous connections, with a clear conflict error.

**Independent Test**: create an ML channel for seller `415458330`, then try to create a second active one, sequentially and from two threads. One active channel remains.

### Tests for User Story 1

> Write these first and confirm they fail.

- [ ] T006 [US1] In `temba/channels/types/mercadolivre/tests.py`, add `MercadoLivreChannelUniquenessTest(TembaTest)` covering spec US1 scenarios 1, 2, 3, 5 and 6: first channel, duplicate in the same org, duplicate in another org, reconnect after `release`, two different sellers. Assert the exception is `ChannelAddressConflict` with code `address_conflict`, that no second row exists, and that the message contains no organization or user name (FR-013, FR-015, FR-016)
- [ ] T007 [US1] In `temba/channels/types/mercadolivre/tests.py`, add `MercadoLivreAddressRaceTest(TembaNonAtomicTest)` modeled on `OutlookConsentRaceTest` in `temba/channels/types/email/tests.py`: two threads on a `threading.Barrier`, `connections.close_all()` in each worker, then assert exactly one channel exists, one success and one `ChannelAddressConflict`, and that each of the seven `ml_*` fields exists exactly once (FR-014, FR-015, spec US1 scenario 4)

### Implementation for User Story 1

- [ ] T008 [US1] In `temba/channels/models.py`, add the named constant for the constraint name (the `ML` type code constant already exists from T004 and is the only definition), a `unique_active_address_constraint = None` attribute on `ChannelType`, the `ChannelAddressConflict(ValidationError)` exception with code `address_conflict` and a generic message, and the partial `UniqueConstraint` in `Channel.Meta.constraints` on `("channel_type", "address")` with condition `channel_type = ML code AND is_active = True` (FR-013, FR-014)
- [ ] T009 [US1] In `Channel.create` in `temba/channels/models.py`, for a type that declares `unique_active_address_constraint`, run the insert inside `transaction.atomic()` and turn an `IntegrityError` whose `diag.constraint_name` matches into `ChannelAddressConflict`. Re-raise any other error. Leave the path of types without the attribute unchanged (FR-015, FR-017)
- [ ] T010 [US1] Generate the migration with `poetry run python manage.py makemigrations channels -n ml_active_address_unique` as `temba/channels/migrations/0139_ml_active_address_unique.py`. Check that it depends on `0138_auto_20260910_2044`, holds one `AddConstraint` and no data step, and uses the literal type code and constraint name (no imports from model code), with a comment pointing to the model constants. The literals must equal the model values (FR-019)
- [ ] T011 [US1] In `temba/channels/types/mercadolivre/type.py`, set `unique_active_address_constraint` to the constraint name constant
- [ ] T012 [US1] Run `poetry run coverage run manage.py test temba.channels.types.mercadolivre` and confirm T006 and T007 pass. This also confirms the driver reports the index name for a partial unique index. If it does not, adjust T009 to identify the violated index by its name and keep the tests

**Checkpoint**: one active `ML` channel per seller is guaranteed by the database. This is the MVP.

---

## Phase 4: User Story 2 - A buyer is one contact identity per organization (Priority: P1)

**Goal**: `mercadolivre:{buyer_id}` is valid only with a digits-only path, the display is not part of the identity, and each organization keeps its own contact.

**Independent Test**: validate and store `mercadolivre:162981404` with two nicknames in one organization and once in another.

### Tests for User Story 2

- [ ] T013 [P] [US2] In `temba/contacts/tests.py`, add cases to `URNTest`: `mercadolivre:162981404` is valid, and `mercadolivre:abc`, a symbol path, an empty path and the composite `mercadolivre:162981404:2000000089077943` are invalid. `URN.identity` of two URNs with different displays is the same, and `URN.format` shows the display (FR-002, FR-003, spec US2 scenarios 1, 2 and 4)
- [ ] T014 [US2] In `temba/contacts/tests.py`, add a case to `ContactURNTest`: the same `mercadolivre` identity stored in two organizations gives one `ContactURN` in each, and storing it twice in one organization gives one (FR-004, spec US2 scenario 3)

### Implementation for User Story 2

- [ ] T015 [US2] In `temba/contacts/models.py`, add a named constant for the digits-only path pattern and one branch in `URN.validate` for `MERCADOLIVRE_SCHEME` that uses only that constant, so the path rule lives in one place (FR-002)
- [ ] T016 [US2] Run `poetry run coverage run manage.py test temba.contacts.tests.URNTest temba.contacts.tests.ContactURNTest` and confirm T013 and T014 pass

**Checkpoint**: the buyer URN is validated and unique per organization.

---

## Phase 5: User Story 3 - The order and question context fields exist (Priority: P1)

**Goal**: the seven `ml_*` text fields exist in the organization after its ML channel is created, created only when missing, never overwritten, kept after release.

**Independent Test**: create an ML channel in an organization with no flows and check the seven text fields. Create a second one and check nothing is duplicated.

### Tests for User Story 3

- [ ] T017 [US3] In `temba/channels/types/mercadolivre/tests.py`, add `MercadoLivreContactFieldsTest(TembaTest)` covering spec US3 scenarios 1 to 5:
  - seven text fields created
  - an existing `ml_pack_id` with another label and type is reused unchanged, the other six are created
  - a second ML channel creates no duplicate
  - at the org field limit the channel is still created, no field is added, and a warning with the org id only is logged (use `assertLogs` and patch the Sentry `capture_message` call)
  - `release` keeps the fields and their values

### Implementation for User Story 3

- [ ] T018 [US3] Create `temba/channels/types/mercadolivre/usecases.py` with a constant tuple of the seven `(key, label)` pairs and `ensure_mercadolivre_contact_fields(org, user)`: skip a key that has an active user field, compare the active user field count with `org.get_limit(Org.LIMIT_FIELDS)` before each creation, create missing fields with `ContactField.get_or_create(..., value_type=ContactField.TYPE_TEXT)`, and at the limit log a warning and send the same Sentry warning as `temba/api/v2/internals/contacts/serializers.py`, with the org id only, then stop without raising (FR-009 to FR-012)
- [ ] T019 [US3] In `temba/channels/types/mercadolivre/type.py`, add `activate(channel)` that calls `ensure_mercadolivre_contact_fields(channel.org, channel.created_by)` and nothing else (FR-009)
- [ ] T020 [US3] Run `poetry run coverage run manage.py test temba.channels.types.mercadolivre` and confirm T017 passes with the earlier tests still green

**Checkpoint**: creating an ML channel gives the organization the seven text fields.

---

## Phase 6: User Story 4 - The channel type works without flows and without a claim screen (Priority: P2)

**Goal**: the seller id is validated and normalized as the channel address, the channel and fields exist in an org with no flow, trigger or campaign, and the claim page and channel list keep working.

**Independent Test**: create a channel with a numeric address in an org with no flow, trigger or campaign, then open the claim page and the channel list.

### Tests for User Story 4

- [ ] T021 [US4] In `temba/channels/types/mercadolivre/tests.py`, add `MercadoLivreTypeTest(TembaTest)` covering spec US4 scenarios 1 to 5:
  - a numeric address creates a channel with scheme `mercadolivre`
  - the type attributes match the contract: code `ML`, `schemes == ["mercadolivre"]`, `courier_url == r"^ml/receive"`, `max_length == 350`, `attachment_support` is true, social-media category, no claim view (FR-005, FR-006, FR-008)
  - blank, `None`, non-string, non-numeric and longer-than-255 addresses raise `ValidationError` and create no channel
  - `" 415458330 "` is stored as `415458330`
  - `channels.channel_claim` and the channel list load, and no claim URL for the type is shown
  - an org with no flow, trigger or campaign has the channel and the seven fields
  - a channel of another type (WhatsApp Cloud) keeps its address untouched by the new hook

### Implementation for User Story 4

- [ ] T022 [US4] In `temba/channels/models.py`, add `ChannelType.clean_address(address)` returning the address unchanged, and call it in `Channel.create` before the creation arguments are built (FR-007). This edits the function changed in T009, so do it after Phase 3
- [ ] T023 [US4] In `temba/channels/types/mercadolivre/type.py`, override `clean_address`: raise `ValidationError` for `None` or a value that is not a string, then strip surrounding whitespace, require a non-empty digits-only value of at most 255 characters, and raise `ValidationError` otherwise (FR-007)
- [ ] T024 [US4] Run `poetry run coverage run manage.py test temba.channels.types.mercadolivre` and confirm T021 passes with the earlier tests still green

**Checkpoint**: all four stories work. The type is ready for the later OAuth connection feature.

---

## Phase 7: Polish & cross-cutting

**Purpose**: gates and release steps required by the constitution.

- [ ] T025 [P] Add one `feat:` bullet to `WENI-CHANGELOG.md` under the next unreleased version heading. Check with `git tag --list` whether `3.115.2` exists: if it does, add a new heading above it, and if it does not, use that heading. The bullet says the Mercado Livre channel type, the `mercadolivre` scheme, the seven `ml_*` contact fields and the one-active-channel-per-seller rule were added (FR-020). Do not edit `CHANGELOG.md`
- [ ] T026 Run `./code_check.py` and fix every Black (line length 119), flake8 and isort finding. Confirm it reports no missing migration, and that no new `# pragma: no cover` was added
- [ ] T027 Run `poetry run coverage run manage.py test temba.channels` and `poetry run coverage run manage.py test temba.contacts.tests.URNTest temba.contacts.tests.ContactURNTest`, matching the `channels` and `core` groups of `.github/workflows/ci.yml`
- [ ] T028 Run the read-only SQL checks from [quickstart.md](quickstart.md) section 3 on each environment before the migration (no active `ML` address with more than one channel, no active contact field keyed `mercadolivre`) and record the results in the pull request
- [ ] T029 In the pull request description state the cycle (SDD Full), how tests, the migration and the changelog were addressed, the open dependency that Courier must serve `/c/ml/receive` (Courier task CO-01), the rule that the OAuth feature (RP-03) creates the channel only after Mercado Livre confirms the `seller_id`, and that the release note names the Courier and Mailroom versions once they exist (Principle IV)

---

## Requirement coverage

| Requirement | Tasks |
|---|---|
| FR-001 scheme and label | T002, T003 |
| FR-002, FR-003, FR-004 URN rules | T013, T014, T015 |
| FR-005, FR-006, FR-008, FR-021 type | T001, T004, T021 |
| FR-007 address cleaning | T021, T022, T023 |
| FR-009 to FR-012 fields | T017, T018, T019 |
| FR-013 to FR-017 uniqueness and conflict | T006, T007, T008, T009, T011, T012 |
| FR-018 no flow dependency | T021 |
| FR-019 migration | T010, T026, T028 |
| FR-020 changelog | T025 |

This table shows that each requirement has a task and a test task. It does not show that the tests are complete.

---

## Dependencies & execution order

### Phase dependencies

- **Setup (Phase 1)**: no dependency.
- **Foundational (Phase 2)**: depends on Phase 1 and blocks every story.
- **User stories (Phases 3 to 6)**: depend on Phase 2. Run them in this order, because they share files:
  - US1 first: it changes `Channel.create` and adds the migration.
  - US2 can run beside US1, because it edits `temba/contacts/models.py` and `temba/contacts/tests.py` only.
  - US3 after US1: it adds `activate` to the same `type.py` and uses the same `tests.py`.
  - US4 after US1: T022 edits `Channel.create` again.
- **Polish (Phase 7)**: depends on the stories being complete. T025 can run at any time after Phase 2.

### Within each story

- Write the tests and confirm they fail, then implement, then run the story tests.
- In `temba/channels/models.py`: T004 (type-code constant), then T008, then T009, then T022.
- In `temba/channels/types/mercadolivre/type.py`: T004, then T011, then T019, then T023.
- In `temba/channels/types/mercadolivre/tests.py`: T006, T007, T017, T021, in this order.

### Parallel opportunities

- T003 (locale files) runs beside T002 and T004.
- T013 (`temba/contacts/tests.py`) runs beside the US1 tasks.
- T025 (changelog) runs beside any other task after Phase 2.

### Parallel example

```bash
# After T001, in parallel (different files):
Task: "T002 Add MERCADOLIVRE_SCHEME in temba/contacts/models.py"
Task: "T003 Add the locale entry in the four django.po files and regenerate the .mo files"

# During Phase 3 and Phase 4, in parallel (different files):
Task: "T008 Add the constraint and the exception in temba/channels/models.py"
Task: "T013 Add URNTest cases in temba/contacts/tests.py"
```

---

## Implementation strategy

### MVP first (User Story 1)

1. Phase 1 and Phase 2.
2. Phase 3 (US1): the one-active-channel guarantee.
3. Stop and validate with T012 and the race test.

### Incremental delivery

1. Add US2 (buyer identity), then US3 (fields), then US4 (address cleaning and no-flow check).
2. Each step ends with its own test run, and the earlier tests stay green.
3. Finish with Phase 7 before opening the pull request.

### Note on the migration

The migration in T010 is the only one of this feature. It cannot be skipped: `makemigrations` requires it once the constraint is in `Channel.Meta`, and `./code_check.py` fails without it.

---

## Notes

- Commit after each task or logical group, with Conventional Commits and a description of 50 characters or fewer.
- Do not edit the Courier or Mailroom repositories. The identifiers are in [contracts/identifiers.md](contracts/identifiers.md).
- Validation checks formats only. Telling the buyer, pack and order ids apart is Courier's job.
