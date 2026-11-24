# Implementation Plan: componentes de streaming do Shopping Assistant em `POST /api/v2/internals/messages/stream` (fatia Flows)

**Branch**: nenhuma criada (trabalho em `main`; diretório `specs/022-sa-components-streaming`) | **Date**: 2026-11-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/022-sa-components-streaming/spec.md`

**Cycle**: SDD Full. **Contratos**: pin `329a1db8c1f3f62208b052457e0e3bc9654ce102` ([contracts/README.md](contracts/README.md)). O commit `fe00c1c` está obsoleto. A tag `arch-v1` existe, mas não é usada enquanto o documento tagueado disser `Status: Draft` com a aprovação do `flows` pendente.

## Summary

`MsgStreamSerializer` passa a validar os seis campos opcionais de `msg` (`quick_replies`, `list_message`, `cta_message`, `interaction_type`, `header`, `footer`) no formato do OpenAPI 1.1.0, com `$ref` ao schema compartilhado:

- tipos JSON estritos;
- `list_message`, cada item de `list_items`, `cta_message` e `header` fechados;
- chaves no nível de `msg` abertas;
- `Msg.metadata` igual ao `msg` enviado.

`MsgStreamView` continua fina e ganha quatro coisas:

- a permissão nomeada `ModuleJWTProjectScope`, que compara o `project_uuid` do corpo com os claims do JWT antes de qualquer consulta ou gravação;
- `get_authenticate_header() → None`, para que toda falha de JWT ou de escopo seja `403`;
- idempotência por `Idempotency-Key` num módulo novo do app (prefixo Redis próprio, reserva de 120s, conclusão de 24h, `200` replay, `409` com `code`, `503` em falha do Redis);
- um filtro de Sentry e logs de desfecho só com identificadores opacos.

A gravação continua em `create_message_db_only`. Sem Mailroom, sem Courier, sem migration. Decisões em [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11 (CI), `>=3.10,<3.12`

**Primary Dependencies**:

- Django 3.2, Django REST Framework 3.15.1
- PyJWT com `cryptography` (RS256, já dependência)
- django-redis 4.12.1, redis-py 3.5.3
- sentry-sdk 1.45.1

Nenhuma dependência nova.

**Storage**:

- PostgreSQL: `msgs_msg`, sem mudança de schema.
- Redis compartilhado (`CACHES["default"]["LOCATION"]`): registros de idempotência com TTL.

**Testing**: `TembaTest`, `poetry run coverage run manage.py test` (grupo `api`) e `./code_check.py`.

**Target Platform**: serviço web Linux (gunicorn, `timeout = 120` em `docker/gunicorn/gunicorn.conf.py`), processos sem estado.

**Project Type**: web-service (Django monolito `temba`), endpoint interno de módulo.

**Performance Goals**: SC-007. Sem regressão do p95 atual para chamadas sem componentes e sem chave. O acréscimo é uma validação em memória e até 4 operações Redis só quando há chave.

**Constraints**:

- timeout explícito no Redis (2s);
- nenhum estado de aplicação em memória de processo;
- nenhum limite que o contrato não declara;
- nenhum conteúdo (`text`, `message`, `msg.text`, `header.text`, `footer`, `quick_replies`, `button_text`, `display_text`, `list_items`, `url`) em log ou Sentry.

**Scale/Scope**: um endpoint, arquivos só em `temba/api/v2/internals/msgs/` e em `WENI-CHANGELOG.md`. Peak Load abaixo.

### Peak Load (Principle XII)

- **Fórmula (spec)**: pico de `POST /api/v2/internals/messages/stream` do Shopping Assistant + pico das respostas com componentes do Shopping Assistant que hoje passam por `/api/v2/internals/whatsapp_broadcasts` em canais com streaming, no mesmo horário de pico. É um valor de pico, não de média.
- **Valor numérico**: **medição pendente**. O repositório não tem métricas de produção. O valor MUST ser medido nos dois endpoints e registrado aqui antes do passo 1 de deploy.
- **Acréscimo por requisição**: ver [data-model.md](data-model.md) §5.
- **Fora do dimensionamento**: gRPC, Redis Pub/Sub do socket, WebSocket e MongoDB.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Antes da Phase 0

| Principle | Gate | Status |
|---|---|---|
| I. Version Control | PR com review e CI verde | PASS: sem mudança de processo |
| II. Security and Secrets | sem segredo; sem dependência nova | PASS |
| III. Observability | logs estruturados sem dado pessoal; correlação | PASS: FR-033 a FR-036 |
| IV. Versioned Contracts | delta aditivo `1.1.0`; sem migration; Courier e Mailroom sem versão nova | PASS: FR-037 |
| V. Specification Traceability | herança no formato exato; Product Spec por tag e commit; Architecture doc por commit | PASS, com nota: a Product Spec vive em `vtex-cx-experience-specs`, registrado na spec |
| VI. No Silent Divergence | `Divergences: none`; resoluções do AD-004 aplicadas | PASS |
| VII. Commit Messages | Conventional Commits, até 50 caracteres | PASS: a aplicar no `/speckit-implement` |
| VIII. Changelog | bullet `feat` + bullet de segurança | PASS: FR-037 |
| IX. Never Trust the Client | validação no serializer; autorização no servidor | PASS: FR-001 a FR-011, FR-028 a FR-032 |
| X. Fail Gracefully | timeouts explícitos; erros consistentes sem detalhe interno | PASS: FR-026 |
| XI. Bounded Retry | operação idempotente por chave | PASS: FR-018 a FR-027 |
| XII. Peak Load | stateless; pico declarado | PASS: fórmula declarada, valor numérico pendente antes do deploy |
| XIII. Diagnosable Errors | ids opacos de projeto, conta, usuário e correlação | PASS: FR-035 (ausência de conta e usuário explícita) |
| XIV. Tests Exercise Flows | fluxo completo + falhas | PASS: Test Strategy da spec |
| XV. Explicit Over Clever | constantes nomeadas | PASS |
| XVI. Contained Changes | só `msgs/` + changelog | PASS |
| XVII. Explicit, Scoped Authorization | permissão nomeada; nada de `[]`, `IsAuthenticated` ou `AllowAny` | PASS: FR-031 corrige o `permission_classes = []` herdado |
| Channel layout | não se aplica | N/A |

Nenhuma violação. Phase 0 liberada.

### Depois da Phase 1

| Principle | Verificação no desenho | Status |
|---|---|---|
| II | `jsonschema`, `rfc3986` e `rfc3987` foram descartados; o URI é checado com `re` e `urllib` (R4) | PASS |
| III, XIII | `observability.py`: tags `project_uuid`, `channel_uuid`, `correlation_id`, `caller`, `account_id=none` e `user_id=none`; log com `outcome` do FR-036 + `reason` (R10, R11) | PASS |
| IV | corpos de `200`, `409`, `403` e `404` iguais aos do contrato; `503` só no caso de FR-026; `201` inalterado ([contracts/messages-stream.behavior.md](contracts/messages-stream.behavior.md)) | PASS |
| IX | a view só orquestra; regras no serializer, na permissão e no módulo de idempotência | PASS |
| X | cliente Redis com `socket_timeout`/`socket_connect_timeout` de 2s; `503` sem detalhe; `500` padrão (R7, R8) | PASS |
| XI | reserva com `SET NX`; conclusão dentro da transação; liberação só pela dona; o `409` não escreve (R7 a R9) | PASS |
| XII | estado só no Redis; o cliente reaproveitado por processo é pool de conexões, não estado de aplicação | PASS |
| XV | constantes `MAX_KEY_LENGTH=128`, `DONE_TTL_SECONDS=86400`, `INFLIGHT_TTL_SECONDS=120`, `REDIS_TIMEOUT_SECONDS=2`, `REDIS_KEY_PREFIX`, `IDEMPOTENCY_KEY_HEADER`, `CORRELATION_ID_HEADER`, `MAX_CORRELATION_ID_LENGTH=128`, `CODE_IDEMPOTENCY_CONFLICT`, `CODE_IDEMPOTENCY_IN_PROGRESS`, `CTA_URL_PATTERN`, `SERVICE_UNAVAILABLE_ERROR`; comentário de porquê em `INFLIGHT_TTL_SECONDS` e em `get_authenticate_header` | PASS |
| XVI | `broadcasts/idempotency.py` só importado (`compute_body_hash`), nunca alterado; `jwt.py`, `JWTAuthMixinRequired`, `settings_common.py` e `services.py` intactos | PASS |
| XVII | `permission_classes = [ModuleJWTProjectScope]` só nesta view | PASS |

Nenhuma violação.

## Project Structure

### Documentation (this feature)

```text
specs/022-sa-components-streaming/
├── spec.md
├── plan.md                         # este arquivo
├── research.md                     # Phase 0
├── data-model.md                   # Phase 1
├── quickstart.md                   # Phase 1
├── contracts/                      # Phase 1
│   ├── README.md                   # pin 329a1db, blobs e SHA-256
│   ├── openapi.flows.yaml          # cópia byte a byte do pin
│   ├── components-shared.schema.json
│   └── messages-stream.behavior.md # ordem de avaliação e efeitos
├── checklists/requirements.md
└── tasks.md                        # Phase 2 (/speckit-tasks, não criado aqui)
```

### Source Code (repository root)

```text
temba/api/v2/internals/msgs/
├── serializers.py     # MODIFICA: StrictCharField, StrictIntegerField, StrictChoiceField,
│                      #   validate_cta_url, ClosedSerializer, ListItemSerializer,
│                      #   ListMessageSerializer, CtaMessageSerializer, HeaderSerializer,
│                      #   StreamMsgField; MsgStreamSerializer.msg = StreamMsgField(required=False)
├── views.py           # MODIFICA: MsgStreamView (permission_classes, get_authenticate_header,
│                      #   handle_exception com log de desfecho, orquestração de idempotência)
├── permissions.py     # NOVO: ModuleJWTProjectScope
├── idempotency.py     # NOVO: constantes, cliente Redis com timeout, extract_key, claim,
│                      #   store_success, release (prefixo idempotency:messages_stream)
├── observability.py   # NOVO: extract_correlation_id, bind_request_scope (tags + scrub_stream_event),
│                      #   log_outcome
├── tests.py           # MODIFICA: testes novos de US1 a US4 e privacidade; os atuais continuam
├── services.py        # SEM MUDANÇA
└── urls.py            # SEM MUDANÇA

WENI-CHANGELOG.md      # MODIFICA: 1 bullet feat + 1 bullet de segurança
```

**Structure Decision**: tudo no app `temba/api/v2/internals/msgs/`, ao lado de `MsgStreamView`, seguindo o desenho de `internals/broadcasts/` (`idempotency.py` próprio). Não há camada `usecases/` neste app. A persistência fica em `services.py`, que não muda.

## Desenho por componente

### `serializers.py`

- `StreamMsgField(DictField)`:
  - herda a checagem de dicionário;
  - valida só as chaves `quick_replies`, `list_message`, `cta_message`, `interaction_type`, `header` e `footer` presentes, cada uma com o campo da tabela de [data-model.md](data-model.md) §2;
  - acumula os erros por chave e levanta um único `ValidationError`, que o DRF coloca sob `msg`;
  - devolve o dicionário original (R6).
- `ClosedSerializer.to_internal_value`: erro `"Unexpected field."` para cada chave fora de `fields`, junto com os erros dos campos declarados (R5).
- `quick_replies`: `ListField(child=StrictCharField(min_length=1, trim_whitespace=False), allow_empty=False)`.
- `footer`: `StrictCharField(allow_blank=True, trim_whitespace=False)`.
- O `validate()` atual de `MsgStreamSerializer` (identificador e conteúdo mínimo) e os campos de topo ficam como estão (FR-016, AD-004 regra 2).

### `permissions.py`

- `ModuleJWTProjectScope(BasePermission)`, regra de [data-model.md](data-model.md) §4.
- Sem efeito colateral. Uma única consulta a `Channel` (`only("org__proj_uuid")`) só quando o token tem claim de canal.

### `idempotency.py`

- API: `extract_key(request) -> str | None`, `claim(project_uuid, key, body_hash) -> (state, ids)`, `store_success(project_uuid, key, body_hash, ids)` e `release(project_uuid, key)`.
- Estados `miss`, `hit`, `conflict` e `in_progress`, conforme a tabela de [data-model.md](data-model.md) §3.
- `RedisError` sobe para a view, que responde `503`. `release` captura `RedisError` e registra com ids opacos.

### `views.py` — `MsgStreamView`

- `permission_classes = [ModuleJWTProjectScope]`; `authentication_classes` continua o do mixin.
- `get_authenticate_header(self, request)` devolve `None`. Comentário: o contrato fixa `403` para toda falha de JWT (AD-004 regra 4).
- `handle_exception`: registra `rejected_auth`/`rejected_tenant` e delega ao DRF.
- `post`: segue exatamente a ordem de [contracts/messages-stream.behavior.md](contracts/messages-stream.behavior.md).
  - **Com chave válida**: `transaction.atomic()` em volta do laço de `create_message_db_only` e do `store_success`.
  - **Sem chave**: o laço atual, inalterado.

### `observability.py`

- `extract_correlation_id(request)`: de 1 a 128 caracteres, sem `strip`; fora disso, `None`.
- `bind_request_scope(project_uuid, channel_uuid, correlation_id)`: `sentry_sdk.configure_scope()`, tags e `add_event_processor(scrub_stream_event)`.
- `log_outcome(outcome, *, reason=None, status, project_uuid, channel_uuid, correlation_id, idempotency_key_present)`: um `logger.info` com `extra`.

## Riscos de implementação

- **URL não ASCII**: o contrato pede URI, então uma URL de CTA com caractere não ASCII é rejeitada (`400`). O `nexus-ai` precisa enviar a URL com percent-encoding. Levar ao tech lead do `nexus-ai` junto com o PR. Isso não muda o contrato.
- **Comportamento do SDK do Sentry**: o filtro depende de o processor do scope da requisição rodar depois do processor de request do `DjangoIntegration`. No sentry-sdk 1.45.1, os processors de scope rodam na ordem em que foram adicionados, e o do Django é adicionado antes da view. O teste O.1 do [quickstart.md](quickstart.md) é a prova. Se ele falhar, parar e decidir com o time antes de sair do escopo de arquivos. A alternativa conhecida, um `before_send` global filtrado pela rota, mexe em `temba/settings_common.py`.
- **Peak Load**: o valor numérico está pendente antes do passo 1 de deploy.
- **Pin**: re-fixar o Architecture doc e os contratos na tag `arch-v1` quando o documento tagueado registrar a aprovação do `flows`, e conferir os hashes em [contracts/README.md](contracts/README.md).

## Complexity Tracking

Sem violações da constitution a justificar.
