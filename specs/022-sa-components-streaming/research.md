# Research: componentes de streaming do Shopping Assistant em `POST /api/v2/internals/messages/stream`

**Feature**: `022-sa-components-streaming` | **Date**: 2026-11-24 | **Plan**: [plan.md](plan.md)

Este documento cobre só o que o `openapi.flows.yaml` e o `components-shared.schema.json` no pin `329a1db8c1f3f62208b052457e0e3bc9654ce102` não dizem. Formato de campo, códigos de status e corpos de erro vêm do contrato e da spec e não são rediscutidos aqui. CI-01, CI-02, L-01, L-02 e O-01 estão fechados pelo AD-004 e não são reabertos.

## R1. `403` em toda falha de JWT sem tocar no autenticador compartilhado

- **Decision**: `MsgStreamView` sobrescreve `get_authenticate_header()` e devolve `None`. `RequiredJWTAuthentication` e `JWTAuthMixinRequired` não mudam.
- **Rationale**: o DRF 3.15.1 (`APIView.handle_exception`) converte `AuthenticationFailed`/`NotAuthenticated` em `403` quando o primeiro autenticador não fornece `WWW-Authenticate`. Hoje o `BaseAuthentication.authenticate_header` já devolve `None`, então o endpoint já responde `403`. A sobrescrita na view torna o contrato explícito (Principle XV). Sem ela, uma mudança futura no autenticador compartilhado passaria este endpoint para `401` sem que ninguém perceba. O corpo continua `{"detail": "..."}`, como no exemplo do contrato.
- **Alternatives considered**: um autenticador específico para o endpoint, que duplicaria a decodificação do JWT; ou mudar o autenticador compartilhado, o que é proibido pela spec (FR-028) e mudaria outros endpoints.

## R2. Permissão de escopo de tenant e ordem de verificação

- **Decision**:
  - Nova permissão nomeada `ModuleJWTProjectScope`, em `temba/api/v2/internals/msgs/permissions.py`, declarada só em `MsgStreamView.permission_classes`.
  - `has_permission` deriva o projeto autorizado com `jwt_tenant_claims(request.jwt_payload)`:
    - com claim de projeto, ele é a autoridade; se também houver claim de canal, o canal precisa pertencer a esse projeto;
    - só com claim de canal, o projeto autorizado é o `org.proj_uuid` do canal ativo com esse UUID;
    - canal inexistente nega.
  - Comparação com o corpo:
    - `project_uuid` presente no corpo é normalizado com `uuid.UUID(...)` e comparado ao autorizado; se não for um UUID válido, ou for diferente, nega;
    - `project_uuid` ausente, ou corpo que não é objeto JSON, não decide aqui: o serializer devolve `400`.
  - Negar levanta `PermissionDenied`, ou seja, `403` com o `detail` padrão do DRF, que é o exemplo `forbiddenTenant` do contrato.
- **Rationale**: o DRF roda autenticação e permissão em `initial()`, antes de `post()`. Assim a comparação acontece antes de consultar a `Idempotency-Key` e antes de gravar (FR-029). A permissão não tem efeito colateral sobre o `request`. A view usa o `project_uuid` do corpo (já igual ao autorizado) para buscar o `Org` (`404` se não existir, FR-030) e como namespace da chave. A regra de canal só replica o contrato de `jwt_tenant_claims` (SEC-05), que hoje já é aplicado em `BaseAPIView._resolve_jwt_user`.
- **Alternatives considered**:
  - Checar na view, como `resolve_org_and_user_internal_whatsapp`: rejeitado porque a view continuaria sem permissão explícita e com `permission_classes = []` (Principle XVII).
  - Guardar o projeto autorizado no `request` dentro da permissão: rejeitado por ser efeito colateral escondido (Principle XV).

## R3. Tipos JSON estritos com DRF

- **Decision**: campos estritos locais em `serializers.py`, sem conversão:
  - `StrictCharField`: rejeita qualquer valor que não seja `str` e usa `trim_whitespace=False`.
  - `StrictIntegerField`: rejeita `bool` e `str` e aceita `int`, ou `float` com `is_integer()`.
  - `StrictChoiceField`: só aceita `str`.

  `null` é rejeitado por `allow_null=False`, que é o padrão.
- **Rationale**: no DRF 3.15.1, `CharField.to_internal_value` converte `int`/`float` em texto e, com `trim_whitespace=True` (o padrão), transforma `"   "` em vazio. Isso rejeitaria um texto que o contrato aceita (`minLength: 1` conta os caracteres como vieram). Já `IntegerField` aceita `"9"`. As duas coisas contrariam FR-008. O tipo `integer` do JSON Schema 2020-12 aceita números com parte fracionária zero (`9.0`), então o contrato também aceita. O valor é gravado como veio (FR-014).
- **Alternatives considered**:
  - Validar com `jsonschema` contra o schema compartilhado: rejeitado porque exigiria dependência nova (Principle II) e mapear os erros para o formato DRF sob `msg`. O formato `uri` ainda exigiria outra biblioteca.
  - Rejeitar `9.0`: rejeitado por ser mais estrito que o contrato.

## R4. `cta_message.url`: `format: uri` + `pattern: ^https?://.+` sem dependência nova

- **Decision**: o validador `validate_cta_url` exige, nesta ordem:
  1. `re.match(r"^https?://.+", value)` (constante `CTA_URL_PATTERN`), sensível a maiúsculas, como o padrão do contrato;
  2. sintaxe de URI da RFC 3986: só caracteres ASCII `unreserved`, `reserved` ou `%` seguido de dois dígitos hex, e `urllib.parse.urlsplit` sem erro.

  A mensagem de erro é `"Enter a valid http(s) URL."`, como no exemplo do contrato.
- **Rationale**: o contrato pede URI, não URL resolvível. O `URLValidator` do Django exige host com domínio ou IP válido e aceita esquema em maiúsculas, o que acrescentaria e removeria regras que o contrato não tem. Um caractere não ASCII não é URI (é IRI) e é rejeitado. Este é um risco registrado no plano: o `nexus-ai` precisa enviar a URL com percent-encoding.
- **Alternatives considered**: `serializers.URLField`, rejeitado pelos mesmos motivos do `URLValidator`; bibliotecas `rfc3986` ou `rfc3987`, que não estão no `poetry.lock` (Principle II).

## R5. Objetos fechados e formato do erro

- **Decision**:
  - Um `ClosedSerializer` base (subclasse de `serializers.Serializer`) sobrescreve `to_internal_value` e falha com `{"<chave>": ["Unexpected field."]}` para cada chave fora de `self.fields`, junto com os demais erros do objeto.
  - É usado em `ListMessageSerializer`, `ListItemSerializer`, `CtaMessageSerializer` e `HeaderSerializer`. `list_items` é um `ListField(child=ListItemSerializer(), allow_empty=False)`.
  - Exemplo do erro resultante: `{"msg": {"cta_message": {"foo": ["Unexpected field."]}}}`. Para item de lista, o índice entra no caminho (`{"msg": {"list_message": {"list_items": {"1": {"foo": [...]}}}}}`).
- **Rationale**: a spec (US2, cenários 15 a 18) exige que o erro aponte o caminho `msg.<objeto>.foo`. O exemplo `unknownComponentKey` do OpenAPI (`{"msg": {"cta_message": ["Unexpected field: foo."]}}`) é ilustrativo (FR-009; `ValidationErrorResponse` tem `additionalProperties: true`), e o formato aninhado também nomeia `foo`. `quick_replies` e `footer` não são objetos e não ganham regra além de FR-002 e FR-007.
- **Alternatives considered**: erro como lista no nível do objeto, como no exemplo do contrato. Rejeitado porque não traz o caminho do campo que a spec exige.

## R6. `Msg.metadata` igual ao enviado, com chaves de `msg` abertas

- **Decision**: `msg` passa de `DictField` para `StreamMsgField` (subclasse de `DictField`). `to_internal_value` faz três coisas:
  1. mantém a checagem de dicionário do `DictField`;
  2. para cada um dos seis campos presentes, valida com o campo ou serializer correspondente e acumula os erros por nome;
  3. sem erros, devolve o **dicionário original**, não o validado.

  Campos fora dos seis passam intactos. Componentes presentes com `null` falham com a mensagem padrão `"This field may not be null."`.
- **Rationale**: FR-014 exige gravar `msg` sem renomear, converter ou remover. Um `Serializer` aninhado descartaria as chaves de `msg` fora dos seis (FR-010) e devolveria valores convertidos. A view continua passando `metadata=msg_data` para `create_message_db_only`, que não muda.
- **Alternatives considered**: `MsgSerializer` com `to_representation` reconstruindo o dict, que é frágil e exige manter duas listas de campos; copiar `WhatsappBroadcastWriteSerializer`, proibido pelo pedido e de formato diferente.

## R7. Armazenamento de idempotência

- **Decision**: novo módulo `temba/api/v2/internals/msgs/idempotency.py`, no estilo do de broadcasts, que não muda:
  - **Chave Redis**: `idempotency:messages_stream:{project_uuid}:{key}` (`REDIS_KEY_PREFIX`), com `project_uuid` normalizado. Não colide com `idempotency:whatsapp_broadcasts:*` (FR-019).
  - **Cliente**: um cliente `redis.Redis.from_url(settings.CACHES["default"]["LOCATION"], socket_timeout=…, socket_connect_timeout=…)` criado sob demanda e reaproveitado pelo processo (pool de conexões, não estado de aplicação). Constante `REDIS_TIMEOUT_SECONDS = 2`.
  - **Validade**:
    - `DONE_TTL_SECONDS = 86400` (24h, FR-020) para o registro concluído;
    - `INFLIGHT_TTL_SECONDS = 120` para a reserva em processamento, igual ao `timeout = 120` de `docker/gunicorn/gunicorn.conf.py`.
  - **Extração da chave**: `strip()`. Se o resultado for vazio, ou tiver mais de 128 caracteres (`MAX_KEY_LENGTH`), vale como ausente (FR-025).
  - **Impressão do corpo**: reutiliza, por import, `compute_body_hash` de `temba/api/v2/internals/broadcasts/idempotency.py`. A função é SHA-256 de `request.data` com `sort_keys=True` (FR-021).
  - **Valor guardado**:
    - reserva: `{"state": "inflight", "body_hash": …}` com `SET NX EX`;
    - conclusão: `{"state": "done", "body_hash": …, "ids": […]}` com `SET EX 86400`;
    - replay: devolve `200 {"ids": […]}`. O status do replay é sempre `200`, enquanto a referência repete o status original.
  - **Liberação**: `DEL` só no caminho da requisição dona da reserva (FR-024). O `409` devolvido ao duplicado não escreve nada.
- **Rationale**:
  - **Cliente próprio**: o `CACHES` de `settings_common.py` e de `settings.py.prod` não define `SOCKET_TIMEOUT`, e o redis-py 3.5.3 bloqueia sem limite por padrão (Principle X). Um cliente próprio dá timeout explícito sem mexer em configuração global. `2s` fica muito acima da latência típica de um `SET`/`GET` e bem abaixo do timeout do worker.
  - **Reserva de 120s**: a referência guarda a reserva por 24h. Se o Redis falhar entre a reserva e a liberação, a chave ficaria presa em `idempotency_in_progress` por 24h, e o retry do `nexus-ai` se esgotaria sem registrar a mensagem. Uma requisição não vive mais que o timeout do worker, então uma reserva mais velha que isso pertence a uma requisição morta. Com ela no banco em transação (R8), nada fica gravado.
  - **Módulo de broadcasts**: as funções dele montam a chave com o prefixo de broadcasts e usam limite 200, por isso só a impressão do corpo é reaproveitada.
- **Alternatives considered**:
  - Chamar as funções de broadcasts com outro `project_uuid` (por exemplo, prefixado): é um truque que mistura os namespaces (Principle XV).
  - Parametrizar o módulo de broadcasts: proibido (FR-027).
  - Configurar `SOCKET_TIMEOUT` global: fora do escopo de arquivos e mudaria todo o uso de cache.
  - Reserva de 24h, como na referência: rejeitada pelo motivo acima.

## R8. Atomicidade e falha do Redis

- **Decision**:
  - **Com chave válida**: a criação das linhas e o `store_success` rodam dentro de `transaction.atomic()`. Se o `store_success` falhar, a transação é desfeita.
  - **Qualquer exceção depois da reserva**: `release` best-effort, que captura e registra `RedisError`. Depois disso:
    - `ValueError` de `create_message_db_only` mantém o `400 {"error": …}` de hoje;
    - `RedisError` (em qualquer etapa, inclusive na reserva) devolve `503 {"error": "Service temporarily unavailable"}` (constante `SERVICE_UNAVAILABLE_ERROR`), sem detalhe interno;
    - qualquer outra exceção é relançada e vira `500`.
  - **Sem chave**: o caminho atual fica igual, sem `atomic`.
- **Rationale**:
  - FR-026 proíbe gravar sem deduplicação. Uma falha no `store_success` depois das linhas criadas deixaria linhas sem chave, e o retry duplicaria.
  - O `503` é um `5xx`, e o `nexus-ai` repete `5xx` (Assumptions). O contrato não lista `5xx`, e a spec só pede "erro de servidor sem detalhe interno".
  - Sem chave, o `atomic` mudaria o resultado de hoje numa chamada com várias URNs em que uma falha depois de outra já criada (hoje a primeira linha fica). Isso violaria FR-016.
- **Alternatives considered**:
  - Gravar a conclusão depois do commit: rejeitado porque, se o Redis falhar ali, a chave fica em processamento com linhas já criadas.
  - `atomic` sempre: rejeitado por FR-016.
  - `500` para Redis indisponível: aceitável, mas o `503` comunica melhor que o problema é transitório.

## R9. Ordem do processamento em `MsgStreamView.post`

- **Decision**:
  1. **DRF `initial()`**: `RequiredJWTAuthentication` e depois `ModuleJWTProjectScope`; qualquer falha devolve `403`.
  2. **Contexto de observabilidade**: `X-Correlation-ID`, tags e filtro do Sentry (R10, R11).
  3. **Chave**: se houver chave válida e o `project_uuid` do corpo for UUID, calcula a impressão do corpo e faz a reserva:
     - registro concluído com a mesma impressão: `200` com os ids;
     - registro concluído com outra impressão: `409` `idempotency_conflict`;
     - reserva em processamento: `409` `idempotency_in_progress`;
     - erro do Redis: `503`.
  4. **Serializer**: se inválido, devolve `400` e libera a chave.
  5. **`Org`**: se não existir, devolve `404 {"error": "Project not found"}` e libera a chave.
  6. **Criação**: como em R8; devolve `201 {"ids": […]}`.
- **Rationale**: é a ordem da referência (reserva antes da validação). Por isso um corpo diferente com a mesma chave recebe `409` mesmo quando também é inválido (FR-022), e o `400` libera a chave (FR-024, US2 cenário 14). A comparação de tenant vem antes da reserva (FR-029, US4 cenário 8). Com `project_uuid` ausente ou inválido não há namespace confiável, então a reserva é pulada e o serializer devolve `400`.
- **Alternatives considered**: validar antes de reservar. Rejeitado porque um corpo diferente e inválido receberia `400` em vez de `409`, o que contraria FR-022.

## R10. Privacidade em logs e Sentry só neste endpoint

- **Decision**: no início de `post()`, adicionar ao scope da requisição atual (`sentry_sdk.configure_scope()`) um event processor `scrub_stream_event`, em `msgs/observability.py`. Ele remove três coisas dos eventos:
  - `event["request"]["data"]`;
  - as `vars` de todos os frames de `exception.values[].stacktrace` e de `threads`;
  - o `data` dos breadcrumbs de categoria `query`.

  Os logs do endpoint só levam identificadores opacos, o `outcome` com os valores enumerados no FR-036 e um `reason` opcional (`idempotency_conflict`, `idempotency_in_progress`, `dedupe_unavailable`, `unexpected`). Nenhum log recebe `request.data`, `msg` ou mensagens de erro de validação. Falhas de autenticação e de permissão acontecem antes de `post()` e são registradas numa sobrescrita de `handle_exception` na view, com `rejected_auth` para `AuthenticationFailed` e `rejected_tenant` para `PermissionDenied`.
- **Rationale**:
  - O sentry-sdk 1.45.1 com `DjangoIntegration` anexa o corpo JSON (`max_request_body_size="medium"`) e, com `include_local_variables` (o padrão) e `send_default_pii=True`, também as variáveis locais e os parâmetros SQL (o `INSERT` em `msgs_msg` leva `text` e `metadata`).
  - O middleware WSGI do SDK clona o hub por requisição, então um processor adicionado na view vale só para esta requisição. Ele roda depois do processor de request do Django, que foi adicionado antes da view, e antes do `before_send` global.
  - O `TODO(SENTRY_PII)` global continua fora de escopo.
  - Um teste com transporte de Sentry capturado comprova o comportamento (SC-006). Se o comportamento real do SDK diferir, o teste falha.
- **Alternatives considered**: `before_send` global filtrando por rota, que muda `settings_common.py` (fora do escopo de arquivos); `max_request_body_size="never"` global, que afeta todos os endpoints.

## R11. `X-Correlation-ID` e identificadores do Sentry

- **Decision**:
  - `X-Correlation-ID` é usado como veio, sem `strip`, se tiver de 1 a 128 caracteres (`MAX_CORRELATION_ID_LENGTH`). Nesse caso vira a tag de Sentry `correlation_id` e o campo `correlation_id` nos logs. Fora disso é ignorado, sem rejeitar a requisição.
  - Tags fixas: `project_uuid` (do corpo, depois da permissão), `channel_uuid` quando presente e `caller: module_jwt`.
  - Tags `account_id` e `user_id` com valor `none`, para deixar explícito que o JWT de módulo não traz conta nem usuário (FR-035, Principle XIII).
- **Rationale**: FR-034 e FR-035. `strip` mudaria o identificador opaco.
- **Alternatives considered**: gerar um correlation id quando ausente. Rejeitado porque a spec não pede isso e o identificador pertence ao `nexus-ai`.

## R12. Estratégia de teste

- **Decision**:
  - **US4 com JWT real**: gerar um par RSA de teste com `cryptography` (já dependência), aplicar `override_settings(JWT_PUBLIC_KEY=<pública>)` e assinar com `jwt.encode(..., algorithm="RS256")`. Sem substituir `authentication_classes` nem `permission_classes`.
  - **Testes atuais de stream**: mantidos como estão (substituem autenticação e permissão) para provar FR-016.
  - **Sem Mailroom e sem Courier**: `patch` de `temba.mailroom.queue._queue_task`, `_queue_batch_task` e `_queue_handler_task` com `assert_not_called` (cenário 11 da US1).
  - **Idempotência**: Redis de teste (DB 10) com limpeza das chaves do prefixo em `setUp`/`tearDown`. Em processamento: gravar uma reserva direto no Redis antes da chamada. Expiração: `ttl` da chave e chamada após `DEL` simulado. Falha do Redis: `patch` do cliente com `side_effect=redis.exceptions.ConnectionError`.
  - **Privacidade**: capturar eventos com um `sentry_sdk.init` de teste de transporte em memória dentro do teste e logs com `assertLogs`.
- **Rationale**: Principle XIV e Test Strategy da spec.

## R13. Peak Load

- **Decision**: o repositório não tem métricas de produção. O plano registra a fórmula da spec:

  > **pico de `POST /api/v2/internals/messages/stream` do Shopping Assistant** + **pico das respostas com componentes do Shopping Assistant que hoje passam por `/api/v2/internals/whatsapp_broadcasts` em canais com streaming**, no mesmo horário de pico.

  O valor numérico fica como medição pendente, a registrar no `plan.md` antes do passo 1 de deploy. O acréscimo por requisição está em [data-model.md](data-model.md): uma validação em memória e até 4 operações Redis (`SET NX`, `GET`, `SET`, `DEL`).
- **Alternatives considered**: estimar um número. Rejeitado porque seria inventado.

## R14. Changelog

- **Decision**: entrada em `WENI-CHANGELOG.md` sob a próxima versão, quando ela for cortada, no formato do arquivo:
  - `* feat: validate Shopping Assistant components and support Idempotency-Key on internal messages stream endpoint`
  - `* fix: security — scope internal messages stream to the module JWT project and declare an explicit permission (SEC-03)`

  Sem locale novo.
- **Rationale**: Principle VIII e exceção de formato do changelog.
