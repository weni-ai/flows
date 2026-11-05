# Contract: WhatsApp broadcast `msg.custom_data` (Flows producer)

Shared by public v2, internal Django, and FastAPI through `WhatsappBroadcastWriteSerializer`.

**Canonical OpenAPI delta**: [vtex-cx-experience-specs](https://github.com/weni-ai/vtex-cx-experience-specs/blob/006-wwc-custom-data/arch-v1/specs/006-wwc-custom-data/contracts/openapi.flows.yaml) @ tag `006-wwc-custom-data/arch-v1`.

**Shared value schema**: same pin → `contracts/custom-data.schema.json` (`x-max-serialized-bytes`: 16384, `x-max-depth`: 32).

## Write — additive

| Field | Type | Required | Limits |
| --- | --- | --- | --- |
| `msg.custom_data` | object | No | AD-002; `{}` treated as absent |

Example (from OpenAPI):

```json
{
  "urns": ["ext:4f7a0c1e-0b9e-4d33-8a5b-9b6a2f1d8c11"],
  "channel": "0b2d9e7e-1c39-4a4f-a5f1-3a3f6f2f9d10",
  "msg": {
    "text": "Seu pedido foi confirmado!",
    "custom_data": {
      "order_id": "1234567890-01",
      "coupon": {
        "code": "BLACKFRIDAY10",
        "expires_at": "2026-11-30T23:59:59Z"
      },
      "tags": ["vip", "recovery"]
    }
  }
}
```

- Omitting `custom_data`: behavior unchanged (MINOR compatible).
- `channel` may be omitted; any channel type is allowed (AD-003).
- Internal POST: `project` / JWT tenant unchanged; `Idempotency-Key` hashes full body including `custom_data`.

## Read — broadcast response

`metadata` on create/read responses is the stored `msg`; when sent, includes `custom_data` as submitted (OpenAPI `WhatsappBroadcastRead` example).

## Validation errors (HTTP 400)

Reported under **`msg`** as a string list (DRF). Exact texts:

| Condition | Response body |
| --- | --- |
| `null` or non-object | `{"msg": ["custom_data must be an object"]}` |
| Compact UTF-8 serialization > 16384 bytes | `{"msg": ["custom_data must be at most 16384 bytes when serialized"]}` |
| Nesting depth > 32 | `{"msg": ["custom_data must have at most 32 levels of nesting"]}` |
| Key starts with `$` or contains `.` | `{"msg": ["custom_data keys must not start with '$' or contain '.'"]}` |

Compact serialization: `json.dumps(value, separators=(',', ':'), ensure_ascii=False)` encoded as UTF-8 byte length.

## Mailroom task (consumer, unchanged Flows code)

When valid and non-empty, `send_whatsapp_broadcast` task includes `msg.custom_data`. Schema: pinned `send-whatsapp-broadcast-task.schema.json`.

**Release coordination**: document required Mailroom/Courier versions in `WENI-CHANGELOG.md` at ship time per architecture Delivery Sequence (Flows deploy step 3).
