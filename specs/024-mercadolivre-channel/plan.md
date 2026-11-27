# Implementation Plan: Create the Mercado Livre channel in Flows

**Branch**: `feat/meli-channel` | **Date**: 2026-11-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/024-mercadolivre-channel/spec.md`

**Cycle**: SDD Full. The change adds a channel type, ships a migration and introduces identifiers that Courier and Mailroom adopt later.

## Summary

Flows gets a Mercado Livre channel type `ML`, a URN scheme `mercadolivre`, seven org-level text contact fields, and a platform-wide rule of at most one active `ML` channel per seller.

Technical approach, from [research.md](research.md):

- **Scheme**: a constant, a label and a digits-only path rule held in one named pattern, in `temba/contacts/models.py`.
- **Type**: a new `temba/channels/types/mercadolivre/` directory following WhatsApp Cloud. No claim view, default activation, address is the seller id.
- **One channel per seller**: a partial unique constraint on `Channel` for `channel_type = 'ML'` and `is_active`, shipped by one migration. `Channel.create` translates its violation into `ChannelAddressConflict`, a `ValidationError` with a generic message.
- **Address cleaning**: a new optional `ChannelType.clean_address` hook, called by `Channel.create` before the insert.
- **Fields**: a use case that creates only the missing text fields, called from the type's `activate`, with a "log and skip" behavior at the org field limit.
- **Tests**: a `TembaTest` class for the type, URN cases in `URNTest`, and a `TembaNonAtomicTest` race test modeled on `OutlookConsentRaceTest`.

## Technical Context

**Language/Version**: Python `>=3.10,<3.12` (CI uses 3.11)

**Primary Dependencies**: Django `^3.2.6`, Django REST Framework (not touched), Poetry. No new dependency.

**Storage**: PostgreSQL. One new partial unique constraint on `channels_channel`. No new table, no Redis, no Elasticsearch change.

**Testing**: Django test runner through `poetry run coverage run manage.py test`. `TembaTest` for the type, `TembaNonAtomicTest` for the concurrent case.

**Target Platform**: Flows backend service (Linux, Celery workers and web processes, stateless).

**Project Type**: Web service (Django monolith, `temba/<app>/`).

**Performance Goals**: not a hot path. Channel creation is a rare write.

**Constraints**:
- Backward compatible migration, same change set as the model change (Principle IV).
- No behavior change for any existing channel type.
- The conflict error must not reveal another organization, user or channel (FR-016).
- Validation checks formats only. Telling buyer, pack and order ids apart is Courier's job.

**Scale/Scope**: one new channel type, one scheme, one constraint, seven fields per organization.

### Peak Load (Principle XII)

Declared peak: a few ML channel creations per minute across the platform, a rare, human or system-triggered write. The webhook lookup by channel type and address is served by the existing `address` index and the new partial index. The feature adds no process, queue or in-memory state, and web and worker processes stay stateless. `AddConstraint` builds a unique index with a short write lock on `channels_channel`, a small table, and the new index has no rows when it is built.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Before Phase 0

| Principle | Result | Note |
|---|---|---|
| I. Version control and review | Pass | PR to `main` with green `ci.yml` |
| II. Security and secrets | Pass | No secret stored. `config` stays empty. No new dependency |
| III. Observability | Pass | One structured warning at the field limit, with the org id only |
| IV. Versioned contracts | Pass with note | New identifiers only, nothing existing changes. Migration ships with the model change. The release note names the Courier and Mailroom versions once they exist ([contracts/identifiers.md](contracts/identifiers.md)) |
| V. Specification traceability | Pass | Spec opens with `Origin Without Product Spec`, each acceptance criterion maps to a test in Test Strategy |
| VI. No silent divergence | Not applicable | No product spec |
| VII. Commit messages | Pass | Atomic conventional commits, description of 50 characters or fewer |
| VIII. Changelog | Pass | One `feat` bullet in `WENI-CHANGELOG.md` under the next unreleased heading (FR-020) |
| IX. Never trust the client | Pass | The address is validated at `Channel.create`, on the server, before the insert |
| X. Fail gracefully | Pass | No outbound call. The conflict is a defined error, not a crash |
| XI. Bounded retry over REST | Not applicable | No REST propagation |
| XII. Scalability and peak load | Pass | Declared above |
| XIII. Diagnosable errors | Pass | The warning carries the opaque org id and no personal data |
| XIV. Tests exercise flows | Pass | Plan has a full-flow test plus failure paths: conflict, bad address, field limit, race |
| XV. Explicit over clever | Pass | Named constants for the type code, constraint name, path pattern, field keys and labels. Comments state why |
| XVI. Contained changes | Pass with note | Two small additions to the shared `ChannelType` and `Channel.create` (an address hook and a constraint name). Both default to no behavior change, and both are needed for FR-007, FR-013 and FR-017 |
| XVII. Explicit, scoped authorization | Not applicable | No endpoint and no permission change |
| Backend standards | Pass | New type under `temba/channels/types/mercadolivre/` with `type.py`, `views.py`, `tests.py`, `__init__.py`. The type code and scheme are consistent with the contract for Courier. `./code_check.py`. Locale strings for EN, ES, PT and RO |

No violation. No `NEEDS CLARIFICATION` marker remains in the spec.

### After Phase 1

| Principle | Result | Note |
|---|---|---|
| IV | Pass | [contracts/identifiers.md](contracts/identifiers.md) lists the identifiers, the lookup guarantee and the errors. The Courier route `/c/ml/receive` is the one open dependency, owned by Courier task CO-01, and does not block this repository |
| XIV | Pass | [quickstart.md](quickstart.md) maps every scenario to an expected result. The race test follows the Outlook race test |
| XVI | Pass | [data-model.md](data-model.md) confirms the shared additions have defaults that leave every other type unchanged |
| All others | Unchanged | No design decision changed an earlier result |

## Project Structure

### Documentation (this feature)

```text
specs/024-mercadolivre-channel/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── identifiers.md   # Phase 1 output
├── checklists/
│   └── requirements.md  # /speckit-specify output
└── tasks.md             # Phase 2 output (/speckit-tasks command)
```

### Source Code (repository root)

```text
temba/
├── contacts/
│   ├── models.py                         # URN scheme constant, label, path pattern, validate branch
│   └── tests.py                          # URNTest cases for the new scheme
├── channels/
│   ├── models.py                         # ChannelType.clean_address, unique_active_address_constraint,
│   │                                     # ChannelAddressConflict, Channel.Meta constraint, Channel.create change
│   ├── migrations/
│   │   └── 0139_<name>.py                # AddConstraint, depends on 0138_auto_20260910_2044
│   └── types/
│       └── mercadolivre/
│           ├── __init__.py               # exports MercadoLivreType
│           ├── type.py                   # MercadoLivreType, constants
│           ├── views.py                  # docstring only, claim view arrives with RP-03
│           ├── usecases.py               # ensure_mercadolivre_contact_fields
│           └── tests.py                  # TembaTest and TembaNonAtomicTest classes
├── settings_common.py                    # CHANNEL_TYPES gets the new class
locale/
├── en_US/LC_MESSAGES/django.po           # "Mercado Livre identifier"
├── es/LC_MESSAGES/django.po
├── pt_BR/LC_MESSAGES/django.po
└── ro/LC_MESSAGES/django.po
WENI-CHANGELOG.md                         # one feat bullet
```

**Structure Decision**: a single Django project. The new type follows the layout of WhatsApp Cloud (type, views, tests, `usecases.py` in the type directory). `views.py` holds no view because the constitution lists it in the minimum layout and the claim view belongs to the later OAuth feature. The only shared files that change are `temba/channels/models.py` and `temba/contacts/models.py`, plus the type list in `settings_common.py`.

## Design by component

### `temba/contacts/models.py`

- Add `MERCADOLIVRE_SCHEME`, its `SCHEME_CHOICES` entry (`Mercado Livre identifier`) and a named constant for the digits-only path pattern.
- Add one branch in `URN.validate` for the scheme. It uses only the pattern constant, so the path format lives in one place.
- No change to `identity`, `format` or `ContactURN`.

### `temba/channels/models.py`

- `ChannelType.clean_address(address)` returns the address by default.
- `ChannelType.unique_active_address_constraint = None` by default.
- `ChannelAddressConflict(ValidationError)` with code `address_conflict` and a generic message.
- `Channel.Meta.constraints` holds the partial unique constraint, using a named constant for the name and one for the type code. These constants are defined only here. `type.py` imports them, because the reverse import would be circular.
- `Channel.create` calls `clean_address` before building the row. For a type that declares the constraint, the insert runs in `transaction.atomic()` and an `IntegrityError` whose constraint name matches becomes `ChannelAddressConflict`. Any other error is re-raised. Types that do not declare the constraint keep today's code path.

### `temba/channels/types/mercadolivre/type.py`

- Attributes as listed in [data-model.md](data-model.md).
- `clean_address` rejects `None` and any value that is not a string, then strips, and requires digits only, non-empty and at most 255 characters. Every rejection is a `ValidationError`.
- `activate(channel)` calls the field use case with `channel.org` and `channel.created_by`. It does nothing else, because the type has no external call.

### `temba/channels/types/mercadolivre/usecases.py`

- A constant tuple of the seven `(key, label)` pairs.
- `ensure_mercadolivre_contact_fields(org, user)`: for each pair, skip if an active user field with the key exists, check the limit, then `ContactField.get_or_create(..., value_type=ContactField.TYPE_TEXT)`.
- At the limit: log a warning and send the same Sentry warning as the internal contact fields fallback, with the org id only, then stop.

### Migration

- One `AddConstraint` for the partial unique constraint. No data step. The migration uses the literal values of the type code and the constraint name, not imports, so it does not change if the constants change later. A comment points to the model constants.

### Tests

- Mapped one-to-one with the spec Test Strategy and the scenario table in [quickstart.md](quickstart.md).

## Implementation risks

| Risk | Consequence | Handling |
|---|---|---|
| The driver does not report the index name for a partial unique index | The conflict would not be recognized and a raw `IntegrityError` would reach the caller | A test asserts `ChannelAddressConflict` for both sequential and concurrent duplicates. If the name is not reported, fall back to checking the violated index by its name in the error and keep the test |
| `Channel.create` is shared by every channel type | A mistake would affect other types | The new code is behind the hook default and the `None` constraint attribute. The existing channel tests run in the same CI group |
| The field use case runs after commit in production | A database error leaves the channel without all fields | The use case is idempotent and the limit case does not raise. The quickstart staging check confirms the seven fields |
| The Courier route differs from `/c/ml/receive` | Courier could not match the type | Open dependency owned by Courier task CO-01, recorded in the contract file and the release note |
| An organization already has a field keyed `mercadolivre` | The key becomes reserved, as for every other scheme | The quickstart SQL check lists such organizations before deploy. No code handling, per the spec |
| `ContactField.get_or_create` has no database constraint on `(org, key)` | Two creations of the same key at the same time could duplicate it | It already takes the per-key org lock. The use case only calls it for missing keys |

## Complexity Tracking

No Constitution Check violation. The two additions to shared channel code (the address hook and the constraint name) are the smallest change that gives FR-007, FR-013 and FR-017, as explained in [research.md](research.md) R1 to R3.
