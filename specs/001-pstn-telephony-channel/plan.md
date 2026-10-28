# Implementation Plan: PSTN Telephony Channel (Flows)

**Branch**: `feat/telephony-channel` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)

## Summary

Add `temba/channels/types/telephony/` with channel type `TPH`, matching Courier's PSTN handler. DID is the channel address; config holds gateway `base_url` and optional `auth_token`.

## Technical Context

**Language**: Python / Django (RapidPro/Temba)  
**Pattern**: `whatsapp_cloud` (address-less courier URL) + `thinq` (tel scheme, phone claim) + `weniwebchat` (base_url config)

## Project Structure

```text
temba/channels/types/telephony/
├── __init__.py
├── type.py
├── views.py
└── tests.py
```

Register in `temba/settings_common.py` → `CHANNEL_TYPES`.

## Constitution Check

All principles PASS — follows existing channel type conventions, includes TembaTest claim coverage, aligns with Product Spec BD-010 and Courier `TPH`.
