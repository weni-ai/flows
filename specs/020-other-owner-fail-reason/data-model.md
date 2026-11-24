# Data model: Other-owner failure reason

No new table and no new column. One existing field gains an allowed code.

## Msg.failed_reason

| | |
|--|--|
| Table | `msgs_msg` |
| Column | `failed_reason` |
| Type | `varchar(1)`, nullable |
| Writer of `H` | Courier, outside this repository |
| Reader | Contact history, failed-message list, message log, Resend |

### Codes

| Code | Constant | Label | This change |
|------|----------|-------|-------------|
| `S` | `FAILED_SUSPENDED` | Suspended | unchanged, not translated |
| `L` | `FAILED_LOOPING` | Looping | unchanged, not translated |
| `E` | `FAILED_ERROR_LIMIT` | Error Limit | unchanged, not translated |
| `O` | `FAILED_TOO_OLD` | Too Old | unchanged, not translated |
| `D` | `FAILED_NO_DESTINATION` | No Destination | unchanged, not translated |
| `H` | `FAILED_OTHER_OWNER` | Another service has the conversation | added, translated |

Empty (`NULL`) stays valid. It is not reason `H`.

Status `H` (`STATUS_HANDLED`) is a different column. A handled message does not gain a failure reason.

### Validation

- Model choices include `H` so a future `full_clean` accepts Courier’s value.
- No database check lists the letters.
- `max_length` stays 1. `null` stays true.

### Who already writes the column here

- `Msg.fail_old_messages` sets `F` + `O` on queued, pending, or errored messages older than a week. It does not select status `F`.
- `fail_channel_outgoing_messages` sets status `F` on queued, pending, or errored messages and leaves `failed_reason` as it was.

An existing `F` + `H` row stays `F` + `H` through both.

## Resend eligibility

Resend does not change status or reason.

| Stored reason | Included in `msg/resend` |
|---------------|--------------------------|
| `NULL` | yes |
| `S`, `L`, `E`, `O`, `D` | yes |
| `H` | no |

If the filter leaves no ids, Mailroom is not called.

## History event

Outbound events built by `Event.from_msg` (`msg_created`, `broadcast_created`, `product_sent`, `ivr_created`) gain one optional key when the reason is `H`:

- `failed_reason_display`: the translated choice label

Other keys (`status`, `msg`, `logs_url`, and the rest) stay as they are. Inbound `msg_received` does not gain the key.
