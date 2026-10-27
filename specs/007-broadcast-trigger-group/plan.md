# Implementation Plan: Managed trigger group for WhatsApp broadcast

**Branch**: `007-broadcast-trigger-group` | **Date**: 2026-08-31 | **Spec**: [spec.md](./spec.md)

## Summary

Enable `trigger_flow_uuid` on WhatsApp broadcasts with `urns`/`contacts` by owning a platform-managed static group per flow, exclusive membership across those groups, and a single Catch All per group — all before dispatch. Shared write serializer so public, internal Django, and FastAPI stay identical.

## Technical Context

**Language/Version**: Python 3.9+ / Django 3.2 (Temba/Flows)

**Primary Dependencies**: Django, DRF, FastAPI (internal route), mailroom client (`contact_create`, `contact_modify`)

**Storage**: PostgreSQL — new `msgs_managedtriggergroup` table

**Testing**: Django `TembaTest` (`python manage.py test`)

**Target Platform**: Flows API (public v2, internals, FastAPI)

**Project Type**: web-service

**Performance Goals**: P95 ≤ 10s at 100 URNs, ≤ 30s at 1000 URNs; membership in one mailroom round-trip

**Constraints**: No new request fields; no mailroom/trigger-model changes; group limit 250 default

**Scale/Scope**: One Flows service; three write entry points; max 1000 URNs per request

## Constitution Check

- I. Channel conventions: N/A (no new channel type). Model change includes a Django migration.
- II. Contract: write serializer remains the single contract; validations preserved except the queue restriction.
- III. Secrets: no new secrets. Logs include org/flow/group ids, not credentials.
- IV. Test-first: failing tests for the removed restriction and URN path, then implementation.
- V. Observability: log group create vs reuse, catch-all create vs restore, membership moves.
- VI. Fidelity: follows product spec BD-001–BD-015.
- VII. Migrations: `0174_managedtriggergroup` in `msgs`.

## Project Structure

```text
specs/007-broadcast-trigger-group/
temba/msgs/models.py                          # ManagedTriggerGroup
temba/msgs/migrations/0174_managedtriggergroup.py
temba/msgs/usecases/managed_trigger_group.py
temba/msgs/usecases/tests/test_managed_trigger_group.py
temba/api/v2/serializers.py                   # validate + save
temba/api/v2/internals/broadcasts/tests.py
temba/api/v2/tests.py                          # public endpoint coverage
temba/settings_common.py                      # URN resolve concurrency
```

## Implementation approach

1. Add `ManagedTriggerGroup` and migration.
2. Use-case layer: resolve/create group + Catch All, concurrent URN resolve (sequential inside atomic blocks), exclusive membership.
3. Serializer: drop queue restriction; before `Broadcast.create`, run the use-case when `trigger_flow` is set with `urns` or `contacts`; stamp `metadata.trigger_group`; keep today's Catch All for caller `groups`.
4. Setting `WHATSAPP_BROADCAST_URN_RESOLVE_CONCURRENCY` (default 20).
5. Tests for journeys 1–3, quota, reuse, recreate, exclusive membership, unchanged path without `trigger_flow_uuid`.
