# Data Model: Named WhatsApp template variables

## Template

Existing `temba.templates.models.Template`.

| Field | Type | Rules |
| --- | --- | --- |
| `parameter_format` | `CharField(max_length=16)`, default `"positional"` | Authoritative. Values: `named`, `positional`. Missing/unknown provider value → `positional`. Never inferred from body. |
| `parameter_policies` | `JSONField`, default `{}` | Optional overlay keyed by provider parameter name. |

### `parameter_policies` shape

```json
{
  "cota": {
    "required": false,
    "default": "000",
    "contact_field": "cota"
  }
}
```

- Missing key or empty object: parameter is **required**.
- `required` default `true` when omitted.
- `default` / `contact_field` optional.
- A policy key that is not a declared parameter name is a contract error at dispatch (FR-038), not at ingest.

## TemplateTranslation

Existing `temba.templates.models.TemplateTranslation`.

| Field | Type | Rules |
| --- | --- | --- |
| `parameter_names` | `JSONField`, default `[]` | Ordered list of provider names for **display**. Order MUST NOT bind values. |

`variable_count` for named templates is `len(parameter_names)`; positional templates keep today's `{{N}}` max-index count.

### Ingest (`get_or_create`)

- Create: persist format (default positional) and names (default `[]`).
- Update: write `parameter_names` only when the argument is not `None`; write `parameter_format` only when not `None`.
- Status/content updates that omit the new arguments MUST leave them intact.

### Translation agreement (dispatch time)

Collect `parameter_names` of active translations. If the sets (as tuples) differ, reject named dispatch naming the disagreeing translation language. Each translation still stores its own list.

## Broadcast metadata (not a new table)

Queued `msg` blob, name-keyed, no indexes:

```json
{
  "template": {
    "uuid": "...",
    "name": "...",
    "parameter_format": "named",
    "named_variables": { "data": "@fields.vencimento" },
    "recipient_variables": {
      "whatsapp:5511999999999": { "nome": "João", "cota": "045", "data": "@fields.vencimento" }
    },
    "variables": []
  },
  "named_parameters": {
    "accepted_count": 1,
    "rejected_count": 1,
    "rejected": [
      { "urn": "whatsapp:5511888888888", "parameter": "cota", "reason": "required_parameter_missing" }
    ]
  }
}
```

Positional broadcasts MUST omit `parameter_format`, `named_variables`, `recipient_variables`, and `named_parameters`.

## Resolution (ephemeral)

Per declared name, first provided wins:

1. `recipients[].variables[name]` (literal; empty/whitespace/null = not provided)
2. `msg.template.named_variables[name]` (presence check in Flows; expression eval in Mailroom)
3. Contact field named by policy (`contact_field`), org-scoped
4. Policy `default`
5. If required → hold back; if optional → filler `" "`

Unknown names in the request are dropped. Values are never written to `Contact`.

## Relationships

- `Template` 1—* `TemplateTranslation`
- `TemplateTranslation` *—1 `Channel` (capability check uses `channel.channel_type ∈ {WAC, WCD}`)
- Policy JSON belongs to `Template`, not to a translation
