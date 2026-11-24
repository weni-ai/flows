---

description: "Task list for 022-sa-components-streaming (fatia Flows)"
---

# Tasks: componentes de streaming do Shopping Assistant em `POST /api/v2/internals/messages/stream` (fatia Flows)

**Input**: `specs/022-sa-components-streaming/` ([spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md))

**Contratos**: pin `329a1db8c1f3f62208b052457e0e3bc9654ce102` ([contracts/README.md](contracts/README.md)). Não usar `fe00c1c`.

**Tests**: obrigatórios (Principle XIV e Test Strategy da spec). Cada fase de história termina num fluxo `TembaTest` em `temba/api/v2/internals/msgs/tests.py`, da chamada HTTP até a linha em `msgs_msg`, com sucesso e falha. Testes isolados de serializer só complementam esse fluxo.

**Organization**: uma fase por user story, na ordem P1 → P4 da spec.

**Escopo de arquivos**: `temba/api/v2/internals/msgs/` e `WENI-CHANGELOG.md`. Não tocar em:

- `temba/api/v2/internals/broadcasts/idempotency.py` (só importar `compute_body_hash`);
- `temba/api/auth/jwt.py`;
- `temba/settings_common.py`;
- `temba/api/v2/internals/msgs/services.py`;
- `temba/api/v2/internals/msgs/urls.py`.

Sem migration, sem locale, sem Mailroom, sem Courier, sem `whatsapp_broadcasts` e sem o restante da spec 009.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: pode rodar em paralelo (arquivo diferente, sem dependência pendente)
- **[Story]**: US1 a US4, conforme [spec.md](spec.md)

---

## Phase 1: Setup

**Purpose**: linha de base e helpers de teste compartilhados

- [X] T001 Rodar `poetry run python manage.py test temba.api.v2.internals.msgs` em `main` e registrar que os testes atuais de stream (`test_stream_*` em `temba/api/v2/internals/msgs/tests.py`) passam. Eles provam FR-016 e não podem ser alterados nas fases seguintes, salvo para acrescentar testes.
- [X] T002 Em `temba/api/v2/internals/msgs/tests.py`, acrescentar helpers compartilhados e reutilizá-los em todas as fases:
  - **Mixin `ModuleJWTTestMixin`**:
    - gera, uma vez por classe, um par RSA com `cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key` e serializa a chave pública em PEM;
    - aplica `override_settings(JWT_PUBLIC_KEY=<PEM>)` no `setUp`;
    - expõe `jwt_headers(project_uuid=None, channel_uuid=None, *, expired=False, wrong_key=False)`, que devolve `{"HTTP_AUTHORIZATION": "Bearer <token RS256>"}` assinado com `jwt.encode`.
  - **Helper `post_stream(payload, headers=None, **extra)`**: faz `self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json", **headers, **extra)`.
  - **Context manager `assert_no_mailroom()`**: `patch` de `temba.mailroom.queue._queue_task`, `_queue_batch_task` e `_queue_handler_task`, com `assert_not_called()` ao sair.
  - **Builders de payload** a partir dos exemplos `quickReplies`, `listAndCtaMultiComponent` e `textlessComponent` de `specs/022-sa-components-streaming/contracts/openapi.flows.yaml`, trocando `project_uuid`, `channel_uuid` e `urns` pelos do `TembaTest`.
  - **Limpeza Redis**: `delete` de todas as chaves `idempotency:messages_stream:*` no `setUp` e no `tearDown`, com `django_redis.get_redis_connection().scan_iter`.

---

## Phase 2: Foundational

**Purpose**: observabilidade compartilhada por todas as histórias (FR-033 a FR-036). Bloqueia as fases seguintes porque cada uma registra o próprio desfecho.

- [X] T003 [P] Criar `temba/api/v2/internals/msgs/observability.py` (research R10, R11):
  - **Constantes nomeadas**:
    - `CORRELATION_ID_HEADER = "X-Correlation-ID"` e `MAX_CORRELATION_ID_LENGTH = 128`;
    - os valores de `outcome` do FR-036: `OUTCOME_CREATED`, `OUTCOME_REPLAYED`, `OUTCOME_CONFLICT`, `OUTCOME_REJECTED_VALIDATION`, `OUTCOME_REJECTED_AUTH`, `OUTCOME_REJECTED_TENANT`, `OUTCOME_PROJECT_NOT_FOUND`, `OUTCOME_ERROR`;
    - `REASON_DEDUPE_UNAVAILABLE = "dedupe_unavailable"` e `REASON_UNEXPECTED = "unexpected"`.
  - **`extract_correlation_id(request)`**: devolve o header como veio, sem `strip`, se `1 <= len <= 128`; senão, `None`.
  - **`scrub_stream_event(event, hint)`**: remove `event["request"]["data"]`, as `vars` de todos os frames em `exception.values[].stacktrace.frames` e em `threads.values[].stacktrace.frames`, e o `data` dos breadcrumbs com `category == "query"`. Devolve o evento.
  - **`bind_request_scope(*, project_uuid, channel_uuid, correlation_id)`**: dentro de `sentry_sdk.configure_scope()`:
    - tags `project_uuid`, `channel_uuid` (se houver), `correlation_id` (se houver), `caller="module_jwt"`, `account_id="none"` e `user_id="none"`;
    - `scope.add_event_processor(scrub_stream_event)`.
  - **`log_outcome(outcome, *, status, project_uuid=None, channel_uuid=None, correlation_id=None, idempotency_key_present=False, reason=None)`**: um `logger.info("messages_stream outcome", extra={...})` só com esses campos opacos. Nunca recebe `request.data`, `msg` nem erros de validação.
- [X] T004 Em `temba/api/v2/internals/msgs/views.py`, no início de `MsgStreamView.post`:
  - chamar `extract_correlation_id` e `bind_request_scope`, usando o `project_uuid` e o `channel_uuid` brutos de `request.data`, só quando forem `str`;
  - chamar `log_outcome` nas saídas atuais: `201` → `created`; `400` do serializer ou de `ValueError` → `rejected_validation`; `404` → `project_not_found`.

  Nenhum status nem corpo muda. Depende de T003.

**Checkpoint**: T001 continua verde. O endpoint se comporta como hoje e passa a registrar o desfecho.

---

## Phase 3: User Story 1 — Registrar componentes sem envio (Priority: P1) 🎯 MVP

**Goal**: uma resposta do Shopping Assistant com componentes válidos (inclusive texto vazio e vários tipos juntos) é gravada só no banco, com `Msg.metadata` igual ao `msg` enviado (FR-012 a FR-017).

**Independent Test**: com JWT real de P, enviar os exemplos do OpenAPI e conferir `201`, a linha em `msgs_msg`, `Msg.metadata == msg` e nenhuma tarefa de Mailroom ([quickstart.md](quickstart.md) US1).

### Tests for User Story 1

- [X] T005 [US1] Em `temba/api/v2/internals/msgs/tests.py`, nova classe `TestMsgStreamComponentsPersist(ModuleJWTTestMixin, TembaTest)`, com um teste por cenário de US1 (1.1 a 1.10 do [quickstart.md](quickstart.md)):
  - cada teste chama `post_stream` com `jwt_headers(project_uuid=P)` e roda dentro de `assert_no_mailroom()` (cenário 1.11);
  - cada teste verifica `201 {"ids": [...]}`, `Msg.objects.get(id=...)`, `metadata == payload["msg"]` como dicionário e o `Msg.text` esperado;
  - o 1.5 verifica `Msg.text == ""` com `quick_replies` válido (FR-012);
  - o 1.10 usa duas URNs e verifica as duas linhas.
- [X] T006 [US1] Na mesma classe de `temba/api/v2/internals/msgs/tests.py`, os caminhos de falha com componentes válidos e o comportamento preservado:
  - `project_uuid` sem `Org` (token do mesmo P) → `404 {"error": "Project not found"}` e 0 linhas;
  - `channel_uuid` de um canal de `self.org2` → `400` com `"Channel not found"` e 0 linhas;
  - `msg: {"text": ""}` sem componente → mesmo resultado de hoje (`201`, `Msg.text == ""`). Esse teste fixa FR-016: a spec não cria rejeição nova para texto vazio sem componente.

### Implementation for User Story 1

- [X] T007 [US1] Em `temba/api/v2/internals/msgs/serializers.py`:
  - criar a constante `MSG_COMPONENT_FIELDS = ("quick_replies", "list_message", "cta_message", "interaction_type", "header", "footer")`;
  - criar a classe `StreamMsgField(serializers.DictField)`, cujo `to_internal_value(data)` chama `super().to_internal_value(data)` só para manter a checagem de dicionário e o erro atual, e devolve o **dicionário original** `data` (research R6);
  - trocar `msg = serializers.DictField(required=False)` por `msg = StreamMsgField(required=False)` em `MsgStreamSerializer`;
  - manter o `validate()` atual e os campos de topo intactos (AD-004 regra 2).
- [X] T008 [US1] Em `temba/api/v2/internals/msgs/views.py`, garantir que `MsgStreamView.post` passe `serializer.validated_data.get("msg") or {}` (o dicionário original) como `metadata` a `create_message_db_only`, sem copiar nem transformar, e que a origem de `text` (`text` → `message` → `msg.text` → `""`) siga igual (FR-014, FR-017). Não alterar `temba/api/v2/internals/msgs/services.py`.
- [X] T009 [US1] Rodar `poetry run python manage.py test temba.api.v2.internals.msgs` e confirmar T005, T006 e os testes de T001 verdes.

**Checkpoint**: US1 entregável sozinha.

---

## Phase 4: User Story 2 — Rejeitar componente malformado (Priority: P2)

**Goal**: os seis campos de `msg` validados no formato do OpenAPI 1.1.0 (com `$ref` ao schema compartilhado):

- `list_message`, cada item de `list_items`, `cta_message` e `msg.header` fechados;
- chaves no nível de `msg` abertas;
- `400` sob `msg`, no caminho do campo, sem nenhuma linha (FR-001 a FR-011).

**Independent Test**: [quickstart.md](quickstart.md) US2. Cada payload inválido devolve `400` com o caminho em `response.json()["msg"]` e a contagem de `Msg` fica inalterada. O cenário 2.19 devolve `201`.

### Tests for User Story 2

- [X] T010 [US2] Em `temba/api/v2/internals/msgs/tests.py`, nova classe `TestMsgStreamComponentsValidation(ModuleJWTTestMixin, TembaTest)` com JWT real de P:
  - **Cenários 2.1 a 2.13 e 2.15 a 2.18 do [quickstart.md](quickstart.md)**: um teste ou `subTest` por entrada, verificando `status_code == 400`, o caminho do erro (por exemplo, `json["msg"]["cta_message"]["foo"]` e `json["msg"]["list_message"]["list_items"]["0"]["foo"]`) e `Msg.objects.count()` igual ao de antes.
  - **Cenário 2.19**: `msg.foo` com componentes válidos → `201` e `metadata["foo"]` gravado.
  - **Casos aceitos pelo contrato** → `201`: `quick_replies: ["   "]`, `item_count: 9.0`, `header.text: ""`, `footer: ""` e `list_items[].uuid` que não está em formato UUID.
  - **Texto vazio com componente inválido** (`msg.text: ""` + `quick_replies: []`) → `400` e 0 linhas.
  - **URL de CTA**: `HTTPS://…` maiúsculo, com espaço, com caractere não ASCII, `https://`, `ftp://…` e `javascript:…` → `400` em `msg.cta_message.url`.

### Implementation for User Story 2

- [X] T011 [US2] Em `temba/api/v2/internals/msgs/serializers.py`, campos estritos (research R3):
  - `StrictCharField(serializers.CharField)`: `trim_whitespace=False` por padrão; `to_internal_value` rejeita qualquer valor que não seja `str` (inclui `bool`, `int`, `float`, `dict`, `list`).
  - `StrictIntegerField(serializers.IntegerField)`: rejeita `bool` e `str`; aceita `int` e `float` com `is_integer()`; aplica `min_value`.
  - `StrictChoiceField(serializers.ChoiceField)`: rejeita o que não for `str`.
- [X] T012 [US2] Em `temba/api/v2/internals/msgs/serializers.py`, validação da URL do CTA (research R4):
  - constantes nomeadas `CTA_URL_PATTERN = re.compile(r"^https?://.+")` (sensível a maiúsculas), `URI_ALLOWED_CHARS` (ASCII `unreserved` + `reserved` da RFC 3986) e `CTA_URL_ERROR = "Enter a valid http(s) URL."`;
  - `validate_cta_url(value)`, que exige três coisas: casar com `CTA_URL_PATTERN`, só ter caracteres de `URI_ALLOWED_CHARS` ou `%` seguido de dois hex, e `urllib.parse.urlsplit` sem erro.

  Não usar `URLField` nem `URLValidator`.
- [X] T013 [US2] Em `temba/api/v2/internals/msgs/serializers.py`, criar `ClosedSerializer(serializers.Serializer)`, cujo `to_internal_value` junta os erros dos campos declarados com `{"<chave>": ["Unexpected field."]}` para cada chave do dicionário fora de `self.fields` (constante `UNEXPECTED_FIELD_ERROR = "Unexpected field."`) e levanta um único `ValidationError` (research R5).
- [X] T014 [US2] Em `temba/api/v2/internals/msgs/serializers.py`, os validadores dos seis campos, conforme [data-model.md](data-model.md) §2:
  - `ListItemSerializer(ClosedSerializer)`: `uuid` e `title` são `StrictCharField(min_length=1)`; `description` é `StrictCharField(required=False, allow_blank=True)`.
  - `ListMessageSerializer(ClosedSerializer)`: `button_text` é `StrictCharField(min_length=1)`; `list_items` é `ListField(child=ListItemSerializer(), allow_empty=False)`; `item_count` é `StrictIntegerField(required=False, min_value=1)`.
  - `CtaMessageSerializer(ClosedSerializer)`: `display_text` é `StrictCharField(min_length=1)`; `url` é `StrictCharField(validators=[validate_cta_url])`.
  - `HeaderSerializer(ClosedSerializer)`: `type` é `StrictChoiceField(choices=["text"], required=False)`; `text` é `StrictCharField(required=False, allow_blank=True)`.
  - Campos simples:
    - `quick_replies`: `ListField(child=StrictCharField(min_length=1), allow_empty=False)`;
    - `interaction_type`: `StrictChoiceField(choices=["list", "cta_url"])`;
    - `footer`: `StrictCharField(allow_blank=True)`.

  `quick_replies` e `footer` não ganham regra além de FR-002 e FR-007.
- [X] T015 [US2] Em `temba/api/v2/internals/msgs/serializers.py`, completar `StreamMsgField.to_internal_value`:
  - para cada chave de `MSG_COMPONENT_FIELDS` presente, rejeitar `None` com `"This field may not be null."`;
  - rodar o validador de T014 correspondente (`run_validation`) e acumular os erros por chave;
  - se houver erros, levantar um único `ValidationError(errors)`, que o DRF coloca sob `msg`;
  - sem erros, devolver o dicionário original, com as chaves fora dos seis intactas (FR-010, FR-014).
- [X] T016 [US2] Em `temba/api/v2/internals/msgs/tests.py`, testes unitários complementares de `StreamMsgField` e de `validate_cta_url` para as variações caras de montar pelo fluxo (tipos estritos e limites da URL). Eles não substituem T010.
- [X] T017 [US2] Rodar `poetry run python manage.py test temba.api.v2.internals.msgs` e confirmar T005, T006, T010, T016 e T001 verdes.

**Checkpoint**: US1 e US2 funcionam juntas, e as chamadas atuais seguem iguais.

---

## Phase 5: User Story 3 — `Idempotency-Key` (Priority: P3)

**Goal**: retry do `nexus-ai` sem duplicar linhas, conforme [data-model.md](data-model.md) §3 e [contracts/messages-stream.behavior.md](contracts/messages-stream.behavior.md):

- `201` na criação e `200` com os mesmos ids no replay;
- `409` com `code` `idempotency_conflict` ou `idempotency_in_progress`;
- liberação da chave só pela requisição que a reservou;
- chave vazia ou com mais de 128 caracteres tratada como ausente;
- `503` com o Redis indisponível (FR-018 a FR-027).

**Independent Test**: [quickstart.md](quickstart.md) US3. Mesmo corpo com a mesma chave: `201` e depois `200`, com uma linha só. Outro corpo com a mesma chave: `409 idempotency_conflict`.

### Tests for User Story 3

- [X] T018 [US3] Em `temba/api/v2/internals/msgs/tests.py`, nova classe `TestMsgStreamIdempotency(ModuleJWTTestMixin, TembaTest)` com JWT real e Redis de teste limpo pelo helper de T002, com um teste por cenário:
  - **3.1**: `201`; a chave `idempotency:messages_stream:{P}:K` com `state == "done"` e `ttl` entre `86400 - 5` e `86400`.
  - **3.2**: `200` com os mesmos ids e as chaves JSON reordenadas; 0 linhas novas.
  - **3.3**: `409`, `code == "idempotency_conflict"` e `error` presente; 0 linhas; depois disso, o corpo original com `K` ainda devolve `200`.
  - **3.4**: dois `201` sem header.
  - **3.5**: isolamento entre P e P2, cada um com o próprio token.
  - **3.6**: uma chave `idempotency:whatsapp_broadcasts:{P}:K` pré-gravada continua intacta, e a requisição recebe `201`.
  - **3.7**: reserva `{"state": "inflight", ...}` gravada direto → `409`, `code == "idempotency_in_progress"`; 0 linhas; o valor da reserva não muda.
  - **3.8**: `DEL` da chave e reenvio → `201` com ids novos.
  - **3.9**: `K` = `""`, `"   "` e 129 caracteres → `201` sem chave gravada; o mesmo corpo de novo → `201` com ids novos. `K` com 128 caracteres exatos → deduplica.
  - **3.10**: primeira tentativa com `K` terminando em `400`, `404` (Org inexistente) e `500` (`create_message_db_only` com `patch` e `side_effect=RuntimeError`); a seguinte, corrigida, com `K` → `201`.
  - **3.11**: `patch` do cliente Redis do módulo com `side_effect=redis.exceptions.ConnectionError` → `503 {"error": "Service temporarily unavailable"}`; 0 linhas.
  - **3.12**: `patch` de `store_success` com `side_effect=redis.exceptions.ConnectionError` depois das linhas → `503`; 0 linhas (transação desfeita).
  - **US2 cenário 14**: payload inválido com `K` → `400`; corrigido com `K` → `201`.

### Implementation for User Story 3

- [X] T019 [P] [US3] Criar `temba/api/v2/internals/msgs/idempotency.py` com as constantes nomeadas (research R7):
  - headers e limites: `IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"`, `MAX_KEY_LENGTH = 128`;
  - TTLs: `DONE_TTL_SECONDS = 86400` (24h, FR-020) e `INFLIGHT_TTL_SECONDS = 120`. O comentário diz por quê: é igual ao `timeout` do worker em `docker/gunicorn/gunicorn.conf.py`, e uma reserva mais velha pertence a uma requisição morta;
  - Redis: `REDIS_TIMEOUT_SECONDS = 2` e `REDIS_KEY_PREFIX = "idempotency:messages_stream"`;
  - codes e mensagens: `CODE_IDEMPOTENCY_CONFLICT = "idempotency_conflict"`, `CODE_IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"`, `CONFLICT_ERROR = "Idempotency-Key reused with different body"`, `IN_PROGRESS_ERROR = "Request with this Idempotency-Key is already being processed"` e `SERVICE_UNAVAILABLE_ERROR = "Service temporarily unavailable"`;
  - estados `STATE_INFLIGHT`/`STATE_DONE` e resultados `CLAIM_MISS`/`CLAIM_HIT`/`CLAIM_CONFLICT`/`CLAIM_IN_PROGRESS`.

  Não importar nem alterar nada de `broadcasts/idempotency.py` além do import de T021.
- [X] T020 [US3] Em `temba/api/v2/internals/msgs/idempotency.py`:
  - `get_client()`: cria sob demanda e reaproveita um `redis.Redis.from_url(settings.CACHES["default"]["LOCATION"], socket_timeout=REDIS_TIMEOUT_SECONDS, socket_connect_timeout=REDIS_TIMEOUT_SECONDS)`;
  - `_redis_key(project_uuid, key)`: devolve `f"{REDIS_KEY_PREFIX}:{project_uuid}:{key}"`;
  - `extract_key(request)`: lê `IDEMPOTENCY_KEY_HEADER` e aplica `strip()`; se o resultado for vazio ou tiver mais de `MAX_KEY_LENGTH`, devolve `None`, sem `400` (FR-025).
- [X] T021 [US3] Em `temba/api/v2/internals/msgs/idempotency.py`, conforme a tabela de [data-model.md](data-model.md) §3:
  - **`claim(project_uuid, key, body_hash)`**:
    - `SET NX EX INFLIGHT_TTL_SECONDS` com `{"state": "inflight", "body_hash"}`;
    - se não conseguir, `GET`. Valor ausente: tenta o `SET NX` de novo; se ainda falhar, `CLAIM_IN_PROGRESS`;
    - `done` com o mesmo hash → `(CLAIM_HIT, ids)`; `done` com outro hash → `CLAIM_CONFLICT`; `inflight` ou valor ilegível → `CLAIM_IN_PROGRESS`.
  - **`store_success(project_uuid, key, body_hash, ids)`**: `SET EX DONE_TTL_SECONDS` com `{"state": "done", "body_hash", "ids"}`.
  - **`release(project_uuid, key)`**: `DEL`; captura `redis.exceptions.RedisError` e registra só com ids opacos.

  `RedisError` em `claim` e em `store_success` sobe para quem chamou. Reutilizar `compute_body_hash` com `from temba.api.v2.internals.broadcasts.idempotency import compute_body_hash`, sem editar aquele arquivo.
- [X] T022 [US3] Em `temba/api/v2/internals/msgs/views.py`, orquestrar `MsgStreamView.post` na ordem de [contracts/messages-stream.behavior.md](contracts/messages-stream.behavior.md):
  1. **Reserva**: `key = extract_key(request)`. Se houver `key` e o `project_uuid` do corpo for um UUID válido (`uuid.UUID`), usar o UUID normalizado como `project_uuid` e chamar `claim`:
     - `CLAIM_HIT` → `200 {"ids": ids}` e `log_outcome(replayed)`;
     - `CLAIM_CONFLICT` → `409 {"code": CODE_IDEMPOTENCY_CONFLICT, "error": CONFLICT_ERROR}` e `log_outcome(conflict, reason=CODE_IDEMPOTENCY_CONFLICT)`;
     - `CLAIM_IN_PROGRESS` → `409 {"code": CODE_IDEMPOTENCY_IN_PROGRESS, "error": IN_PROGRESS_ERROR}` e `log_outcome(conflict, reason=CODE_IDEMPOTENCY_IN_PROGRESS)`;
     - `RedisError` → `503 {"error": SERVICE_UNAVAILABLE_ERROR}` e `log_outcome(error, reason=REASON_DEDUPE_UNAVAILABLE)`.

     Nenhuma dessas respostas escreve no Redis.
  2. **Validação e projeto**: depois da reserva vêm o serializer (`400` → `release`) e o `Org` (`404` → `release`).
  3. **Com chave reservada**: `with transaction.atomic():` em volta do laço de `create_message_db_only` e de `store_success(..., ids)`.
     - `ValueError` → `release` e `400 {"error": str(e)}`, como hoje;
     - `RedisError` → `release` e `503`;
     - outra exceção → `release` e relançar (`500`, com `log_outcome(error, reason=REASON_UNEXPECTED)`).
  4. **Sem chave**: o laço atual, sem `atomic` (FR-016, FR-018).
  5. **Sucesso**: `201 {"ids": [...]}`.

  `release` só é chamado no caminho da requisição dona da reserva (FR-024).
- [X] T023 [US3] Rodar `poetry run python manage.py test temba.api.v2.internals.msgs` (T018 e as fases anteriores verdes) e confirmar com `git diff --exit-code -- temba/api/v2/internals/broadcasts/idempotency.py` que o módulo de referência não mudou.

**Checkpoint**: US1, US2 e US3 funcionam juntas. Sem o header, o comportamento é o de hoje.

---

## Phase 6: User Story 4 — JWT de módulo e escopo de tenant (Priority: P4)

**Goal**: permissão explícita só nesta view; o `project_uuid` do corpo é comparado ao claim antes da chave e da gravação; toda falha de JWT ou de escopo devolve `403` com `detail`, nunca `401`; projeto autorizado inexistente devolve `404` (FR-028 a FR-032).

**Independent Test**: [quickstart.md](quickstart.md) US4, com autenticação e permissão **reais**.

### Tests for User Story 4

- [X] T024 [US4] Em `temba/api/v2/internals/msgs/tests.py`, nova classe `TestMsgStreamAuthz(ModuleJWTTestMixin, TembaTest)`. Proibido usar `patch` de `MsgStreamView.authentication_classes`, de `MsgStreamView.permission_classes` ou de `RequiredJWTAuthentication.authenticate`. Um teste por cenário:
  - **4.1**: sem header → `403`, `"detail"` no corpo, 0 linhas e nenhuma chave `idempotency:messages_stream:*`.
  - **4.2**: `wrong_key=True`, `expired=True` e token sem claim de tenant → `403` com `detail`. Verificar `assertNotEqual(status, 401)` em todos.
  - **4.3**: token de P1 com corpo de P2 existente → `403` com `detail == "You do not have permission to perform this action."`; 0 linhas em P1 e P2.
  - **4.4**: token só com `channel_uuid` de um canal de P1 e corpo de P2 → `403`.
  - **4.5**: token de P sem `Org` e corpo de P → `404 {"error": "Project not found"}`.
  - **4.6**: token de P e corpo de P → `201`.
  - **4.7**: token de P e `channel_uuid` de outro projeto → `400` com `"Channel not found"`; 0 linhas.
  - **4.8**: token de P1, corpo de P2 e `Idempotency-Key: K` → `403`, e nenhuma chave `*:K` no Redis.
  - **Composição**: um teste afirma que `MsgStreamView.permission_classes == [ModuleJWTProjectScope]`, que não é vazio e que não contém `IsAuthenticated` nem `AllowAny` (Principle XVII).

### Implementation for User Story 4

- [X] T025 [P] [US4] Criar `temba/api/v2/internals/msgs/permissions.py` com `ModuleJWTProjectScope(BasePermission)`, conforme [data-model.md](data-model.md) §4 e research R2:
  - **Projeto autorizado**: `jwt_tenant_claims(getattr(request, "jwt_payload", None))`.
    - com claim de projeto, ele é a autoridade; se também houver canal, exigir `Channel.objects.filter(uuid=channel, is_active=True, org__proj_uuid=project).exists()`;
    - só com claim de canal, o projeto autorizado é o `org.proj_uuid` do canal ativo; canal inexistente → `False`;
    - sem claims → `False`.
  - **Comparação com o corpo**: se `request.data` for `Mapping` e tiver `project_uuid`, normalizar com `uuid.UUID(str(...))` e comparar. UUID inválido ou diferente → `False`. `project_uuid` ausente, ou corpo que não é objeto → `True`, porque o serializer devolve `400`.

  Sem efeito colateral no `request`. Não alterar `temba/api/auth/jwt.py`.
- [X] T026 [US4] Em `temba/api/v2/internals/msgs/views.py`, em `MsgStreamView`:
  - `permission_classes = [ModuleJWTProjectScope]`;
  - `get_authenticate_header(self, request)` devolve `None`, com comentário: o contrato fixa `403` para toda falha de JWT neste endpoint (AD-004 regra 4) e não pode depender do autenticador compartilhado;
  - `handle_exception(self, exc)`: chama `log_outcome(rejected_auth)` para `AuthenticationFailed`/`NotAuthenticated` e `log_outcome(rejected_tenant)` para `PermissionDenied`, com `status=403`, e depois `return super().handle_exception(exc)`.

  Não alterar `JWTAuthMixinRequired` nem os outros endpoints.
- [X] T027 [US4] Rodar `poetry run python manage.py test temba.api.v2.internals.msgs`:
  - T024 e todas as fases anteriores verdes;
  - os testes atuais de stream (T001), que substituem autenticação e permissão, continuam verdes sem edição;
  - rodar também `poetry run python manage.py test temba.api.tests` para confirmar que o autenticador compartilhado e os outros endpoints não mudaram.

**Checkpoint**: as quatro histórias estão completas.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: privacidade (SC-006), changelog, gates e auditoria de escopo.

- [X] T028 Em `temba/api/v2/internals/msgs/tests.py`, nova classe `TestMsgStreamObservability(ModuleJWTTestMixin, TembaTest)`, com os cenários O.1 a O.4 do [quickstart.md](quickstart.md):
  - **O.1**: inicializar dentro do teste um cliente Sentry com transporte em memória (salvando e restaurando o hub). Com `patch` de `create_message_db_only` (`side_effect=RuntimeError`), enviar um payload com `text`, `quick_replies`, `button_text`, `display_text`, `list_items` e `url` conhecidos. Verificar que o JSON serializado do evento capturado não contém nenhum desses valores e que tem as tags `project_uuid`, `correlation_id`, `caller=module_jwt`, `account_id=none` e `user_id=none`.
  - **O.2**: usar `assertLogs("temba.api.v2.internals.msgs")` em cada desfecho: `created`, `replayed`, `conflict` com os dois `reason`, `rejected_validation`, `rejected_auth`, `rejected_tenant`, `project_not_found` e `error`. Verificar `outcome` e `reason` e que nenhum valor de conteúdo aparece no registro.
  - **O.3 e O.4**: `X-Correlation-ID` com 1 e 128 caracteres aparece como veio, no log e na tag; vazio ou com 129 caracteres → a requisição é aceita e o valor não aparece.
- [X] T029 [P] Em `WENI-CHANGELOG.md`, sob a próxima versão no formato do arquivo, acrescentar:
  - `* feat: validate Shopping Assistant components and support Idempotency-Key on internal messages stream endpoint`
  - `* fix: security — scope internal messages stream to the module JWT project and declare an explicit permission (SEC-03)`
- [X] T030 Rodar os gates do [quickstart.md](quickstart.md): `poetry run coverage run manage.py test temba.api.v2.internals.msgs temba.api.tests`, `poetry run coverage report --include="temba/api/v2/internals/msgs/*"` (sem linha nova descoberta nos módulos novos) e `./code_check.py` limpo, que inclui o check de migrations faltando. Sem `# pragma: no cover` novo.
- [X] T031 Auditar o escopo, com `git diff --stat main` e `git status`:
  - só podem mudar `temba/api/v2/internals/msgs/{serializers,views,permissions,idempotency,observability,tests}.py` e `WENI-CHANGELOG.md`;
  - `temba/api/v2/internals/broadcasts/idempotency.py`, `temba/api/auth/jwt.py`, `temba/settings_common.py`, `temba/api/v2/internals/msgs/services.py` e `temba/api/v2/internals/msgs/urls.py` ficam intactos;
  - sem arquivo em `locale/` nem migration nova;
  - por `rg`, nenhum literal `128`, `86400`, `120`, `"Idempotency-Key"`, `"X-Correlation-ID"`, `"idempotency_conflict"`, `"idempotency_in_progress"` ou `https?://` fora das constantes nomeadas (Principle XV);
  - nenhuma chamada de log em `msgs/` recebe `request.data`, `msg`, `serializer.errors` nem `str(e)` de validação.
- [ ] T032 Gate de deploy, fora do PR de código: medir o pico em produção pela fórmula de [plan.md](plan.md) (Peak Load) e registrar o valor numérico em `specs/022-sa-components-streaming/plan.md` antes do passo 1 da *Delivery Sequence*. Até lá, o valor fica como "medição pendente".

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sem dependência. T002 vem antes de qualquer teste novo.
- **Foundational (Phase 2)**: depende de Setup e bloqueia todas as histórias (T004 depende de T003).
- **US1 (Phase 3)**: depende da Phase 2.
- **US2 (Phase 4)**: depende de T007 (o `StreamMsgField` criado em US1), porque estende o mesmo campo no mesmo arquivo.
- **US3 (Phase 5)**: depende da Phase 2. É independente de US1 e US2 em comportamento, mas T022 edita `views.py` depois de T008, então vem depois de US1 na ordem de arquivo.
- **US4 (Phase 6)**: depende da Phase 2. T026 edita `views.py` depois de T022.
- **Polish (Phase 7)**: depende das histórias. T029 pode ser feita a qualquer momento.

### Within Each User Story

- Testes primeiro. Alguns de US1 já passam hoje e ficam como regressão. Os de US2, US3 e US4 precisam falhar antes da implementação.
- `serializers.py`, `idempotency.py` e `permissions.py` antes de `views.py`.
- A história só fecha com o fluxo HTTP → `msgs_msg` verde.

### Parallel Opportunities

- T003 (`observability.py`) em paralelo com T002 (`tests.py`).
- T019 (`idempotency.py`) e T025 (`permissions.py`) podem começar logo após a Phase 2, em paralelo com US1 e US2, porque são arquivos novos e independentes.
- T029 (`WENI-CHANGELOG.md`) em paralelo com qualquer tarefa.
- As tarefas em `tests.py`, `serializers.py` e `views.py` são sequenciais (mesmo arquivo).

---

## Parallel Example

```bash
# Logo após a Phase 2, três pessoas em arquivos diferentes:
Task: "T019 [US3] Criar temba/api/v2/internals/msgs/idempotency.py com constantes"
Task: "T025 [US4] Criar temba/api/v2/internals/msgs/permissions.py com ModuleJWTProjectScope"
Task: "T011-T015 [US2] Validação em temba/api/v2/internals/msgs/serializers.py"

# A qualquer momento:
Task: "T029 Bullets feat e segurança em WENI-CHANGELOG.md"
```

---

## Implementation Strategy

### MVP (User Story 1)

1. Phase 1 e Phase 2.
2. Phase 3 (US1): componentes gravados em `Msg.metadata` sem envio.
3. **Parar e validar** com T009.

US1 sozinha não basta para o deploy do passo 1. A Architecture doc exige validação (US2) e o fechamento do SEC-03 (US4) no mesmo deploy, e o `nexus-ai` precisa de US3 para o retry.

### Entrega incremental (um PR, commits atômicos por fase)

1. Setup + Foundational: `test: add stream test helpers` e `feat: add stream outcome logging`.
2. US1, US2, US3 e US4, cada uma em commits próprios com Conventional Commits de até 50 caracteres (Principle VII).
3. Polish: privacidade, changelog e gates.

---

## Notes

- **[P]**: só arquivos diferentes e sem dependência pendente.
- **Fora destas tasks**: `nexus-ai`, socket, webchat, `whatsapp_broadcasts`, Mailroom, Courier, migration e o restante da spec 009.
- **Pin**: re-fixar o Architecture doc e os contratos na tag `arch-v1` quando o documento tagueado registrar a aprovação do `flows`. É uma tarefa de documentação fora deste PR de código.
