# Engineering Spec: componentes de streaming do Shopping Assistant em `POST /api/v2/internals/messages/stream` (fatia Flows)

**Feature Branch**: `022-sa-components-streaming` (diretório da spec; nenhuma branch foi criada por este comando)

**Created**: 2026-11-23

**Status**: Draft

**Cycle**: SDD Full (`specify` → `plan` → `tasks` → `analyze` → `implement`). O contrato HTTP interno em `temba/api` muda (Principle IV). SDD Lite não se aplica.

**Input**: engineering spec da fatia Flows da feature `019-sa-components-streaming`: validar componentes (`quick_replies`, `list_message`, `cta_message`, `interaction_type`, `header`, `footer`) em `msg`, aceitar `Idempotency-Key` para retry do `nexus-ai`, gravar só no banco e garantir JWT com escopo de tenant.

## Inheritance from Product Spec

- Product Spec: Streaming de componentes no Shopping Assistant (quick reply, lista e CTA) — https://github.com/weni-ai/vtex-cx-experience-specs/blob/e0f8e7ec9b5645681534645dc182a070b2d38e15/specs/019-sa-components-streaming/spec.md
- Pinned version: `019-sa-components-streaming-v1` (commit `e0f8e7ec9b5645681534645dc182a070b2d38e15`)
- Architecture doc: https://github.com/weni-ai/vtex-cx-experience-specs/blob/329a1db8c1f3f62208b052457e0e3bc9654ce102/specs/019-sa-components-streaming/architecture.md — commit `329a1db8c1f3f62208b052457e0e3bc9654ce102` ("Resolve flows contract inconsistencies in the 019 architecture document", emenda de 2026-11-23; cópia local idêntica em `task-spec.md`). O pin anterior, `fe00c1c`, está obsoleto. A aprovação do tech lead do `flows` (Lucas Linhares) está **pendente**. A tag `019-sa-components-streaming/arch-v1` já existe no remoto e aponta para o merge `148d5ee704f49fb3cf47df26df20d3ac124cd3b8`, com o mesmo conteúdo, mas o documento nessa tag ainda diz `Status: Draft` e `flows` `pending`. Por isso esta spec ainda não se fixa na tag. Quando a aprovação constar no documento tagueado, este campo MUST ser re-fixado na tag.
- Inherited binding decisions: BD-004, BD-006, BD-009 e BD-010 (Product Spec); AD-004 e a parte `flows` de AD-006 (Architecture doc).
- Scope of this spec: linha `engineering/flows` (`flows`) do Impact Map — validar `msg.quick_replies`, `msg.list_message`, `msg.cta_message`, `msg.interaction_type`, `msg.header` e `msg.footer` em `POST /api/v2/internals/messages/stream`, suportar `Idempotency-Key` para retry limitado do `nexus-ai` e gravar os metadados estruturados em `Msg.metadata` via `create_message_db_only`, sem Mailroom e sem Courier.
- Divergences: none

### Como esta fatia honra o que herda

| Origem | O que diz (resumo, sem redefinir) | Onde esta spec implementa |
|---|---|---|
| BD-004 | O CTA só entra com o link completo. | FR-005: `cta_message.url` precisa ser URL `http(s)` absoluta, conforme o OpenAPI. Tempo de espera e esqueleto não são do `flows`. |
| BD-006 | Uma resposta pode ter mais de um tipo de componente. | FR-013: qualquer combinação de `list_message`, `cta_message` e `quick_replies` na mesma `msg`. |
| BD-009 | Só quick reply, lista e CTA mudam; WhatsApp, catálogo, carrossel, mídia e pedido continuam como hoje. | Fora de escopo explícito; `/api/v2/internals/whatsapp_broadcasts` não é tocado. |
| BD-010 | Sem configuração para o merchant; vale para todos os canais de Shopping Assistant. | Nenhuma flag ou configuração nova no `flows`; a validação vale para toda chamada ao endpoint. |
| AD-004 (com as regras 1 a 4 de 2026-11-23) | Validar os seis campos em `msg` conforme o OpenAPI (`400`), com `list_message`, `list_items[]`, `cta_message` e `msg.header` fechados; campos de topo inalterados; aceitar `msg.text` vazio com componente válido; `Idempotency-Key` (`200` replay, `409` com `code` `idempotency_conflict` ou `idempotency_in_progress`, chave inválida tratada como ausente); `403` para toda falha de JWT ou de escopo. | US1 a US4, FR-001 a FR-028. |
| AD-006 (parte `flows`) | `flows.msg` aceita qualquer combinação de componentes; `item_count` é inteiro positivo opcional. | FR-004, FR-013, FR-014. |
| Cross-Cutting Conventions | Modelo de erro (`400` sob `msg`, inclusive chave não declarada; `403` com `detail` em qualquer falha de JWT ou de escopo, sem `401`; `404`; `409` com `code` e `error`), Bearer module JWT com escopo de `project_uuid`, idempotência de 24h com chave de 1 a 128 caracteres, `X-Correlation-ID` opaco, nunca logar texto, rótulos ou URL. | FR-009, FR-010, FR-018 a FR-036. |
| FR-028, FR-019/FR-038, FR-034 (Product Spec) | Resposta sem texto; quantidade da lista só quando conhecida; respostas antigas continuam como hoje. | FR-012, FR-014, FR-016. |

### Contratos lidos (mesmo pin do Architecture doc)

- `contracts/openapi.flows.yaml` versão `1.1.0` — https://github.com/weni-ai/vtex-cx-experience-specs/blob/329a1db8c1f3f62208b052457e0e3bc9654ce102/specs/019-sa-components-streaming/contracts/openapi.flows.yaml
- `contracts/components-shared.schema.json` versão `1.0.0` — https://github.com/weni-ai/vtex-cx-experience-specs/blob/329a1db8c1f3f62208b052457e0e3bc9654ce102/specs/019-sa-components-streaming/contracts/components-shared.schema.json

O `openapi.flows.yaml` emendado define `quick_replies`, `list_message` e `cta_message` por `$ref` ao `components-shared.schema.json`, que não mudou desde `fe00c1c`. O formato de cada campo nesta spec vem desses dois arquivos no pin acima, e não do exemplo de WhatsApp em `temba/api/v2/views.py`. O texto de `fe00c1c` não é mais o contrato vigente.

## Resoluções de contrato (AD-004, 2026-11-23)

As cinco inconsistências da versão anterior foram resolvidas pelo autor do Architecture doc nas regras 1 a 4 do AD-004 (Amendment Log, segunda linha). As resoluções são binding, e Divergences continua `none`.

- **CI-01 → rejeitar** (AD-004 regra 1). Uma chave não declarada em `list_message`, em cada item de `list_items`, em `cta_message` ou em `msg.header` recebe `400`. As chaves no nível de `msg` continuam abertas (FR-010).
- **CI-02 → sem mudança** (AD-004 regra 2). `urns: []` com `contact_uuid` continua válido, e `minItems: 1` não é adotado. Os campos de topo ficam fora do escopo desta spec por decisão do AD-004.
- **L-01 → `409` com `code`** (AD-004 regra 3). `idempotency_conflict` é final, e `idempotency_in_progress` é transitório (FR-022, FR-023).
- **L-02 → chave inválida tratada como ausente** (AD-004 regra 3). Uma chave vazia após remover os espaços nas pontas, ou com mais de 128 caracteres, desativa a deduplicação e não gera `400` (FR-025).
- **O-01 → `403` para toda falha** (AD-004 regra 4). Toda falha de JWT ou de escopo de projeto devolve `403` com `detail`, e o endpoint não devolve `401` (FR-028).

## Escopo neste repositório

**Dentro:**

- `POST /api/v2/internals/messages/stream` (`MsgStreamView`, `MsgStreamSerializer`) em `temba/api/v2/internals/msgs/`.
- Validação dos seis campos opcionais de `msg` (FR-001 a FR-011).
- Gravação DB-only em `Msg.metadata` (FR-012 a FR-017).
- `Idempotency-Key` (FR-018 a FR-027).
- JWT com escopo de tenant neste endpoint, incluindo o que falta do SEC-03 (FR-028 a FR-032).
- Privacidade em logs e Sentry deste endpoint e `X-Correlation-ID` (FR-033 a FR-036).

**Fora de escopo:**

- `nexus-ai`, `weni-webchat-socket`, `webchat-service`, `webchat-react`.
- gRPC, WebSocket, Redis Pub/Sub de stream, MongoDB.
- `/api/v2/internals/whatsapp_broadcasts` e o módulo `temba/api/v2/internals/broadcasts/idempotency.py`, que não pode ser alterado.
- `catalog_message`, mídia, pedido, carrossel e o pipeline `2.6`.
- Courier e Mailroom: nenhuma mudança e nenhuma versão mínima nova.
- O resto da spec `009-endpoint-authz-tenant-fixes`. A classe compartilhada `JWTAuthMixinRequired`, o autenticador JWT compartilhado e os outros endpoints continuam como estão.
- Os TODOs globais da constitution `TODO(SENTRY_PII)` e `TODO(DRF_PERMISSIONS)`.
- A validação dos campos de topo do corpo, por decisão do AD-004 regra 2 (`urns: []` com `contact_uuid` continua válido), e a de `msg.text`, `msg.attachments` e `msg.template`. Todos mantêm o tratamento de hoje.
- Migrations: nenhuma. `Msg.metadata` já existe.

## Estado atual

Observado em `main` @ `1b1507341`, em 2026-11-23.

- `MsgStreamSerializer` declara `msg = DictField(required=False)`. Nenhum campo de componente é validado, e o objeto é gravado como chegou em `Msg.metadata`.
- `MsgStreamView(JWTAuthMixinRequired, APIViewMixin, APIView)`:
  - Usa `RequiredJWTAuthentication`.
  - Herda `permission_classes = []` do mixin, o que conflita com a Principle XVII.
  - Lê `project_uuid` do corpo e busca o `Org` sem comparar com o claim do token.
  - Responde `201 {"ids": [...]}` e `404 {"error": "Project not found"}`.
- O `Msg.text` vem do primeiro valor preenchido entre `text`, `message` e `msg.text`, ou fica `""`. A regra de conteúdo mínimo aceita qualquer `msg` não vazia.
- `create_message_db_only` (`services.py`) cria só a linha em `msgs_msg`. Não chama Mailroom nem Courier. Cria uma linha por URN.
- **SEC-03** (`specs/009-endpoint-authz-tenant-fixes`):
  - A correção da ordem do mixin entrou no commit `93bc2f94f`. Uma chamada anônima hoje é rejeitada, com `403`.
  - Faltam três coisas: nenhum teste exercita a chamada anônima, porque todos os testes de stream substituem autenticação e permissão por `[]`; o `project_uuid` do corpo pode divergir do claim do token sem rejeição; e não há permissão explícita.
  - Esta spec inclui esse enforcement (US4) sem reabrir os outros itens da 009.
- Sentry: `DjangoIntegration` (sentry-sdk 1.45) anexa por padrão o corpo JSON da requisição aos eventos, e `send_default_pii=True` está ativo. Sem cuidado, um erro neste endpoint enviaria `text`, rótulos e `url` ao Sentry.
- Referência de idempotência (`broadcasts/idempotency.py`):
  - Comportamento: escopo por `(project_uuid, chave)`, retenção de 24h, replay com o mesmo corpo, `409` para corpo diferente ou em andamento, liberação da chave em qualquer caminho sem sucesso, e chave vazia ou longa demais tratada como ausente.
  - O prefixo Redis está fixo em `whatsapp_broadcasts` e o limite é 200. Por isso o módulo não pode ser usado como está sem dividir o espaço de chaves com outro endpoint e sem contrariar o limite de 128 do contrato.

## User Scenarios & Testing *(mandatory)*

Os atores são o `nexus-ai`, que chama o endpoint com Bearer module JWT, e o `flows`, que grava. Cada história se testa sozinha, por chamada HTTP ao endpoint e verificação da linha em `msgs_msg`.

### User Story 1 - Registrar uma resposta do Shopping Assistant com componentes, sem envio (Priority: P1)

Depois de terminar uma resposta em streaming, o `nexus-ai` registra no `flows` o texto e os componentes da resposta. O `flows` grava o registro só no banco, com os componentes em `Msg.metadata`, e não dispara nenhum envio.

**Why this priority**: sem isso, o `nexus-ai` não pode deixar de usar `/whatsapp_broadcasts` no Shopping Assistant (AD-003), e o histórico do `flows` perde os componentes das respostas em streaming.

**Independent Test**: com um token autorizado para o projeto P e um contato com URN no projeto, enviar cada exemplo do OpenAPI (`quickReplies`, `listAndCtaMultiComponent`, `textlessComponent`) e conferir o `201`, a linha criada, o `Msg.metadata` igual ao `msg` enviado e a ausência de qualquer envio para Mailroom ou Courier.

**Acceptance Scenarios**:

1. **Given** um token autorizado para P e um contato de P, **When** o `nexus-ai` envia `msg.text` com `msg.quick_replies` de 3 rótulos, **Then** a resposta é `201 {"ids": [id]}`, existe uma linha em `msgs_msg` com `text` igual a `msg.text`, e `metadata.quick_replies` contém os 3 rótulos na mesma ordem.
2. **Given** o mesmo contexto, **When** o corpo traz `msg.list_message` com `button_text`, `item_count: 9` e `list_items`, **Then** a linha é criada e `metadata.list_message.item_count` é `9`.
3. **Given** uma lista sem `item_count`, **When** ela é registrada, **Then** `metadata.list_message` não tem `item_count`, e o `flows` não o calcula a partir de `list_items`.
4. **Given** `msg.cta_message` com `display_text` e `url` `https://` completa, **When** registrado, **Then** a linha é criada com `metadata.cta_message` igual ao enviado.
5. **Given** `msg.text: ""` e `msg.quick_replies` válido (exemplo `textlessComponent`), **When** registrado, **Then** a resposta é `201`, `Msg.text` é `""` e `metadata.quick_replies` está presente.
6. **Given** `msg` com `interaction_type: "list"`, `list_message` e `cta_message` (exemplo `listAndCtaMultiComponent`), **When** registrado, **Then** a resposta é `201` e os dois componentes estão em `metadata`.
7. **Given** `msg` com `quick_replies`, `list_message` e `cta_message` ao mesmo tempo, **When** registrado, **Then** a resposta é `201` e os três estão em `metadata`.
8. **Given** `msg.header` `{"type": "text", "text": "..."}` e `msg.footer`, **When** registrado, **Then** os dois estão em `metadata`.
9. **Given** um corpo no formato de hoje, sem nenhum dos seis campos, **When** enviado, **Then** o resultado (status, corpo, linhas e `metadata`) é o mesmo de hoje.
10. **Given** `urns` com 2 URNs e componentes válidos, **When** registrado, **Then** a resposta é `201` com 2 ids, e cada linha tem os mesmos componentes em `metadata`.
11. **Given** qualquer cenário acima, **When** a linha é criada, **Then** nenhuma mensagem é enfileirada para Mailroom e nenhuma chamada a Courier acontece.

---

### User Story 2 - Rejeitar componente malformado sem criar registro (Priority: P2)

Quando o `nexus-ai` envia um componente fora do contrato, o `flows` responde `400`, com o erro sob a chave `msg` apontando o campo, e não grava nada.

**Why this priority**: é a fronteira de validação da Principle IX. Sem ela, URLs incompletas ou estruturas inválidas entram em `Msg.metadata` (AD-004).

**Independent Test**: enviar cada payload inválido da matriz abaixo com um token autorizado e conferir o `400`, o caminho do campo dentro de `msg` no corpo da resposta e a contagem de linhas em `msgs_msg` inalterada.

**Acceptance Scenarios**:

Em todos os cenários, exceto o 19: a resposta é `400`, o corpo tem a chave `msg` com o caminho do campo inválido, e nenhuma linha é criada.

1. **Given** `quick_replies: []`, **When** enviado, **Then** o erro aponta `msg.quick_replies`.
2. **Given** `quick_replies` com um rótulo `""`, ou com um item que não é texto (número, objeto, `null`), **When** enviado, **Then** o erro aponta o item.
3. **Given** `list_message` sem `button_text` ou com `button_text: ""`, **When** enviado, **Then** o erro aponta `msg.list_message.button_text`.
4. **Given** `list_message` sem `list_items`, ou com `list_items: []`, **When** enviado, **Then** o erro aponta `msg.list_message.list_items`.
5. **Given** um item de `list_items` sem `uuid` ou sem `title`, ou com um deles vazio, **When** enviado, **Then** o erro aponta o item.
6. **Given** `item_count` igual a `0`, `-1`, `1.5`, `"9"` ou `true`, **When** enviado, **Then** o erro aponta `msg.list_message.item_count`.
7. **Given** `cta_message` sem `url`, com `url` sem esquema (`loja.example/x`), com esquema diferente de `http`/`https` (`ftp://…`, `javascript:…`), só com o esquema (`https://`) ou com caracteres que não formam um URI, **When** enviado, **Then** o erro aponta `msg.cta_message.url`.
8. **Given** `cta_message` sem `display_text` ou com `display_text: ""`, **When** enviado, **Then** o erro aponta `msg.cta_message.display_text`.
9. **Given** `interaction_type: "button"`, **When** enviado, **Then** o erro aponta `msg.interaction_type`.
10. **Given** `header.type: "image"`, ou um `header` que não é objeto, ou um `footer` que não é texto, **When** enviado, **Then** o erro aponta o campo.
11. **Given** um componente com valor `null` (por exemplo `cta_message: null`), **When** enviado, **Then** o erro aponta o componente.
12. **Given** `list_message` válida e `cta_message` inválido na mesma `msg`, **When** enviado, **Then** a requisição inteira é rejeitada e nenhum componente é gravado.
13. **Given** `urns` com 2 URNs e um componente inválido, **When** enviado, **Then** nenhuma das 2 linhas é criada.
14. **Given** um payload inválido com `Idempotency-Key: K`, **When** o `nexus-ai` reenvia o corpo corrigido com a mesma `K`, **Then** a resposta é `201` (o `400` não consumiu a chave).
15. **Given** uma `list_message` válida com uma chave extra (`"foo": "x"`), **When** enviado, **Then** o erro aponta `msg.list_message.foo`.
16. **Given** um item de `list_items` válido com uma chave extra (`"foo": "x"`), **When** enviado, **Then** o erro aponta `foo` dentro desse item, em `msg.list_message.list_items`.
17. **Given** um `cta_message` válido com uma chave extra (`"foo": "x"`), **When** enviado, **Then** o erro aponta `msg.cta_message.foo`.
18. **Given** um `msg.header` válido com uma chave extra (`"foo": "x"`), **When** enviado, **Then** o erro aponta `msg.header.foo`.
19. **Given** uma `msg` com componentes válidos e uma chave extra no nível de `msg` que não é um dos seis campos (`"foo": "x"`), **When** enviado, **Then** a resposta é `201`, e `metadata.foo` é gravado como hoje.

---

### User Story 3 - Deduplicar retry do `nexus-ai` com `Idempotency-Key` (Priority: P3)

O `nexus-ai` reenvia o registro após timeout, `5xx` ou `429` (AD-004, Principle XI). Com a mesma chave, o `flows` não cria registro duplicado.

**Why this priority**: o retry só é seguro com deduplicação. Sem a chave, o comportamento atual continua, então a história pode ser entregue depois de US1 e US2.

**Independent Test**: enviar o mesmo corpo duas vezes com a mesma chave e conferir `201` e depois `200` com os mesmos ids e uma linha só; depois enviar outro corpo com a mesma chave e conferir `409`.

**Acceptance Scenarios**:

1. **Given** nenhuma requisição anterior com a chave K no projeto P, **When** o `nexus-ai` envia o corpo B com `Idempotency-Key: K`, **Then** a resposta é `201 {"ids": X}`.
2. **Given** o cenário 1, **When** o `nexus-ai` reenvia B com K, mesmo com as chaves JSON em outra ordem, **Then** a resposta é `200 {"ids": X}` e nenhuma linha nova é criada.
3. **Given** o cenário 1, **When** o `nexus-ai` envia um corpo B' diferente com K, **Then** a resposta é `409 {"code": "idempotency_conflict", "error": "..."}`, nenhuma linha é criada e o registro de K continua devolvendo `200 {"ids": X}` para B.
4. **Given** nenhum header `Idempotency-Key`, **When** o mesmo corpo é enviado duas vezes, **Then** as duas respostas são `201` com ids diferentes, como hoje.
5. **Given** K já usada no projeto P, **When** um token do projeto P2 envia um corpo com K, **Then** a resposta é `201` em P2, e P não é afetado.
6. **Given** K já usada em `/api/v2/internals/whatsapp_broadcasts` no projeto P, **When** este endpoint recebe K em P, **Then** a requisição é tratada como nova, e o estado de idempotência de broadcasts não muda.
7. **Given** uma requisição com K ainda em processamento, **When** chega outra com K, **Then** a resposta à segunda é `409 {"code": "idempotency_in_progress", "error": "..."}`, nenhuma linha extra é criada e a primeira requisição conclui e registra K normalmente.
8. **Given** K usada há mais tempo que a retenção (no mínimo 24h), **When** B é reenviado com K, **Then** ele é tratado como novo (`201`).
9. **Given** `Idempotency-Key` vazia, só com espaços ou com mais de 128 caracteres, **When** enviado, **Then** a requisição segue como se o header não existisse (`201`, sem deduplicação e sem `400`).
10. **Given** uma primeira tentativa com K que terminou em `400`, `403`, `404` ou erro de servidor, **When** o `nexus-ai` reenvia com K, **Then** a requisição é processada normalmente.
11. **Given** o armazenamento de deduplicação indisponível e o header presente, **When** a requisição chega, **Then** nenhuma linha é criada e a resposta é um erro de servidor sem detalhe interno, para que o retry limitado do `nexus-ai` tente de novo.

---

### User Story 4 - JWT de módulo e escopo de tenant (Priority: P4)

Só o `nexus-ai`, com Bearer module JWT válido, grava no projeto que o token autoriza. O corpo não escolhe outro projeto.

**Why this priority**: fecha o que resta do SEC-03 e é o pré-requisito do passo 1 de deploy do Architecture doc (*Risks*). Fica em P4 porque a rejeição de chamada anônima já funciona hoje; o que falta é a comparação com o claim, a permissão explícita e os testes.

**Independent Test**: chamar o endpoint sem token, com token inválido, com token de outro projeto e com token de projeto inexistente, sem substituir autenticação e permissão no teste. Conferir status, corpo e ausência de linha em cada caso.

**Acceptance Scenarios**:

1. **Given** nenhuma credencial, **When** um corpo válido é enviado, **Then** a resposta é `403` com `detail`, nenhuma linha é criada e nenhuma chave de idempotência é registrada.
2. **Given** um token com assinatura inválida, expirado ou sem claim de tenant, **When** enviado, **Then** a resposta é `403` com `detail`, nunca `401`.
3. **Given** um token autorizado para P1 e o corpo com `project_uuid` de P2, que existe, **When** enviado, **Then** a resposta é `403` com `detail` e nenhuma linha é criada em P1 nem em P2.
4. **Given** um token que só tem claim de canal, de um canal de P1, e o corpo com `project_uuid` de P2, **When** enviado, **Then** a resposta é `403`.
5. **Given** um token para P e o corpo com `project_uuid` P, sem projeto P no `flows`, **When** enviado, **Then** a resposta é `404 {"error": "Project not found"}`.
6. **Given** um token para P e o corpo com P, **When** enviado, **Then** a resposta é `201` (controle).
7. **Given** um token para P e `channel_uuid` de um canal de outro projeto, **When** enviado, **Then** a resposta é `400` com o erro de canal de hoje e nenhuma linha é criada.
8. **Given** um token para P1, o corpo com P2 e `Idempotency-Key: K`, **When** enviado, **Then** a resposta é `403`, sem `200` nem `409`, e K não é registrada em nenhum projeto.

### Edge Cases

- `msg` ausente ou sem nenhum dos seis campos: comportamento de hoje (FR-016).
- `msg.text` vazio sem nenhum componente: segue a regra de conteúdo mínimo de hoje. Esta spec não cria rejeição nova.
- Campos não previstos no nível de `msg`, fora dos seis (por exemplo `template`): aceitos e gravados como hoje.
- Campos não previstos dentro de `list_message`, de um item de `list_items`, de `cta_message` ou de `msg.header`: `400` sob `msg`, no caminho do campo (FR-010, AD-004 regra 1). `quick_replies` e `footer` seguem só as próprias regras de tipo (FR-002, FR-007).
- `interaction_type` sem o componente correspondente (por exemplo `cta_url` sem `cta_message`): o OpenAPI não define regra cruzada, então só o valor é validado.
- Esquema da URL em maiúsculas (`HTTPS://…`): o padrão do contrato (`^https?://.+`) diferencia maiúsculas, então a URL é rejeitada.
- Muitos `quick_replies`, muitos `list_items`, rótulos longos e corpo grande: o contrato não define limite, e esta spec não cria nenhum (FR-011).
- Replay após a linha original ter sido apagada: devolve os ids originais. A chave guarda a resposta, não reconsulta o banco.
- Replay com o mesmo corpo e outro `X-Correlation-ID`: como o header não faz parte do corpo, é replay (`200`).
- `X-Correlation-ID` vazio ou com mais de 128 caracteres: é ignorado, e a requisição não é rejeitada (FR-034).
- Header `Idempotency-Key` repetido ou com espaços nas pontas: as pontas são removidas, como na referência. Se sobrar vazio, vale como ausente.
- Componentes válidos numa mensagem com `direction: "in"`: o OpenAPI não restringe, então são aceitos.

## Requirements *(mandatory)*

### Functional Requirements

**Validação de `msg` (AD-004, BD-004, AD-006)**

- **FR-001**: O endpoint MUST validar `msg.quick_replies`, `msg.list_message`, `msg.cta_message`, `msg.interaction_type`, `msg.header` e `msg.footer` conforme `StreamMsgPayload` de `openapi.flows.yaml` 1.1.0. Os seis campos são opcionais. Quando um campo está ausente, nenhuma regra nova se aplica a ele.
- **FR-002**: `quick_replies` MUST ser uma lista com pelo menos 1 item, e cada item MUST ser um texto com pelo menos 1 caractere.
- **FR-003**: `list_message` MUST ser um objeto com `button_text` (texto, ≥ 1 caractere) e `list_items` (lista, ≥ 1 item). Cada item MUST ser um objeto com `uuid` (texto, ≥ 1 caractere) e `title` (texto, ≥ 1 caractere). `description` é opcional e, quando presente, MUST ser texto.
- **FR-004**: `list_message.item_count` é opcional e, quando presente, MUST ser um inteiro ≥ 1.
- **FR-005**: `cta_message` MUST ser um objeto com `display_text` (texto, ≥ 1 caractere) e `url`. `url` MUST ser um URI e MUST casar com `^https?://.+`, ou seja, ser absoluta, com esquema `http` ou `https` e conteúdo depois do esquema.
- **FR-006**: `interaction_type`, quando presente, MUST ser `"list"` ou `"cta_url"`.
- **FR-007**: `header`, quando presente, MUST ser um objeto. `header.type`, quando presente, MUST ser `"text"`, e `header.text`, quando presente, MUST ser texto. `footer`, quando presente, MUST ser texto.
- **FR-008**: Cada valor MUST ter o tipo JSON que o contrato declara, sem conversão: um número não vale como texto, um texto não vale como inteiro, e um booleano não vale como inteiro. `null` MUST NOT ser aceito nos seis campos nem nas propriedades deles.
- **FR-009**: Payload inválido MUST ser rejeitado com `400`, com o erro sob a chave `msg` e o caminho do campo inválido, no formato de erro do DRF que o OpenAPI exemplifica. Os textos de exemplo do OpenAPI são ilustrativos. A rejeição MUST ser da requisição inteira: nenhuma linha em `msgs_msg` é criada, para nenhuma das URNs.
- **FR-010**: Uma chave não declarada em `list_message`, em cada item de `list_items`, em `cta_message` ou em `msg.header` MUST receber `400` sob a chave `msg`, no caminho do campo, sem criar linha em `msgs_msg` (AD-004 regra 1). As chaves no nível de `msg`, fora dos seis campos, MUST continuar aceitas e gravadas como hoje. `quick_replies` e `footer` não ganham regra além de FR-002 e FR-007.
- **FR-011**: Esta mudança MUST NOT criar limites que o contrato não declara: nenhum máximo de `quick_replies`, de `list_items` ou de tamanho de texto, URL ou corpo.

**Gravação DB-only (AD-004, AD-006, BD-006)**

- **FR-012**: `msg.text` vazio MUST ser aceito quando a `msg` tem pelo menos um componente válido. Nesse caso `Msg.text` é `""`.
- **FR-013**: Qualquer combinação de `list_message`, `cta_message` e `quick_replies` na mesma `msg` MUST ser aceita.
- **FR-014**: `Msg.metadata` MUST guardar o objeto `msg` como foi enviado e validado, sem renomear, converter, calcular ou remover campos. `item_count` só existe quando foi enviado.
- **FR-015**: O registro MUST continuar sendo criado só no banco, pelo caminho de `create_message_db_only`: nenhuma fila para Mailroom, nenhuma chamada a Courier e nenhum broadcast.
- **FR-016**: Chamadas sem os seis campos e sem `Idempotency-Key` MUST ter o mesmo resultado de hoje (status, corpo, linhas e `metadata`). As regras atuais de identificador do contato, conteúdo mínimo, canal, status, datas e labels não mudam.
- **FR-017**: A origem de `Msg.text` (o primeiro preenchido entre `text`, `message` e `msg.text`) MUST continuar a mesma.

**Idempotência (AD-004, Principle XI)**

- **FR-018**: O header `Idempotency-Key` é opcional. Sem ele, cada chamada válida MUST responder `201` e criar as linhas, como hoje, sem consultar o armazenamento de deduplicação.
- **FR-019**: O escopo da chave MUST ser endpoint + projeto autorizado + chave. Chaves deste endpoint MUST NOT colidir com as de `/api/v2/internals/whatsapp_broadcasts` nem com as de outro projeto.
- **FR-020**: Uma resposta bem-sucedida MUST ser lembrada por no mínimo 24h.
- **FR-021**: A mesma chave com um corpo equivalente (mesmo conteúdo JSON, em qualquer ordem de chaves) MUST responder `200` com os `ids` originais e MUST NOT criar linhas.
- **FR-022**: A mesma chave com um corpo diferente MUST responder `409` com `{"code": "idempotency_conflict", "error": "..."}` e MUST NOT criar linhas. O conflito é final: o chamador não repete com essa chave.
- **FR-023**: A mesma chave enquanto a primeira requisição ainda está em processamento MUST responder `409` com `{"code": "idempotency_in_progress", "error": "..."}` e MUST NOT criar linhas. O caso é transitório: o chamador pode repetir dentro do orçamento de retry.
- **FR-024**: Só um `201` MUST ser lembrado. Se a requisição que reservou a chave termina sem sucesso (`400`, `403`, `404` ou erro de servidor), a chave MUST ficar livre para nova tentativa. A liberação vale só para a requisição que reservou a chave. O `409` devolvido a uma requisição duplicada MUST NOT liberar nem sobrescrever o registro da chave.
- **FR-025**: Uma chave vazia depois de remover espaços nas pontas, ou com mais de 128 caracteres, MUST ser tratada como ausente: sem deduplicação e sem `400` (AD-004 regra 3).
- **FR-026**: A chamada ao armazenamento de deduplicação MUST ter timeout explícito. Se ele falhar com o header presente, o endpoint MUST NOT criar linhas e MUST responder com erro de servidor sem detalhe interno. Ele MUST NOT gravar sem deduplicação.
- **FR-027**: O comportamento de `broadcasts/idempotency.py` é a referência. O módulo MUST NOT ser alterado.

**Autenticação e escopo de tenant (Cross-Cutting Conventions, SEC-03)**

- **FR-028**: O endpoint MUST exigir Bearer module JWT. Toda falha de JWT (ausente, com assinatura inválida, expirado ou sem claim de tenant) e toda falha de escopo de projeto MUST receber `403` com `detail`, sem criar linhas e sem efeito de idempotência. Este endpoint MUST NOT devolver `401` (AD-004 regra 4). O autenticador JWT compartilhado e o status de falha dos outros endpoints MUST NOT mudar.
- **FR-029**: O projeto autorizado MUST vir dos claims do token, pela regra de `jwt_tenant_claims`: `project_uuid`/`project`, ou o projeto do canal em `channel_uuid`/`channel` quando só ele existe. Um `project_uuid` no corpo diferente do projeto autorizado MUST receber `403` com `detail`. Essa verificação MUST acontecer antes de consultar ou registrar a `Idempotency-Key` e antes de qualquer gravação.
- **FR-030**: Quando o corpo bate com o projeto autorizado e o projeto não existe, a resposta MUST ser `404 {"error": "Project not found"}`.
- **FR-031**: O endpoint MUST declarar uma permissão explícita, com nome, que verifica o escopo de tenant (Principle XVII). Ele MUST NOT ter permissão vazia, nem `IsAuthenticated` ou `AllowAny`. A mudança MUST ficar contida neste endpoint: `JWTAuthMixinRequired` e as outras views que o usam não mudam.
- **FR-032**: `channel_uuid` no corpo MUST continuar restrito a canais do projeto autorizado, como hoje.

**Observabilidade e privacidade (Principles III, XIII; Cross-Cutting Conventions)**

- **FR-033**: Logs e eventos de Sentry gerados por este endpoint MUST NOT conter:
  - texto da resposta: `text`, `message`, `msg.text`, `header.text` e `footer`;
  - rótulos de botão: itens de `quick_replies`, `button_text` e `display_text`;
  - `list_items` e seus `title`/`description`;
  - `url`.

  Isso inclui o corpo da requisição que o Sentry anexa por padrão, as mensagens de exceção e os detalhes de erro de validação. "Rótulos" aqui não se refere ao campo de topo `labels`, que tem UUIDs de labels do Flows.
- **FR-034**: `X-Correlation-ID`, quando presente e com 1 a 128 caracteres, MUST ser tratado como identificador opaco: propagado como veio aos logs estruturados e às tags de Sentry da requisição, sem ser interpretado nem usado em decisão. Fora disso, é ignorado, e a requisição não é rejeitada.
- **FR-035**: Eventos de Sentry deste endpoint MUST carregar identificadores opacos: o projeto autorizado, o canal quando houver e o `X-Correlation-ID` quando houver. O JWT de módulo não traz conta nem usuário, e essa ausência MUST ficar explícita no evento (Principle XIII).
- **FR-036**: Cada requisição MUST gerar um log estruturado com o desfecho (`created`, `replayed`, `conflict`, `rejected_validation`, `rejected_auth`, `rejected_tenant`, `project_not_found` ou `error`) e só identificadores opacos.

**Contrato e entrega (Principles IV, VIII)**

- **FR-037**: A mudança MUST ser aditiva sobre o contrato atual (OpenAPI `1.1.0`): o `201 {"ids": [...]}` não muda, e `200` e `409` só aparecem com `Idempotency-Key`. Ela MUST NOT exigir migration nem versão nova de Courier ou Mailroom. A entrada em `WENI-CHANGELOG.md` MUST ter um bullet `feat` para os componentes e a idempotência e um bullet identificado como segurança para o escopo de tenant.

### Key Entities

- **Registro de mensagem** (`Msg`): uma linha por URN em `msgs_msg`, com `text` (pode ser `""`) e `metadata` (o objeto `msg` validado, com componentes). Nenhuma coluna nova.
- **Componentes**: `quick_replies` (lista de rótulos), `list_message` (`button_text`, `list_items`, `item_count` opcional) e `cta_message` (`display_text`, `url`), mais os acessórios `interaction_type`, `header` e `footer`. Podem coexistir.
- **Registro de idempotência**: projeto autorizado, chave, impressão do corpo, estado (em processamento ou concluído), resposta concluída (`ids`) e validade de no mínimo 24h. Vive no armazenamento compartilhado, nunca na memória do processo.
- **Token de módulo**: Bearer JWT do `nexus-ai` com claim de projeto e/ou canal. Define o projeto autorizado.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% dos payloads válidos da matriz de contrato (os 3 exemplos do OpenAPI e as combinações de US1) são registrados com os componentes iguais ao enviado, e 0 envios são disparados para o shopper por esses registros.
- **SC-002**: 100% dos payloads inválidos da matriz de US2 são rejeitados com o campo apontado, e 0 registros são criados por eles.
- **SC-003**: 0 registros duplicados quando o mesmo registro é reenviado com a mesma chave dentro de 24h; 100% dos reenvios recebem os ids originais; 100% dos reusos com conteúdo diferente recebem conflito.
- **SC-004**: 100% das chamadas no formato de hoje, sem campos novos e sem chave, continuam com o mesmo resultado de antes da mudança.
- **SC-005**: 0 chamadas aceitas sem credencial válida ou para um projeto diferente do autorizado.
- **SC-006**: 0 ocorrências de texto da resposta, rótulos, itens de lista ou URLs em logs e relatórios de erro deste endpoint, em todos os caminhos de sucesso e falha da matriz de testes.
- **SC-007**: Na carga de pico declarada, chamadas sem componentes e sem chave mantêm o tempo de resposta p95 da versão atual, dentro da variação normal de medição, e nenhum erro de servidor vem da validação ou da deduplicação.

## Peak Load (Principle XII)

- **Carga de pico declarada**: o endpoint já existe. O pico é a taxa de pico de registros DB-only do Shopping Assistant depois que o `nexus-ai` passar a chamar este endpoint em vez de `/api/v2/internals/whatsapp_broadcasts` para respostas com componentes em todos os canais de Shopping Assistant de uma vez (BD-010, AD-003). Ela é a soma de duas partes no mesmo horário de pico: o pico atual deste endpoint para o Shopping Assistant e o pico atual das respostas com componentes do Shopping Assistant que hoje passam por `whatsapp_broadcasts` em canais com streaming. O `/speckit-plan` MUST registrar esse número a partir das métricas de produção dos dois endpoints, como pico e não como média, antes do passo 1 de deploy.
- **Acréscimo por requisição**: uma validação síncrona em memória, sem I/O. Com `Idempotency-Key`, há no máximo uma chave no armazenamento compartilhado por requisição (reserva atômica, leitura em replay e regravação no sucesso), com validade de no mínimo 24h. O volume de chaves vivas é o número de requisições com chave em 24h.
- **Sem estado em processo**: o estado de idempotência fica no Redis compartilhado. Nenhum estado sobrevive na memória do processo entre requisições.
- **Fora do dimensionamento**: gRPC, Redis Pub/Sub do `weni-webchat-socket`, WebSocket e MongoDB.

## Assumptions

- O `nexus-ai` envia a `Idempotency-Key` recomendada pelo Architecture doc (`msg_id` ou `turn_id`), sempre com 1 a 128 caracteres (AD-004 regra 3).
- O `nexus-ai` aplica o retry limitado em timeout, erro de conexão, `5xx`, `429` e `409` `idempotency_in_progress`. Ele trata `400`, `403`, `404` e `409` `idempotency_conflict` como definitivos (Principle XI). Nem todo `409` é definitivo: o `nexus-ai` decide pelo `code`.
- Um `X-Correlation-ID` fora do contrato é ignorado, porque o `400` do contrato cobre só o corpo.
- Com o armazenamento de deduplicação indisponível e o header presente, falhar sem gravar é preferível a gravar sem deduplicação, porque o chamador tem retry limitado e a duplicação não teria como ser desfeita.
- `msg.text`, `msg.attachments`, `msg.template` e os campos de topo mantêm o tratamento de hoje (AD-004 regra 2 e escopo).
- A Product Spec é da Experience e vive em `vtex-cx-experience-specs`, não em `vtex-cx-engine-specs` como diz a Principle V. Isso está registrado em Constitution Alignment.

## Test Strategy

- Testes de fluxo completo em `temba/api/v2/internals/msgs/tests.py`, com `TembaTest`: da chamada HTTP até a linha em `msgs_msg` e `Msg.metadata`, com asserção de que nada foi enfileirado para Mailroom nem enviado ao Courier.
- Cada cenário de aceitação de US1 a US4 é um teste. Os caminhos de falha (`400`, `403`, `404`, `409` `idempotency_conflict`, `409` `idempotency_in_progress` e erro de servidor do armazenamento de deduplicação) são cobertos individualmente (Principle XIV). Os testes de US4 confirmam que nenhuma falha de autenticação devolve `401`.
- US4 MUST rodar com autenticação e permissão reais. Os testes atuais de stream substituem as duas por `[]`, e isso esconde o SEC-03. Os testes que precisam de token usam um token de teste com claims controlados.
- US3 usa o Redis de teste com limpeza das chaves, como os testes de broadcasts. Concorrência (em processamento) e expiração da validade são testadas.
- Teste de privacidade: captura de logs e de eventos de Sentry nos caminhos de erro, com asserção de que nenhum valor de `text`, rótulo, `list_items` ou `url` aparece (SC-006).
- Testes unitários da validação para as variações da matriz de US2 que são caras de montar pelo fluxo completo. Eles não substituem o fluxo completo.
- Gates: `poetry run coverage run manage.py test` (grupo `api` do `.github/workflows/ci.yml`) e `./code_check.py` limpos, sem `# pragma: no cover` novo.

## Rollout and Rollback

- Passo 1 da *Delivery Sequence*: `flows` é 100% aditivo e vai a produção antes de o `nexus-ai` habilitar o streaming com componentes (passo 5).
- O risco "Autenticação JWT em `POST /api/v2/internals/messages/stream` (SEC-03)" do Architecture doc é resolvido por US4, no mesmo deploy.
- Rollback do `flows` só depois de o `nexus-ai` desligar o envio de componentes em stream, como diz o Architecture doc.

## Constitution Alignment

| Principle | Como esta spec atende |
|---|---|
| IV. Versioned Contracts | Delta aditivo `1.1.0`; `201` inalterado; sem migration; sem versão nova de Courier ou Mailroom (FR-037). |
| V. Specification Traceability | Herança no formato exato, com Product Spec pinada por tag e commit e Architecture doc pinado no commit da emenda (`329a1db`). Re-fixar na tag `arch-v1` quando a aprovação do `flows` constar no documento tagueado. A Product Spec vive em `vtex-cx-experience-specs`, e não em `vtex-cx-engine-specs` como o texto da Principle V prevê, porque é uma feature da Experience. Ponto registrado para os mantenedores. |
| VI. No Silent Divergence | `Divergences: none` em relação à Product Spec. Não há inconsistência de contrato pendente: as cinco levantadas antes foram resolvidas pelo autor no AD-004 (regras 1 a 4, 2026-11-23), e esta spec só aplica essas decisões. |
| IX. Never Trust the Client | Validação na fronteira do serializer (FR-001 a FR-011) e autorização no servidor (FR-028 a FR-032). |
| XI. Bounded Retry Over REST | `Idempotency-Key` torna o retry do `nexus-ai` seguro (FR-018 a FR-027). |
| XII. Scalability and Peak Load | Pico declarado como pico; estado de idempotência no Redis compartilhado (seção Peak Load). |
| XIII. Diagnosable Errors | Identificadores opacos de projeto, canal e correlação; ausência de conta e usuário explícita; nenhum dado pessoal (FR-033 a FR-035). |
| XIV. Tests Exercise Flows | Fluxo completo por história, caminhos de falha cobertos e autenticação real em US4 (Test Strategy). |
| XV. Explicit Over Clever | Limite de 128 caracteres da chave, retenção de 24h, nomes de header e padrão da URL como constantes nomeadas no plano. |
| XVI. Contained Changes | Só `temba/api/v2/internals/msgs/`. `broadcasts/idempotency.py`, `JWTAuthMixinRequired`, `whatsapp_broadcasts` e o resto da 009 ficam intocados. |
| XVII. Explicit, Scoped Authorization | Permissão nomeada de escopo de tenant no endpoint; fim do `permission_classes = []` herdado (FR-031). |
| III, VIII, X | Logs estruturados sem dado pessoal; changelog com bullet de segurança; timeout explícito no Redis e erro sem detalhe interno (FR-026, FR-036, FR-037). |
