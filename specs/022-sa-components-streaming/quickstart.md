# Quickstart: validar `POST /api/v2/internals/messages/stream` com componentes

**Feature**: `022-sa-components-streaming` | **Plan**: [plan.md](plan.md)

Guia de validação. Não contém implementação. Formato dos campos: [contracts/openapi.flows.yaml](contracts/openapi.flows.yaml). Ordem e efeitos: [contracts/messages-stream.behavior.md](contracts/messages-stream.behavior.md). Regras e estados: [data-model.md](data-model.md).

## Pré-requisitos

- Python 3.11, Poetry, PostgreSQL/PostGIS e Redis locais, como no `.github/workflows/ci.yml`. Os testes usam o Redis DB 10 (`TESTING`).
- `poetry install`

## Rodar

```bash
poetry run python manage.py test temba.api.v2.internals.msgs
poetry run coverage run manage.py test temba.api.v2.internals.msgs
./code_check.py
```

Gate do PR: grupo `api` verde no CI e `./code_check.py` limpo, sem `# pragma: no cover` novo.

## Fixtures comuns

- `TembaTest` com `self.org.proj_uuid = uuid4()` (P) e `self.org2.proj_uuid = uuid4()` (P2), um contato de P com URN `ext:shopper-42@` e um canal de P.
- **JWT real** (US4 e todos os testes novos que passam pela autenticação):
  - gerar um par RSA de teste com `cryptography`;
  - aplicar `override_settings(JWT_PUBLIC_KEY=<PEM público>)`;
  - assinar `{"project_uuid": str(P)}` (ou `{"channel_uuid": ...}`) com `jwt.encode(..., algorithm="RS256")`;
  - enviar `HTTP_AUTHORIZATION="Bearer <token>"`.
- **Sem Mailroom e sem Courier**: `patch` de `temba.mailroom.queue._queue_task`, `_queue_batch_task` e `_queue_handler_task`, com `assert_not_called()`.
- **Redis**: apagar `idempotency:messages_stream:*` no `setUp` e no `tearDown`.
- **Payloads base**: os exemplos `quickReplies`, `listAndCtaMultiComponent` e `textlessComponent` do OpenAPI, com `project_uuid`, `channel_uuid` e `urns` trocados pelos da fixture.

## US1 — registrar componentes sem envio (P1)

Token de P. Cada linha é um teste.

| Cenário | Corpo (`msg`) | Esperado |
|---|---|---|
| 1.1 | `text` + `quick_replies` (3) | `201 {"ids":[id]}`; `Msg.text == msg.text`; `metadata.quick_replies` na mesma ordem |
| 1.2 | `list_message` com `item_count: 9` | `201`; `metadata.list_message.item_count == 9` |
| 1.3 | `list_message` sem `item_count` | `201`; `item_count` ausente em `metadata` |
| 1.4 | `cta_message` com `https://` completa | `201`; `metadata.cta_message` igual ao enviado |
| 1.5 | `textlessComponent` (`text: ""` + `quick_replies`) | `201`; `Msg.text == ""` |
| 1.6 | `listAndCtaMultiComponent` | `201`; os dois componentes em `metadata` |
| 1.7 | `quick_replies` + `list_message` + `cta_message` | `201`; os três em `metadata` |
| 1.8 | `header {"type":"text","text":"..."}` + `footer` | `201`; os dois em `metadata` |
| 1.9 | corpo de hoje, sem os seis campos (testes atuais de stream) | resultado idêntico ao de hoje |
| 1.10 | 2 URNs + componentes | `201` com 2 ids; `metadata` igual nas duas linhas |
| 1.11 | todos acima | nenhuma tarefa de Mailroom enfileirada |

Em todos: `Msg.metadata == msg` do corpo, comparado como dicionário.

## US2 — rejeitar componente malformado (P2)

Token de P. Em cada caso: `400`, o caminho dentro de `response.json()["msg"]` e a contagem de `Msg` inalterada.

| Cenário | Entrada | Caminho esperado |
|---|---|---|
| 2.1 | `quick_replies: []` | `msg.quick_replies` |
| 2.2 | `quick_replies: ["", 1, {}, null]` (um por teste) | `msg.quick_replies.<i>` |
| 2.3 | `list_message` sem `button_text` / `button_text: ""` | `msg.list_message.button_text` |
| 2.4 | `list_items` ausente / `[]` | `msg.list_message.list_items` |
| 2.5 | item sem `uuid` / sem `title` / vazio | `msg.list_message.list_items.<i>.<campo>` |
| 2.6 | `item_count`: `0`, `-1`, `1.5`, `"9"`, `true` | `msg.list_message.item_count` |
| 2.7 | `url`: sem esquema, `ftp://…`, `javascript:…`, `https://`, com espaço, com caractere não ASCII, `HTTPS://…` | `msg.cta_message.url` |
| 2.8 | `display_text` ausente / `""` | `msg.cta_message.display_text` |
| 2.9 | `interaction_type: "button"` | `msg.interaction_type` |
| 2.10 | `header.type: "image"` / `header: "x"` / `footer: 1` | o campo |
| 2.11 | `cta_message: null` | `msg.cta_message` |
| 2.12 | `list_message` válida + `cta_message` inválido | só `msg.cta_message`; 0 linhas |
| 2.13 | 2 URNs + componente inválido | 0 linhas |
| 2.14 | inválido com `Idempotency-Key: K`, depois corrigido com `K` | `400` e depois `201` |
| 2.15 | `list_message.foo` | `msg.list_message.foo` |
| 2.16 | `list_items[0].foo` | `msg.list_message.list_items.0.foo` |
| 2.17 | `cta_message.foo` | `msg.cta_message.foo` |
| 2.18 | `header.foo` | `msg.header.foo` |
| 2.19 | `msg.foo` + componentes válidos | **`201`**; `metadata.foo` gravado |

Casos aceitos por contrato, que precisam de `201`: `quick_replies: ["   "]` (sem trim), `item_count: 9.0`, `header.text: ""`, `footer: ""`, `list_items[].uuid` que não está em formato UUID.

## US3 — `Idempotency-Key` (P3)

Token de P. Corpo B válido.

| Cenário | Passos | Esperado |
|---|---|---|
| 3.1 | B + `K` | `201 {"ids": X}`; chave `done` com TTL ≤ 86400 e > 86400 − margem |
| 3.2 | 3.1, depois B com chaves JSON reordenadas + `K` | `200 {"ids": X}`; 0 linhas novas |
| 3.3 | 3.1, depois B' + `K` | `409` `code == "idempotency_conflict"`; 0 linhas; depois B + `K` ainda devolve `200 {"ids": X}` |
| 3.4 | B duas vezes sem header | dois `201` com ids diferentes |
| 3.5 | `K` em P; token de P2 com `project_uuid` P2 + `K` | `201` em P2; registro de P intacto |
| 3.6 | `idempotency:whatsapp_broadcasts:{P}:K` presente; B + `K` aqui | `201`; chave de broadcasts intacta |
| 3.7 | reserva `inflight` de `K` gravada direto no Redis; B + `K` | `409` `code == "idempotency_in_progress"`; 0 linhas; a reserva continua com o mesmo valor |
| 3.8 | 3.1; apagar a chave (expiração simulada); B + `K` | `201` com ids novos |
| 3.9 | `K` = `""`, `"   "`, 129 caracteres | `201` sem chave gravada; depois o mesmo corpo e header de novo: `201` com ids novos |
| 3.10 | primeira tentativa termina em `400`, `403`, `404` ou `5xx`; depois corrigida + `K` | processada normalmente (`201`) |
| 3.11 | cliente Redis com `ConnectionError` + `K` | `503 {"error": "Service temporarily unavailable"}`; 0 linhas |
| 3.12 | `store_success` falha depois das linhas criadas | `503`; 0 linhas (transação desfeita) |

Só 128 caracteres exatos (válido) e 129 (ausente) testam o limite.

## US4 — JWT de módulo e escopo de tenant (P4)

Autenticação e permissão **reais**, sem `patch` de `authentication_classes` nem de `permission_classes`.

| Cenário | Token | Corpo | Esperado |
|---|---|---|---|
| 4.1 | nenhum | válido de P | `403` com `detail`; 0 linhas; nenhuma chave no Redis |
| 4.2 | assinatura inválida / expirado / sem claim de tenant | válido de P | `403` com `detail`, **nunca** `401` |
| 4.3 | P1 | `project_uuid` P2 (existe) | `403`; 0 linhas em P1 e P2 |
| 4.4 | só `channel_uuid` de um canal de P1 | `project_uuid` P2 | `403` |
| 4.5 | P (sem `Org`) | `project_uuid` P | `404 {"error": "Project not found"}` |
| 4.6 | P | P | `201` |
| 4.7 | P | `channel_uuid` de outro projeto | `400` com o erro de canal de hoje; 0 linhas |
| 4.8 | P1 | P2 + `Idempotency-Key: K` | `403`; nenhuma chave `idempotency:messages_stream:*:K` |

Também: um teste de unidade confirma que `MsgStreamView.permission_classes` contém `ModuleJWTProjectScope` e não contém `IsAuthenticated`, `AllowAny` nem lista vazia (Principle XVII).

## Observabilidade e privacidade (SC-006)

| Cenário | Esperado |
|---|---|
| O.1 | erro forçado dentro da criação (exceção inesperada) com `cta_message.url`, `quick_replies`, `list_items` e `text` conhecidos | evento de Sentry capturado sem nenhum desses valores (`request.data`, `vars` dos frames e `data` dos breadcrumbs `query` removidos); tags `project_uuid`, `correlation_id`, `caller=module_jwt`, `account_id=none` e `user_id=none` |
| O.2 | cada desfecho da matriz | `assertLogs`: um log com `outcome` (e `reason` quando houver) e só identificadores opacos; nenhum valor de conteúdo |
| O.3 | `X-Correlation-ID` com 1 e com 128 caracteres | presente como veio, no log e na tag |
| O.4 | `X-Correlation-ID` vazio / com 129 caracteres | requisição aceita normalmente; o valor não aparece |
