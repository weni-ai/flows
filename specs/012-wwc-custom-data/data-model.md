# Data Model: custom_data on WhatsApp broadcasts (Flows slice)

No new tables or migrations. This feature constrains an optional key on an existing JSON blob.

## Broadcast (`msgs_broadcast`)

Existing model `temba.msgs.models.Broadcast`.

| Attribute | When `broadcast_type == W` (WhatsApp) | Rules for this feature |
| --- | --- | --- |
| `metadata` | Copy of request `msg` at create time | Optional key `custom_data` |
| `channel_id` | Optional FK | **Not** used to accept/reject `custom_data` (AD-003) |

### `metadata` / `msg` shape (additive)

```json
{
  "text": "Seu pedido foi confirmado!",
  "custom_data": {
    "order_id": "1234567890-01",
    "coupon": { "code": "BLACKFRIDAY10" },
    "tags": ["vip", "recovery"]
  }
}
```

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `custom_data` | object | No | If omitted or normalized from `{}`, key MUST NOT represent a present empty object. If present, MUST pass AD-002 validation and persist verbatim (no expression evaluation). |

Other `msg` keys (`text`, `attachments`, `template`, `queue` stored then popped for task, etc.) are unchanged.

## Mailroom task payload (read-only contract)

After `Broadcast.create`, `queue_broadcast` (type `W`) builds:

```json
{
  "broadcast_id": 123456,
  "org_id": 77,
  "channel_id": 42,
  "queue": "wpp_broadcast_batch",
  "urns": ["..."],
  "contact_ids": [],
  "group_ids": [],
  "msg": { "...": "same as metadata after queue key popped from metadata copy" }
}
```

When `custom_data` was stored on metadata, it appears as `task.msg.custom_data` with no Flows code change.

Canonical event schema: `vtex-cx-experience-specs` @ `006-wwc-custom-data/arch-v1` → `contracts/events/send-whatsapp-broadcast-task.schema.json`.

## Validation state (ephemeral)

No persisted validation state. Failed requests never create a `Broadcast` row.

## Relationships

- **Broadcast → Mailroom**: one async batch task per send; `msg` is metadata minus internal `queue` key handling in `queue.py`.
- **Downstream** (out of scope): Mailroom `msgs_msg.metadata`, Courier WWC, socket history — see architecture Impact Map.
