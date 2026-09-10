# Contract: WhatsApp broadcast named parameters

Shared by public v2, internal Django, and internal FastAPI through `WhatsappBroadcastWriteSerializer`.

## Write — named

Additive. Existing fields keep their meaning.

| Field | Type | Required | Limits |
| --- | --- | --- | --- |
| `recipients` | array of object | No | Max 1000; each item needs `urn` |
| `recipients[].urn` | string | Yes if item present | Same URN parsing as `urns` |
| `recipients[].variables` | object | No | Max 100 name→value pairs; **literal** text |
| `msg.template.named_variables` | object | No | Batch-level name→value; evaluated as expressions in Mailroom |
| `msg.template.variables` | array | No | Positional list; **mutually exclusive** with `named_variables` |

```json
{
  "channel": "<channel-uuid>",
  "msg": {
    "template": {
      "uuid": "<template-uuid>",
      "locale": "pt-BR",
      "named_variables": { "data": "@fields.vencimento" }
    }
  },
  "recipients": [
    {
      "urn": "whatsapp:5511999999999",
      "variables": { "campanha": "BF4", "nome": "João", "cota": "045" }
    },
    {
      "urn": "whatsapp:5511888888888",
      "variables": { "campanha": "BF4", "nome": "Ana" }
    }
  ]
}
```

Names the template does not declare are ignored. Order of keys is irrelevant.

## Write — positional (unchanged)

```json
{
  "channel": "<channel-uuid>",
  "msg": {
    "template": {
      "uuid": "<template-uuid>",
      "variables": ["João", "045", "@fields.vencimento"]
    }
  },
  "urns": ["whatsapp:5511999999999"]
}
```

Must not include `named_variables` or require `recipients`. Response metadata must not grow named fields.

## Validation

| Condition | Result |
| --- | --- |
| Named values for a positional template | `400`, names the template and states its format |
| Positional `variables` for a named template | `400`, names the template and states its format |
| Both shapes present | `400`, names both fields |
| Named template on a non-`WAC`/`WCD` channel | `400`, names channel and template |
| Named template with no recorded names | `400`, template is not ready for named dispatch |
| Translations disagree on names | `400`, identifies the disagreeing translation |
| Repeated recipient URN | `400`, identifies the URN |
| More than 1000 recipients or 100 names on one recipient | `400`, names the field and the limit |
| Every recipient held back | `400`; no broadcast created |
| Some recipients held back | `201`; accepted URNs dispatched; report in metadata |
| Unknown name supplied | ignored |
| No `urns`/`contacts`/`groups`/`recipients` | `400`, existing audience error |

## Response metadata (named, partial hold-back)

```json
{
  "metadata": {
    "named_parameters": {
      "accepted_count": 1,
      "rejected_count": 1,
      "rejected": [
        {
          "urn": "whatsapp:5511888888888",
          "parameter": "cota",
          "reason": "required_parameter_missing"
        }
      ]
    }
  }
}
```

The report MUST NOT echo parameter values.

## Template read

Public template list/detail adds `parameter_format` on the template and `parameter_names` on each translation.

Internal translation details adds `parameter_format` and `parameters: [{ "name": "..." }]`.
