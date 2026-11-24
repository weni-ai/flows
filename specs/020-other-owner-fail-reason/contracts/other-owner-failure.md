# Contracts: Other-owner failure reason

## 1. Stored reason (Courier → Flows)

Courier spec 008-fail-wac-not-owner writes, and this repository accepts:

| Field | Value |
|-------|--------|
| `msgs_msg.status` | `F` (failed) |
| `msgs_msg.failed_reason` | `H` |

Courier stores the letter only. This repository owns the operator sentence.

The column stays nullable. Rows with `NULL` or `S` / `L` / `E` / `O` / `D` stay valid. No check constraint is added.

Flows does not decide the send, does not read `wac:thread_owner:*`, and does not call the Thread Control API.

## 2. Contact history event (Flows page)

`ContactCRUDL.History` returns the same event dicts to the HTML template and to `as_json`.

For an outgoing message with reason `H`, the event includes the existing fields plus:

```json
{
  "status": "F",
  "failed_reason_display": "Another service has the conversation"
}
```

`failed_reason_display` is the active-language label. Under `pt-br` it is exactly `Outro atendimento está com a conversa`.

Events for any other reason omit `failed_reason_display`. Clients that ignore unknown keys keep working. The public message API (`MsgReadSerializer`) and the spreadsheet export do not gain a field or a column. Their status for this message remains `failed`.

## 3. Resend (Flows → Mailroom)

`POST` body of `msg/resend` stays:

```json
{
  "org_id": 1,
  "msg_ids": [10, 11]
}
```

Flows removes ids whose stored `failed_reason` is `H` before the call. Empty reasons and the five older codes stay in `msg_ids`. When every selected id is `H`, Flows does not call Mailroom.

Mailroom’s endpoint, payload, and retry query are unchanged. A message left out of this call stays `status=F` and `failed_reason=H`.
