# Contract: Project events consumed by Flows

**Feature**: [../spec.md](../spec.md) | **Data model**: [../data-model.md](../data-model.md)

This document covers what Flows accepts on its two project event queues, what it does with each message, and what operators see. The publisher side is `weni-engine/specs/005-project-events-amazonmq` (Connect) and Nexus for `project.type.updated`.

## 1. AmazonMQ: `projects.topic` → `flows.projects.queue`

Consumer: `ProjectConsumer` (`temba/projects/consumers/project_consumer.py`), process `edaconsume-amq`.

### Bindings required (infrastructure)

| Routing key | Status |
|-------------|--------|
| `project.created` | Existing |
| `project.updated` | New |
| `project.status.updated` | New |
| `project.type.updated` | New |
| `project.deleted` | New |

The queue needs a dead-letter exchange before `PROJECT_EVENTS_LEGACY_ACTIONS` drops any action, because rejected messages are not requeued.

### Envelope

```json
{
  "event_id": "8a0f1f0e-3c1e-4d0b-9a59-2f6a7c0f5d11",
  "event_type": "project.status.updated",
  "producer": "connect",
  "timestamp": "2026-11-17T21:40:00Z",
  "data": { "...": "per event type" }
}
```

Exactly these five keys. Any other shape is rejected. For every `event_type`, including `project.created`:

| Field | Accepted values |
|-------|-----------------|
| `event_id` | String of 1 to 64 characters from `A-Z a-z 0-9 . _ : -` (a UUID fits) |
| `event_type` | Same rule |
| `producer` | Same rule, or `null` (`weni-engine` fits) |
| `timestamp` | Not checked |

An envelope that breaks these rules is rejected before anything from it is logged.

### `data` per event type

| `event_type` | Field | Required | Accepted values |
|--------------|-------|----------|-----------------|
| all four | `uuid` | yes | String parseable as a UUID; equals `Org.proj_uuid` |
| all four | `user_email` | yes | Non-empty string |
| `project.updated` | `name` | no | String or `null` |
| `project.updated` | `description` | no | String or `null` |
| `project.updated` | `language` | no | String or `null` |
| `project.updated` | `timezone` | no | Time zone name `pytz` accepts, or `null` |
| `project.status.updated` | `status` | yes | `ACTIVE`, `IN_TEST`, `INACTIVE` |
| `project.type.updated` | `is_multi_agents` | yes | JSON `true` or `false` only |

Other keys in `data` are ignored. They include `date_format`, `config`, `vtex_account` and `currency` from Connect's `project.updated`.

Examples:

```json
{ "uuid": "5b1e…", "user_email": "admin@example.com", "name": "Loja", "description": null, "language": "pt-br", "timezone": "America/Sao_Paulo" }
{ "uuid": "5b1e…", "user_email": "admin@example.com", "status": "INACTIVE" }
{ "uuid": "5b1e…", "user_email": "admin@example.com", "is_multi_agents": true }
{ "uuid": "5b1e…", "user_email": "admin@example.com" }
```

### Effect and acknowledgement

| Situation | Broker outcome | Org effect |
|-----------|----------------|------------|
| Valid, action not in the legacy list, org exists | ack | Applied (see data model, "Org fields written") |
| Valid, action in the legacy list | ack | None |
| Valid, no org for `uuid` | ack | None |
| Valid `project.deleted`, org already released | ack | None (`released_on` unchanged) |
| Invalid envelope or `data` | reject, `requeue=False` | None |
| Use case raises | reject, `requeue=False` | None: update, status and type write in one `save`, and deletion runs inside a transaction |
| `project.created` with a valid envelope | unchanged | unchanged |
| Any other `event_type` | ack | None |

Delivery is at least once. A repeat is harmless: status and type only write on change, a repeated update writes the same values, and a repeated deletion is a no-op.

## 2. RabbitMQ (legacy, deprecated): `flows.project-events`

Consumer: `ProjectEventConsumer`, process `edaconsume`. The body shape is unchanged:

```json
{ "project_uuid": "5b1e…", "action": "status_updated", "user_email": "admin@example.com", "status": "INACTIVE" }
```

Change: a message whose `action` is not in `PROJECT_EVENTS_LEGACY_ACTIONS` is acknowledged without effect. With the default value nothing changes. `project_uuid` is still not validated as a UUID; logs, Sentry tags and the rejection message carry it only in canonical form when it is one, and omit it otherwise. The queue is announced as deprecated in `WENI-CHANGELOG.md` and is removed after SC-005 holds.

## 3. Setting `PROJECT_EVENTS_LEGACY_ACTIONS`

| Property | Value |
|----------|-------|
| Format | Comma-separated; whitespace around items ignored; empty items dropped |
| Allowed items | `updated`, `status_updated`, `project_type_update`, `deleted` |
| Default (unset) | All four, so the legacy consumer applies everything (today's behaviour) |
| Empty string | `[]`, so `ProjectConsumer` applies everything |
| Unknown item | System check `projects.E001`, and `edaconsume`, `edaconsume-amq`, `migrate` and `check` refuse to run |
| Change takes effect | After restarting both `edaconsume` and `edaconsume-amq`, which must get the same value |

Rollout values: default, then `project_type_update`, then `""` (spec, Rollout and Rollback).

## 4. Logs

Logger `temba.projects` at `INFO`. Each line is an event name followed by `key=value` pairs, readable with Loki's `logfmt` parser.

| Line | Level | Fields |
|------|-------|--------|
| `project_event_consumed` | info | AmazonMQ: `event_id`, `event_type`, `project_uuid`, `producer`. Legacy: `action`, `project_uuid`. |
| `project_event_skipped` | info | `event_id` (AmazonMQ), `event_type` or `action`, `project_uuid`, `reason` (`legacy_consumer_applies` or `amazonmq_consumer_applies`) |
| `project_event_org_not_found` | warning | `event_id`, `event_type`, `project_uuid` |
| `project_already_released` | info | `project_uuid`, `org_id` |
| `[ProjectConsumer] Message rejected: project event rejected: …` | error | Written by `weni-eda`: `event_id`, `event_type` or `action`, `project_uuid` when known, `reason` |

No line contains an e-mail address or a project name.

## 5. Sentry

One event per rejection from `capture_exception`, with these tags when known: `project_uuid`, `event_id`, `event_type` or `action`, `org_id`, `user_id` (the `User.id` with the event's e-mail, looked up without creating a user; absent when no such user exists or the event failed before the use case). There is no account tag: the events carry no account identifier. Stack frame local variables are removed, and e-mail-shaped substrings in exception values are replaced with `[email]`. The `weni-eda` rejection log can produce a second event. It carries only `ProjectEventRejected`, whose frames hold no payload. Neither event contains an e-mail address or a project name.

## 6. Versioning

The change is additive for publishers: new routing keys are handled on a queue that already accepted unknown types. No Courier or Mailroom release is required.
