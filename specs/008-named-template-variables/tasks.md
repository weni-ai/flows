# Tasks: Named WhatsApp template variables

**Input**: Design documents from `/specs/008-named-template-variables/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/whatsapp-broadcast-named.md](./contracts/whatsapp-broadcast-named.md)

**Tests**: Included — constitution IV and the product spec require ingest, contract, resolution, and positional-regression coverage.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)

## Phase 1: Setup

**Purpose**: Feature branch and Speckit artifacts

- [x] T001 Create feature directory `specs/008-named-template-variables/` with engineering spec, plan, research, data-model, contracts, and quickstart
- [x] T002 Point `.specify/feature.json` at `specs/008-named-template-variables`

---

## Phase 2: Foundational

**Purpose**: Shared helpers and schema that every story needs

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Add format/name helpers in `temba/templates/parameter_format.py`
- [x] T004 Add `parameter_format` and `parameter_policies` on `Template` and `parameter_names` on `TemplateTranslation` in `temba/templates/models.py`
- [x] T005 Add migration `temba/templates/migrations/0016_named_template_parameters.py`

**Checkpoint**: Registry columns exist; helpers normalize format without inferring from body text

---

## Phase 3: User Story 1 - Registry records format and names from sync (Priority: P1) 🎯 MVP

**Goal**: Named templates sync with names; positional default; read surfaces publish format/names; status-only updates do not clear them

**Independent Test**: `python manage.py test temba.utils.whatsapp.tests`

### Tests for User Story 1

- [x] T006 [P] [US1] Add named ingest fixture and assertions in `temba/utils/whatsapp/tests.py`

### Implementation for User Story 1

- [x] T007 [US1] Read `parameter_format` and derive names in `temba/utils/whatsapp/tasks.py`; skip header/footer placeholders with `has_placeholders`
- [x] T008 [US1] Preserve format/names when `get_or_create` arguments are `None` in `temba/templates/models.py`
- [x] T009 [P] [US1] Publish format and names on public `TemplateReadSerializer` in `temba/api/v2/serializers.py`
- [x] T010 [P] [US1] Publish format and names on internal details in `temba/api/v2/templates/serializers.py`

**Checkpoint**: A named Meta payload is stored and readable; a positional payload is unchanged

---

## Phase 4: User Story 2 - Dispatch a campaign with per-recipient named data (Priority: P1)

**Goal**: Named write contract, Cloud-only check, translation agreement, recipient uniqueness, name-keyed queued metadata

**Independent Test**: Serializer + use-case tests for format match, `WAC`/`WCD` only, ignored extra names, duplicate URN

### Tests for User Story 2

- [x] T011 [P] [US2] Add contract/resolution tests in `temba/msgs/usecases/tests/test_named_template_broadcast.py`

### Implementation for User Story 2

- [x] T012 [US2] Implement `assert_named_template_ready` and `declared_parameter_names` in `temba/msgs/usecases/named_template_broadcast.py`
- [x] T013 [US2] Accept `recipients` and `named_variables`, reject format mismatch and mixed shapes in `temba/api/v2/serializers.py`
- [x] T014 [US2] Queue `parameter_format`, `named_variables`, and `recipient_variables` on named path only in `temba/api/v2/serializers.py`

**Checkpoint**: Named Cloud broadcasts queue name-keyed values; positional requests never grow those fields

---

## Phase 5: User Story 3 - Incomplete data follows the declared policy (Priority: P2)

**Goal**: Required hold-back, optional default/filler, contact-field fallback, all-held-back rejection, report without values

**Independent Test**: `python manage.py test temba.msgs.usecases.tests.test_named_template_broadcast`

### Implementation for User Story 3

- [x] T015 [US3] Implement `resolve_named_recipients` policy chain in `temba/msgs/usecases/named_template_broadcast.py`
- [x] T016 [US3] Stamp `metadata.named_parameters` accepted/rejected counts without echoing values in `temba/api/v2/serializers.py`
- [x] T017 [US3] Cover hold-back, all-held-back, default, and filler in `temba/msgs/usecases/tests/test_named_template_broadcast.py`

**Checkpoint**: Incomplete rows hold back the recipient; a fully held-back batch creates no broadcast

---

## Phase 6: User Story 4 - Positional broadcasts stay identical (Priority: P3)

**Goal**: Existing positional fixtures and metadata shape unchanged

**Independent Test**: Existing WhatsApp broadcast API tests remain green

- [x] T018 [US4] Keep positional `variables` path free of named metadata in `temba/api/v2/serializers.py`

**Checkpoint**: Positional suite does not observe `named_variables` or `parameter_format` on the queued blob

---

## Phase 7: Polish

- [x] T019 Record the change in `WENI-CHANGELOG.md` (3.96.0)
- [x] T020 Run targeted Django tests listed in `specs/008-named-template-variables/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (P1)**: Depends on Foundational
- **User Story 2 (P1)**: Depends on Foundational + US1 (needs recorded names)
- **User Story 3 (P2)**: Depends on US2 (resolution runs after contract validation)
- **User Story 4 (P3)**: Can be verified in parallel with US2 once the serializer branches
- **Polish**: Depends on US1–US4

### User Story Dependencies

- **User Story 1 (P1)**: Registry MVP — no dependency on broadcast
- **User Story 2 (P1)**: Needs US1 so format/names exist
- **User Story 3 (P2)**: Needs US2 write path
- **User Story 4 (P3)**: Regression gate on the positional branch of the same serializer

### Parallel Opportunities

- T006, T009, T010 can run in parallel after T005
- T011 can start once T003 exists
- T018 is a constraint on T013/T014, not a separate feature

---

## Parallel Example: User Story 1

```bash
Task: "Add named ingest fixture and assertions in temba/utils/whatsapp/tests.py"
Task: "Publish format and names on public TemplateReadSerializer in temba/api/v2/serializers.py"
Task: "Publish format and names on internal details in temba/api/v2/templates/serializers.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1–2
2. Complete Phase 3 (registry + read)
3. STOP and validate ingest tests

### Incremental Delivery

1. US1 → named templates are visible and not recorded as zero variables
2. US2 → complete campaigns with full data can dispatch by name
3. US3 → incomplete rows hold back instead of failing the batch
4. US4 → positional traffic stays identical

## Notes

- Authoring, Graph API version, and one-time reconciliation stay in `weni-integrations-engine`
- Named substitution and Meta payload emission stay in goflow / mailroom / courier
