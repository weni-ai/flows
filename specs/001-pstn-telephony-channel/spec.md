# Engineering Spec: PSTN Telephony Channel (Flows)

**Feature Branch**: `feat/telephony-channel`  
**Created**: 2026-07-21  
**Status**: Draft

## Inheritance from Product Spec

- **Product Spec**: Voice Mode for Telephony — `vtex-cx-engine-specs/specs/004-voice-mode-telephony/spec.md`
- **Pinned version**: `004-voice-mode-telephony` (branch)
- **Inherited binding decisions**: BD-010 (TPH channel type, `tel:` URN, DID as channel address)
- **Scope of this spec**: Flows channel type `TPH` — claim UI, `tel` scheme, DID as address. Agent replies are not delivered via channel `base_url`.
- **Divergences**: none
- **Courier dependency**: `courier` handler `TPH` on branch `feat/telephony-channel`

## User Scenarios & Testing

### User Story 1 - Claim a PSTN telephony channel (Priority: P1)

An org admin configures a telephony channel with a DID so inbound voice calls resolve to the correct project.

**Acceptance Scenarios**:

1. **Given** an admin on the claim page, **When** they submit name, country, and DID, **Then** a `TPH` channel is created with `tel` scheme and DID as address
2. **Given** the claim form is shown, **When** inspecting fields, **Then** there is no voice gateway base URL or auth token
3. **Given** the channel is created, **When** viewing configuration, **Then** the Courier receive URL `courier.tph` is shown

## Requirements

- **FR-001**: Register `TelephonyPSTNType` with code `TPH` and `tel` scheme
- **FR-002**: Store DID as channel `address` for Courier DID lookup
- **FR-003**: Do not require `base_url` or `auth_token` on claim; agent audio is delivered by Nexus gRPC, not Courier REST
- **FR-004**: Expose `courier_url` pattern `^tph/receive` (no UUID — address-based routing)
- **FR-005**: Validate phone number as E.164 on claim

## Success Criteria

- **SC-001**: Claim test creates channel with correct type, address, schemes, and config
- **SC-002**: Configuration page shows inbound Courier URL for gateway setup

## Assumptions

- Channel provisioning UI via standard RapidPro claim flow is sufficient for v1
- No IVR/TWIML protocol on this channel (voice handled by external gateway)
