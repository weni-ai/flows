# Engineering Spec: Persist ElevenLabs voice config on TPH claim

**Feature Branch**: `feat/012-tph-voice-config`

**Created**: 2026-11-03

**Status**: Draft

**Cycle**: SDD Lite

**Input**: User description: "On TPH channel create, persist the same voice_mode.elevenLabs.{apiKey,voiceId} blob WWC preview uses, plus tests. Specify then implement on one feat branch."

## Inheritance from Product Spec

- Product Spec: Voice Mode for Telephony — https://github.com/weni-ai/vtex-cx-engine-specs/blob/b977cb60859d2238eb57f0b6ea3ad173aff4a6f4/specs/004-voice-mode-telephony/spec.md
- Pinned version: `b977cb60859d2238eb57f0b6ea3ad173aff4a6f4`
- Architecture doc: none
- Inherited binding decisions: BD-003 (ElevenLabs is the STT/TTS provider), BD-010 (PSTN is channel type TPH; DID is the channel address)
- Scope of this spec: Flows TPH claim — copy host-environment ElevenLabs credentials onto the new channel so the existing internals lookup can serve the gateway the same way it already does for Weni Web Chat preview
- Divergences: none

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A newly claimed telephony channel can speak with the platform voice (Priority: P1)

An org admin claims a PSTN telephony channel with name, country, and DID. They do not enter speech-vendor credentials. After the channel is created, the platform already has the ElevenLabs API key and voice ID that the voice gateway needs to synthesize the agent's replies on that channel.

**Why this priority**: Without these values on the channel, the existing internals lookup used by the gateway cannot return an API key, so a newly claimed TPH channel cannot speak even though the rest of telephony already works.

**Independent Test**: Claim a TPH channel as an admin and assert the stored voice configuration matches the host environment, then confirm the existing internals ElevenLabs key lookup returns that key for the new channel UUID.

**Acceptance Scenarios**:

1. **Given** an admin on the TPH claim page and host environment credentials for ElevenLabs, **When** they submit a valid name, country, and DID, **Then** the created TPH channel stores voice mode enabled with the ElevenLabs API key and voice ID from the host environment
2. **Given** a TPH channel just created by claim, **When** the existing internals ElevenLabs API key lookup is called with that channel UUID, **Then** it returns the stored API key
3. **Given** the TPH claim form, **When** inspecting fields, **Then** there is still no field for ElevenLabs credentials, voice gateway base URL, or auth token

---

### Edge Cases

- Host environment credentials are empty strings: the channel is still created and the same voice-mode blob is stored (empty values), matching Weni Web Chat preview. Claim does not fail.
- A TPH channel that already exists without voice mode is left unchanged. This change does not backfill.
- Invalid DID: claim is rejected and no channel is created, same as today.
- `base_url` and `auth_token` remain absent on the new channel.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: On a successful TPH claim, the new channel MUST persist voice mode enabled with ElevenLabs `apiKey` and `voiceId` taken from the host environment, in the same shape already used by Weni Web Chat preview
- **FR-002**: The TPH claim form MUST NOT ask the admin for ElevenLabs credentials
- **FR-003**: TPH channels created before this change MUST NOT be rewritten
- **FR-004**: DID validation, `tel` scheme, and DID-as-address behavior MUST stay as they are today
- **FR-005**: After a successful TPH claim, the existing internals ElevenLabs API key lookup MUST return the stored API key for that channel UUID

### Key Entities

- **TPH channel**: A PSTN telephony channel whose address is the DID. After this change, a newly claimed instance also carries the platform ElevenLabs voice configuration used at runtime by the gateway
- **Voice configuration**: The enabled flag plus ElevenLabs API key and voice ID, sourced from the host environment at claim time

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of newly claimed TPH channels store voice mode with the host environment's ElevenLabs API key and voice ID
- **SC-002**: For every such new channel, the existing internals ElevenLabs API key lookup returns that channel's stored API key
- **SC-003**: Admins still complete TPH claim with the same three fields as today (name, country, DID); no extra credential step is added

## Peak Load

TPH claim is an infrequent admin action on the existing channel-claim path. This change adds no new public endpoint and no extra traffic. Declared peak is the current channel-claim load: a handful of concurrent admin POSTs, not a runtime call-volume concern.

## Test Strategy

All tests use `TembaTest` in `temba/channels/types/telephony/tests.py`, following the existing TPH claim tests. They run in the `channels` CI group with `poetry run coverage run manage.py test`.

| Acceptance criterion | Test (flow from claim to stored effect) |
|---|---|
| AC-1 / FR-001 / SC-001 | Existing successful claim posts a valid DID; after redirect, the created channel's config contains `voice_mode.enabled` true and `elevenLabs.apiKey` / `voiceId` equal to the overridden host settings |
| AC-2 / FR-005 / SC-002 | After that claim, `GetElevenLabsApiKeyUseCase.execute(channel.uuid)` returns the stored API key |
| AC-3 / FR-002 / SC-003 | Claim GET/POST still uses only name, country, and phone number; no `base_url` or `auth_token` on the channel |
| FR-003 | No migration or update of existing TPH rows; covered by not adding a data migration and by leaving pre-existing channels out of the claim tests |
| FR-004 | Existing invalid-DID and national-format normalization tests stay green without behavior change |
| Empty host credentials | Claim with empty `WENI_VOICE_TOKEN` and `WENI_ELEVENLABS_VOICE_ID` still creates the channel and stores the blob with empty strings |

Failure paths covered: invalid DID still rejects before create (existing tests). Empty credentials do not block claim.

## Constitution Alignment

- **I. Version Control and Review**: Delivered through a pull request from `feat/012-tph-voice-config`, gated by `.github/workflows/ci.yml` and review.
- **II. Security and Secrets**: No secret is committed. Credentials continue to come from `WENI_VOICE_TOKEN` and `WENI_ELEVENLABS_VOICE_ID` and are stored on Temba channel config, which is the constitutionally required place for channel credentials. They are not logged.
- **III. Observability**: No new logging. Claim errors stay on the existing form path.
- **IV. Versioned Contracts**: Additive channel-config field on new TPH channels only. The internals ElevenLabs key lookup contract is unchanged. Released as MINOR `3.107.0`. No migration. No Courier or Mailroom version dependency.
- **V. Specification Traceability**: Derived from product spec `004-voice-mode-telephony` at pin `b977cb60859d2238eb57f0b6ea3ad173aff4a6f4`. This spec does not redefine problem, scope, or binding decisions; it implements the Flows slice that lets a TPH channel carry the host-environment ElevenLabs credentials the gateway already consumes.
- **VI. No Silent Divergence**: None. Credentials still come from the host environment (product NFR-004). Persisting the env-sourced blob on channel config is the existing Flows HOW used by Weni Web Chat preview so the gateway can fetch the key at runtime; it does not contradict BD-003 or BD-010.
- **VII. Commit Messages**: Conventional Commits, atomic (spec, then implementation + tests + changelog).
- **VIII. Changelog Maintenance**: `WENI-CHANGELOG.md` entry under a new `3.107.0` heading: `feat:` bullet that newly claimed TPH channels persist the platform ElevenLabs voice configuration.
- **IX. Never Trust the Client**: Admins still cannot supply ElevenLabs credentials on the form; values are taken from the server environment after DID validation at the form boundary.
- **X. Fail Gracefully and Predictably**: Empty environment values do not crash claim; they persist as empty strings, same as Weni Web Chat preview. Invalid DID still returns a form error.
- **XI. Bounded Retry Over REST**: Not applicable; no new outbound REST call.
- **XII. Scalability and Peak Load**: Stateless claim view; no new process state; peak declared above.
- **XIII. Diagnosable Errors**: No new Sentry surface; claim failures remain form validation errors.
- **XIV. Tests Exercise Flows**: Claim POST through to stored config and internals key lookup, plus empty-credential and existing invalid-DID paths.
- **XV. Explicit Over Clever**: Voice-mode blob is built by a named helper; no new unexplained literals.
- **XVI. Contained Changes**: Only TPH claim config, its tests, changelog, and this spec. Weni Web Chat preview is not refactored. Existing TPH channels are not backfilled. Gateway and Courier are unchanged.
- **Cycle choice**: SDD Lite. The change does not add a channel type, does not change a public contract, does not ship a migration, and does not need Courier or Mailroom coordination. It touches one claim path under `temba/channels/types/telephony/`. The requester chose specify then implement.

## Implementation Notes

These notes replace `plan.md` in the Lite cycle.

- **Claim**: `ClaimView.form_valid` in `temba/channels/types/telephony/views.py` currently passes `config={}`. Change it to pass `config={"voice_mode": build_default_voice_mode_config()}`.
- **Helper**: `build_default_voice_mode_config()` lives in the same module as `ClaimView` (cannot live on `type.py` without a circular import: `type.py` already imports `ClaimView`). It returns `{"enabled": True, "elevenLabs": {"apiKey": settings.WENI_VOICE_TOKEN, "voiceId": settings.WENI_ELEVENLABS_VOICE_ID}}`, matching `_build_default_wwc_config(preview=True)` in `temba/projects/usecases/channel_creation.py`. Do not refactor that WWC helper in this change.
- **Tests**: Extend `temba/channels/types/telephony/tests.py` with `override_settings` for the two env-backed settings. Assert the stored blob, assert `GetElevenLabsApiKeyUseCase` returns the key, and add a case with empty settings. Keep existing DID tests untouched in behavior.
- **Changelog**: `feat:` bullet under a new `3.107.0` heading in `WENI-CHANGELOG.md`. A feature ships as its own version bump, not under an already-released heading.
- **Out of scope**: backfill of existing TPH channels; new Flows environment variables; gateway `voiceId` reader; Courier/Mailroom.

## Assumptions

- The gateway already reads the ElevenLabs API key through Flows internals `GetElevenLabsApiKeyUseCase`, which walks `config.voice_mode.elevenLabs.apiKey` on any channel type. Aligning TPH claim with the WWC preview blob is sufficient for the key. A gateway change to read `voiceId` from the same blob is out of scope here.
- Host environment variables `WENI_VOICE_TOKEN` and `WENI_ELEVENLABS_VOICE_ID` are already defined in `temba/settings_common.py` and already set in Rancher for Weni Web Chat preview. No new Flows env var is required.
- Existing TPH channels that were patched manually keep their current config; those created with empty config stay empty until recreated or updated by a later change.
- SDD Lite is the chosen cycle; `plan.md` and `tasks.md` are not produced.
