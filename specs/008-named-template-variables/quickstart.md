# Quickstart: Named WhatsApp template variables

## Prerequisites

- Flows running against a workspace with a WhatsApp Cloud channel (`WAC` or `WCD`)
- A named template already mirrored locally (`parameter_format=named`, `parameter_names` populated)
- Mailroom ≥ 1.97.0 and Courier ≥ 1.67.0 deployed if you want an actual Meta send; Flows tests cover the write/registry slice without them

## 1. Confirm the registry recorded the template

```bash
python manage.py test temba.utils.whatsapp.tests
```

Expected: ingest fixture with `parameter_format: "named"` stores names; positional fixtures stay positional; header/footer placeholders still skip the template.

## 2. Confirm resolution and policy

```bash
python manage.py test temba.msgs.usecases.tests.test_named_template_broadcast
```

Expected: required hold-back, all-held-back rejection, optional default/filler, duplicate URN error, translation disagreement, Cloud-only check.

## 3. Confirm the write contract (positional unchanged + named additive)

```bash
python manage.py test temba.api.v2.tests temba.api.v2.internals.broadcasts.tests
```

Expected: existing positional broadcast tests still pass without named metadata. A named request with `named_variables` / `recipients` is accepted only for a named Cloud template.

## Manual smoke (optional)

POST the named payload in [contracts/whatsapp-broadcast-named.md](./contracts/whatsapp-broadcast-named.md) to the internal WhatsApp broadcast endpoint.

- Format mismatch → `400`, no broadcast row
- Complete named data → `201`, queued `msg.template.recipient_variables` keyed by URN identity
- Partial missing required → `201` with `metadata.named_parameters.rejected` listing parameter names only
