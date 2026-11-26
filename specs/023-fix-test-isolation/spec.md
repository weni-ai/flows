# Engineering Spec: isolamento de logging e de escopo do Sentry entre testes do grupo `api`

**Repository**: weni-ai/flows — backend

**Feature Branch**: `fix/msg-stream-tests`

**Created**: 2026-11-25

**Status**: Implemented

**Input**: User description: "Engineering spec SDD Lite (sem Product Spec) para fazer voltar a passar no CI os 13 testes que quebram quando o grupo `api` roda inteiro no mesmo processo. Causa A: `temba/fastapi_app/__init__.py` chama `django.setup()` na importação e reaplica `LOGGING` com `disable_existing_loggers: True`, desligando loggers no meio da suíte. Causa B: `bind_request_scope` grava tags e um event processor no escopo atual do Sentry e o cliente de teste do Django não cria escopo por requisição. Não mudar asserções, não pular testes, não acrescentar `# pragma: no cover`. Avaliar se o vazamento do Sentry acontece em produção."

**Cycle**: SDD Lite. Duas correções contidas, uma em `temba/fastapi_app/__init__.py` e uma na base de testes `temba/tests/`, mais testes de regressão. Sem migration, sem contrato público alterado, sem Courier ou Mailroom, sem tipo de canal. A implementação sai direto deste `spec.md`, sem `plan.md` nem `tasks.md`.

## Origin Without Product Spec

- Product Spec: none
- Problem: Quando o grupo `api` do CI roda inteiro num só processo, 13 testes que passam isolados falham pela ordem de execução. Importar `temba.fastapi_app` no meio da suíte desliga todos os loggers já criados (testes 1 a 4), e as tags e o event processor que o endpoint de stream grava no escopo do Sentry sobrevivem à requisição de teste e aparecem nos eventos de testes seguintes (testes 5 a 13).
- Acceptance criteria:
  - AC-1: O comando de reprodução (seção "Reprodução") termina com 0 failures. Os 8 errors `test_trigger_flow_uuid_*`, que só acontecem sem Mailroom em `localhost:8090`, podem continuar localmente. Testes: os 13 listados em "Testes que falham hoje", sem nenhuma alteração nas suas asserções.
  - AC-2: Os quatro grupos de `.github/workflows/ci.yml` (`api`, `channels`, `core` e `others`) ficam verdes, porque a base de testes alterada é compartilhada por todos. Teste: execução do workflow no pull request.
  - AC-3: Importar `temba.fastapi_app` com o Django já configurado não desliga loggers que já existem. Teste: `temba.fastapi_app.tests.TestPackageImport.test_import_with_django_configured_keeps_existing_loggers` (novo), que falha antes da correção e passa depois.
  - AC-4: Depois de uma requisição ao `POST /api/v2/internals/messages/stream`, o escopo do Sentry fora dela não tem as tags do stream (`caller`, `account_id`, `user_id`, `project_uuid`, `channel_uuid`, `correlation_id`) nem o processor `scrub_stream_event`. Teste: `temba.api.v2.internals.msgs.tests.TestMsgStreamObservability.test_stream_request_scope_does_not_leak` (novo), que falha antes da correção e passa depois.
  - AC-5: O endpoint de stream continua cumprindo os FR-033 a FR-036 da spec 022: os 64 testes atuais de `temba.api.v2.internals.msgs` continuam passando, em especial `test_sentry_event_omits_message_content`, `test_each_outcome_is_logged_without_content` e `test_correlation_id_bounds`.
  - AC-6: A conclusão de que o vazamento não acontece em produção fica fixada por um teste do contrato do sentry-sdk em que ela se apoia. Teste: `temba.api.v2.internals.msgs.tests.TestStreamSentryProductionScope.test_wsgi_request_scope_is_discarded` (novo).
  - AC-7: `./code_check.py` termina limpo com os arquivos alterados.

## Testes que falham hoje

Nenhuma das asserções abaixo pode mudar (Principle XIV).

| # | Teste | Sintoma | Causa |
|---|-------|---------|-------|
| 1 | `temba.api.v2.internals.contacts.tests.UpdateContactFieldsViewTest.test_fallback_skips_auto_create_when_org_at_field_limit` | `no logs of level WARNING or higher triggered on temba.api.v2.internals.contacts.serializers` | A |
| 2 | `temba.api.v2.internals.msgs.tests.TestMsgStreamObservability.test_correlation_id_bounds` | `no logs of level INFO or higher triggered on temba.api.v2.internals.msgs` | A |
| 3 | `temba.api.v2.internals.msgs.tests.TestMsgStreamObservability.test_each_outcome_is_logged_without_content` | idem | A |
| 4 | `temba.api.v2.internals.msgs.tests.TestStreamMsgFieldUnit.test_claim_recovers_when_the_key_disappears_and_release_swallows_redis_errors` | `assertLogs` em `temba.api.v2.internals.msgs.idempotency` não recebe log | A |
| 5–8 | `temba.api.v2.tests.WhatsappBroadcastsInlineMediaTest.test_redis_failures` [get ConnectionError], [get TimeoutError], [set ConnectionError], [set TimeoutError] | tags do evento trazem `caller: module_jwt` e `account_id: none` além das esperadas por `assertMediaStorageUnavailable` (`temba/api/v2/tests.py:7610`) | B |
| 9–13 | `temba.api.v2.tests.WhatsappBroadcastsInlineMediaTest.test_s3_failures` [ClientError], [S3UploadFailedError], [ReadTimeoutError], [ConnectTimeoutError], [OSError] | idem | B |

## Reprodução

```sh
poetry run python manage.py test temba.api.v2.internals.broadcasts temba.api.v2.internals.contacts.tests.UpdateContactFieldsViewTest temba.api.v2.internals.msgs temba.api.v2.tests.WhatsappBroadcastsInlineMediaTest --keepdb
```

Resultado em 2026-11-25, no commit `c03aa1954`: `Ran 225 tests`, `FAILED (failures=13, errors=8)`. Os 13 failures são exatamente os da tabela acima. Os 8 errors são `TestInternalWhatsappBroadcast.test_trigger_flow_uuid_*`, que exigem Mailroom local e estão fora do escopo.

## Causas confirmadas no código

### Causa A: loggers desligados no meio da suíte (testes 1 a 4)

- `temba/fastapi_app/__init__.py:16` chama `django.setup()` incondicionalmente na importação. A docstring (linhas 5 a 7) diz que isso é idempotente, mas não é: `django.setup()` sempre chama `configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)` antes de `apps.populate()`, e só o `populate` é idempotente.
- `LOGGING` em `temba/settings_common.py:364-381` tem `"disable_existing_loggers": True`. Reaplicar essa configuração marca `logger.disabled = True` em todo logger já criado que não esteja declarado em `loggers` nem seja filho de um declarado. O comentário da linha 378 sobre `temba.conversion_events` é o mesmo problema contornado para um logger só.
- `assertLogs` troca handlers, nível e `propagate`, mas não mexe em `logger.disabled`. Com `disabled = True`, `Logger.isEnabledFor` devolve `False` e nenhum registro chega ao handler de captura.
- O gatilho no grupo `api` é `temba/api/v2/internals/broadcasts/tests.py:2681` (`TestFastAPIBridgeUnchanged.test_bridge_serializer_unchanged`), que importa `temba.fastapi_app.broadcasts` dentro do teste. Os módulos `temba.api.v2.internals.contacts` e `temba.api.v2.internals.msgs` rodam depois na ordem alfabética, com seus loggers já criados e agora desligados.
- No grupo `others`, `temba/fastapi_app/tests.py:9-10` importa o pacote durante a descoberta de testes, então a mesma causa já desliga ali todo logger criado até aquele ponto, mesmo que hoje nenhum teste do grupo dependa disso.
- Verificação direta (2026-11-25): com o Django configurado, `logging.getLogger("temba.api.v2.internals.msgs.observability").disabled` passa de `False` para `True` logo depois de `import temba.fastapi_app`.
- Nenhum outro ponto do código chama `django.setup()`, `dictConfig` ou `configure_logging`.

### Causa B: escopo do Sentry compartilhado entre requisições de teste (testes 5 a 13)

- `bind_request_scope` (`temba/api/v2/internals/msgs/observability.py:77-89`), chamado no início de `MsgStreamView.post` (`views.py:188`), usa `sentry_sdk.configure_scope()`, grava as tags `caller`, `account_id`, `user_id`, `project_uuid`, `channel_uuid` e `correlation_id`, e chama `add_event_processor(scrub_stream_event)` no escopo atual.
- No sentry-sdk 1.45.1 (`poetry.lock:4000`), `Hub.configure_scope()` só devolve o escopo real quando há um cliente ligado ao hub. Sem cliente, devolve um `Scope()` descartável. Por isso o vazamento só aparece quando algum teste liga um cliente antes da requisição de stream. É o caso de `TestMsgStreamObservability.test_sentry_event_omits_message_content` (`tests.py:1537-1549`), que faz `Hub.current.bind_client(client)`. Ao terminar, o teste devolve o cliente anterior, mas as tags e o processor ficam no escopo do hub principal.
- O cliente de teste do Django usa `django.test.client.ClientHandler`, que herda de `BaseHandler` e não de `WSGIHandler` (`issubclass(ClientHandler, WSGIHandler)` é `False`). Por isso o patch que o `DjangoIntegration` aplica em `WSGIHandler.__call__`, e que cria um hub por requisição, nunca roda nos testes. Além disso, os testes não inicializam o Sentry com `DjangoIntegration`.
- Mais adiante, `report_media_storage_failure` (`temba/api/v2/broadcast_media.py:139`) usa `push_scope()`, que copia o escopo atual, já poluído. `capture_sentry_events` (`temba/tests/media.py:10-26`) liga um cliente ao mesmo hub principal, e o evento sai com `caller` e `account_id` herdados. Os valores de `user_id`, `project_uuid` e `correlation_id` são sobrescritos pelo `push_scope`, por isso só essas duas tags sobram.
- O processor também se acumula: cada requisição de stream de teste com cliente ligado acrescenta mais uma cópia de `scrub_stream_event` ao escopo global.
- Verificação direta (2026-11-25): duas chamadas a `bind_request_scope` fora de um hub por requisição deixam no escopo global as cinco tags e duas cópias de `scrub_stream_event`.
- `scrub_events_for_current_request` (`temba/utils/sentry.py:18-24`), usado em `temba/api/v2/broadcast_media.py:89` e `temba/flows/views.py:807`, segue o mesmo padrão (`configure_scope` e `add_event_processor`). Ele não grava tags, então hoje não quebra asserção, mas a correção da causa B também o isola nos testes. O código dele não muda.

## Avaliação em produção (causa B)

**Conclusão: o vazamento não acontece em produção.** A correção da causa B fica na base de testes, e o código de runtime do endpoint não muda.

Evidência:

1. **Sentry com `DjangoIntegration` em produção.** `docker/Dockerfile:124` liga `temba/settings.py` a `temba/settings.py.prod`, que chama `sentry_sdk.init(dsn=..., integrations=[DjangoIntegration()])` na linha 263. `temba/settings_common.py:21-26` faz o mesmo quando `SENTRY_DSN` está definido.
2. **Entrada WSGI.** `docker/start:65-70` sobe `gunicorn temba.wsgi:application`, e `temba/wsgi.py` usa `get_wsgi_application()`, ou seja, um `WSGIHandler`. `docker/gunicorn/gunicorn.conf.py` não define `worker_class`, então os workers são `sync` e atendem uma requisição por vez por processo.
3. **Hub por requisição.** No sentry-sdk 1.45.1, `DjangoIntegration.setup_once` troca `WSGIHandler.__call__` por `SentryWsgiMiddleware(old_app)`. `SentryWsgiMiddleware.__call__` cria `hub = Hub(Hub.current)` e roda a requisição dentro de `with hub:`. `Hub.__init__`, quando recebe um hub, faz `scope = copy.copy(other_scope)`, e a cópia duplica o dicionário de tags e a lista de processors. Assim, o `configure_scope()` chamado dentro da view devolve a cópia daquela requisição, que é descartada no fim dela.
4. **Exceções não tratadas também ficam no escopo da requisição.** O handler `_got_request_exception` do `DjangoIntegration` (sinal `got_request_exception`) captura com `Hub.current`, que durante a requisição é o hub dela. Por isso, em produção, um erro que escapa de `MsgStreamView` também recebe as tags e o `scrub_stream_event`. É disso que os FR-033 e FR-035 dependem.
5. **Concorrência.** `Hub.current` fica num `ContextVar`. Mesmo que o gunicorn passe a usar threads, cada contexto tem o seu hub.
6. **Verificação direta (2026-11-25).** `SentryWsgiMiddleware` em volta de uma aplicação WSGI que chama `bind_request_scope`, com cliente ligado, deixa o escopo externo com `tags = {}` e sem `scrub_stream_event`. Sem o middleware, as cinco tags e o processor ficam.
7. **Processo FastAPI.** O endpoint de stream é uma view DRF servida pelo gunicorn. O processo `fastapi` (`docker/start:111-118`, uvicorn) não serve essa rota.

Risco residual: a conclusão depende do contrato do sentry-sdk 1.x descrito no item 3. `pyproject.toml` aceita `sentry-sdk = "^1.0.0"`. O teste do AC-6 (FR-009) fixa esse contrato: se uma atualização o quebrar, o teste falha antes do deploy.

## Decisões de implementação

### D-1 (causa A): `django.setup()` só quando o Django ainda não está configurado

Em `temba/fastapi_app/__init__.py`, `django.setup()` passa a rodar só quando `django.apps.apps.ready` é `False`. A docstring é corrigida para dizer por que a chamada é condicional: reaplicar `LOGGING` com `disable_existing_loggers` desliga os loggers que já existem.

- Processo uvicorn: o pacote é importado antes de o Django estar configurado, então `apps.ready` é `False` e `django.setup()` roda como hoje.
- Gunicorn, Celery e consumers: nenhum deles importa `temba.fastapi_app`. Em todo o repositório, só testes importam o pacote. O comportamento de runtime não muda.
- Testes: o Django já está configurado pelo runner, a chamada é pulada e o logging não é reaplicado.

Alternativas rejeitadas:

- Mudar `disable_existing_loggers` para `False` em `LOGGING`: altera o logging global de todos os processos, o que a restrição de escopo proíbe (Principle XVI), e existe alternativa contida.
- Declarar em `LOGGING` cada logger afetado, como já foi feito com `temba.conversion_events`: trata o sintoma logger por logger, e o próximo logger novo volta a quebrar.
- Reabilitar loggers no `setUp` dos testes afetados, ou mover o import de `temba/api/v2/internals/broadcasts/tests.py:2681`: esconde o sintoma em cada teste, e qualquer outro import do pacote reproduz a falha.

### D-2 (causa B): cada requisição do cliente de teste roda no seu próprio hub do Sentry

A base de testes ganha um cliente de teste, subclasse de `django.test.Client`, cujo `request()` roda dentro de `with sentry_sdk.Hub(sentry_sdk.Hub.current):`. É a mesma fronteira que o `SentryWsgiMiddleware` cria em produção: mesmo cliente do Sentry, cópia do escopo no início e descarte no fim. Esse cliente é declarado como `client_class` de `TembaTestMixin` (`temba/tests/base.py:40`), e com isso vale para `TembaTest` e `TembaNonAtomicTest`. Um comentário curto registra a restrição: o `ClientHandler` do Django não passa por `WSGIHandler`, então o hub por requisição do `DjangoIntegration` não existe nos testes.

`bind_request_scope`, `scrub_stream_event` e `MsgStreamView` não mudam.

Alternativas rejeitadas:

- Trocar `configure_scope()` por `push_scope()` em `bind_request_scope` ou em volta de `MsgStreamView.post`/`dispatch`: em produção, uma exceção que escapa da view (erro de banco em `Org.objects.get`, erro inesperado do serializer, de `idempotency.claim` etc.) é capturada por `_got_request_exception` no hub da requisição, já fora do `push_scope`. O evento sairia sem `scrub_stream_event` e sem as tags, levando o corpo da requisição com `text`, rótulos e URL. Isso viola os FR-033 e FR-035 da spec 022 e reabre uma decisão dela.
- Criar um hub próprio em `MsgStreamView.dispatch`: tem o mesmo problema, porque `dispatch` relança a exceção não tratada e ela é capturada fora do hub da view. Também mudaria o runtime para corrigir algo que só acontece em teste.
- Corrigir só o teste que polui (`test_sentry_event_omits_message_content`) ou `capture_sentry_events` para usar `with Hub(client)`: é correção teste a teste, e o próximo teste que ligar um cliente e chamar um endpoint com `configure_scope` volta a vazar.
- Inicializar o Sentry com `DjangoIntegration` nas settings de teste: não resolve, porque o `ClientHandler` não passa pelo `WSGIHandler` patchado, e mexe na inicialização do Sentry em settings, o que a restrição proíbe.
- Limpar o escopo global no `setUp` ou no `tearDown` de `TembaTest`: não reproduz a fronteira de produção. Dentro de um mesmo teste, o que uma requisição grava continua visível depois dela, e os processors continuam se acumulando.

### D-3: teste do contrato de produção

Um teste em `temba/api/v2/internals/msgs/tests.py` envolve, com `SentryWsgiMiddleware` (o middleware que o `DjangoIntegration` 1.45.1 aplica em `WSGIHandler.__call__`), uma aplicação WSGI mínima que chama `bind_request_scope` e captura um evento, usando um cliente ligado num `Hub` isolado. O teste verifica que o evento capturado dentro da requisição traz as tags do stream, que o processor rodou nele e que, depois da requisição, o escopo do hub não tem nem as tags nem o processor. Assim a evidência dos itens 3 e 6 de "Avaliação em produção" fica executável.

## Escopo neste repositório

**Muda**:

- `temba/fastapi_app/__init__.py`: `django.setup()` condicional e docstring corrigida (D-1).
- `temba/tests/`: cliente de teste com hub do Sentry por requisição, e `client_class` em `TembaTestMixin` (D-2).
- `temba/fastapi_app/tests.py`: teste de regressão da causa A.
- `temba/api/v2/internals/msgs/tests.py`: teste de regressão da causa B e teste do contrato de produção (D-3).

**Não muda**:

- As asserções dos 13 testes listados. Nenhum teste é pulado, e nenhum `# pragma: no cover` é acrescentado.
- `LOGGING`, `send_default_pii` e a inicialização do Sentry em `temba/settings_common.py` e `temba/settings.py.prod`.
- `bind_request_scope`, `scrub_stream_event`, `log_outcome` e `MsgStreamView`.
- `temba/utils/sentry.py`.
- A detecção de DOCX, XLSX e PPTX em `temba/msgs/usecases/broadcast_media.py` (commit `c03aa1954`), `temba/api/v2/internals/broadcasts/idempotency.py`, `JWTAuthMixinRequired` e o autenticador JWT.
- As decisões das specs 019 (inline media) e 022 (stream).
- Os 8 errors `test_trigger_flow_uuid_*`, que dependem de Mailroom local.

## User Scenarios & Testing *(mandatory)*

Quem usa esta mudança é quem abre pull request no Flows: o gate do CI precisa refletir defeitos reais, não a ordem dos testes.

### User Story 1 - Testes que verificam logs passam em qualquer ordem (Priority: P1)

Um desenvolvedor roda o grupo `api` inteiro. Os testes que usam `assertLogs` recebem os logs que o código emite, mesmo que algum teste anterior tenha importado `temba.fastapi_app`.

**Why this priority**: Quatro dos 13 testes quebram por isso, e a mesma causa ameaça qualquer teste de log que rode depois do import, em qualquer grupo.

**Independent Test**: Rodar o comando de reprodução e confirmar que os testes 1 a 4 passam. Rodar o teste do AC-3 isolado.

**Acceptance Scenarios**:

1. **Given** o Django já configurado e o logger `temba.api.v2.internals.msgs.observability` habilitado, **When** `temba.fastapi_app` é importado, ou reimportado com `importlib.reload`, **Then** o logger continua habilitado e `assertLogs` nele captura o registro emitido.
2. **Given** um processo sem o Django configurado, **When** `temba.fastapi_app` é importado, **Then** o Django fica configurado (settings, logging e apps) e `temba.fastapi_app.broadcasts` importa ORM e serializers no topo do módulo, como hoje.

---

### User Story 2 - Eventos do Sentry de um teste não herdam o escopo de outro (Priority: P1)

Um desenvolvedor roda os testes de mídia inline depois dos testes do endpoint de stream. Cada evento capturado traz só as tags que o código daquele fluxo grava.

**Why this priority**: Nove dos 13 testes quebram por isso, e o mesmo vazamento pode mascarar ou inventar falhas em qualquer teste que verifique eventos do Sentry.

**Independent Test**: Rodar o comando de reprodução e confirmar que os testes 5 a 13 passam. Rodar o teste do AC-4 isolado.

**Acceptance Scenarios**:

1. **Given** um cliente do Sentry ligado ao hub atual, **When** o teste faz uma requisição ao endpoint de stream e depois sai dela, **Then** o escopo fora da requisição não tem `caller`, `account_id`, `user_id`, `project_uuid`, `channel_uuid` nem `correlation_id`, não tem `scrub_stream_event` e está igual ao que era antes da requisição.
2. **Given** uma requisição de stream já feita no mesmo processo, **When** `report_media_storage_failure` reporta uma falha de S3 ou de Redis, **Then** o evento traz exatamente `org_id`, `project_uuid`, `user_id`, `correlation_id`, `media_stage` e `media_cause`.
3. **Given** N requisições de stream com cliente ligado, **When** termina a última, **Then** o escopo global tem zero cópias de `scrub_stream_event`.

---

### User Story 3 - Observabilidade do endpoint de stream continua igual (Priority: P2)

O endpoint `POST /api/v2/internals/messages/stream` continua mandando eventos do Sentry sem conteúdo de mensagem e com as tags opacas, e continua logando um desfecho por requisição, tanto nos testes quanto em produção.

**Why this priority**: É a restrição que impede a correção de virar regressão de privacidade (FR-033 a FR-036 da spec 022).

**Independent Test**: Rodar `temba.api.v2.internals.msgs` e confirmar que os 64 testes atuais passam e que os dois novos passam.

**Acceptance Scenarios**:

1. **Given** uma requisição de stream que falha com exceção inesperada e um cliente do Sentry ligado, **When** o evento é capturado dentro da requisição, **Then** ele não contém `text`, rótulos, `list_items` nem `url` e traz `project_uuid`, `correlation_id`, `caller=module_jwt`, `account_id=none` e `user_id=none` (`test_sentry_event_omits_message_content`).
2. **Given** a requisição atravessando `SentryWsgiMiddleware`, como em produção, **When** um evento é capturado dentro dela, **Then** ele traz as tags do stream e passou por `scrub_stream_event`, e o escopo externo continua limpo depois (teste do AC-6).
3. **Given** qualquer desfecho do endpoint, **When** a requisição termina, **Then** há exatamente um log `messages_stream outcome` com só identificadores opacos (`test_each_outcome_is_logged_without_content`).

---

### Edge Cases

- `temba.fastapi_app` importado antes de o Django estar configurado (processo uvicorn): `django.setup()` roda como hoje.
- `temba.fastapi_app` importado durante `apps.populate()`: `apps.ready` ainda é `False` e `django.setup()` falha com `populate() isn't reentrant`, exatamente como hoje. Nenhum código faz isso, e a mudança não piora o caso.
- Teste que não liga cliente do Sentry: `configure_scope()` já devolvia escopo descartável, e o hub por requisição não muda nada.
- Requisição feita dentro de `with sentry_sdk.Hub(client):`, como em `temba/flows/tests.py:3670-3679`: o hub da requisição copia esse hub, então os eventos continuam chegando ao `before_send` do teste.
- Requisição feita com `capture_sentry_events()` ativo (cliente ligado ao hub principal): o hub da requisição herda o cliente, então os eventos continuam chegando ao transport do teste.
- Teste que monta `APIClient()` manualmente em vez de usar `self.client` (por exemplo `temba/api/v2/tests.py:7951` e `temba/api/v2/internals/media/tests.py:163`): não ganha o hub por requisição. Nenhum desses testes chama o endpoint de stream. Se algum passar a precisar, deve usar o cliente de teste da base.
- Falha dos testes de regressão antes da correção: cada teste novo restaura o estado global que ele mesmo alterou (loggers que desligou, tags e processors que acrescentou), sem limpar estado que já existia quando ele começou. Assim, a falha esperada antes da correção não contamina outros testes nem esconde a poluição deixada por testes anteriores.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Importar ou reimportar `temba.fastapi_app` num processo em que o Django já está configurado MUST NOT reaplicar `LOGGING` nem alterar `disabled` de qualquer logger existente.
- **FR-002**: Importar `temba.fastapi_app` num processo em que o Django não está configurado MUST continuar configurando settings, logging e apps antes dos submódulos, para que `temba.fastapi_app.broadcasts` e `temba.fastapi_app.auth` importem ORM e serializers no topo do arquivo.
- **FR-003**: A docstring de `temba/fastapi_app/__init__.py` MUST deixar de dizer que `django.setup()` é idempotente e MUST registrar por que a chamada é condicional.
- **FR-004**: Toda requisição feita pelo cliente de teste padrão de `TembaTest` e `TembaNonAtomicTest` MUST rodar num hub do Sentry próprio, criado a partir do hub atual no início (mesmo cliente, cópia do escopo) e descartado no fim, como faz o `SentryWsgiMiddleware` em produção.
- **FR-005**: Eventos capturados dentro de uma requisição de teste MUST continuar chegando ao cliente que estava ligado antes dela (`capture_sentry_events`, `with sentry_sdk.Hub(client)` e `bind_client`), com as tags e os processors gravados durante a requisição.
- **FR-006**: `bind_request_scope`, `scrub_stream_event`, `log_outcome` e `MsgStreamView` MUST NOT mudar. Os FR-033 a FR-036 da spec 022 MUST continuar valendo, comprovados pelos 64 testes atuais de `temba.api.v2.internals.msgs` e pelo FR-009.
- **FR-007**: MUST existir o teste `TestPackageImport.test_import_with_django_configured_keeps_existing_loggers` em `temba/fastapi_app/tests.py`. Ele cria um logger, reexecuta o pacote com `importlib.reload(temba.fastapi_app)`, verifica que o logger continua habilitado e que `assertLogs` captura um registro dele, e reabilita no cleanup os loggers que o reload tiver desligado. O teste MUST falhar sem D-1 e passar com D-1.
- **FR-008**: MUST existir o teste `TestMsgStreamObservability.test_stream_request_scope_does_not_leak` em `temba/api/v2/internals/msgs/tests.py`. Ele guarda as tags e os processors do escopo atual, liga um cliente do Sentry, faz um `post_stream` com `project_uuid`, `channel_uuid` e `X-Correlation-ID`, devolve o cliente anterior e verifica que o escopo fora da requisição não tem nenhuma das tags do stream, não tem `scrub_stream_event` e ficou igual ao que era antes. No cleanup, restaura as tags e os processors que guardou. O teste MUST falhar sem D-2 e passar com D-2.
- **FR-009**: MUST existir o teste `TestStreamSentryProductionScope.test_wsgi_request_scope_is_discarded` em `temba/api/v2/internals/msgs/tests.py`, conforme D-3, usando um `Hub` isolado para não depender nem alterar o hub principal.
- **FR-010**: As asserções dos 13 testes de "Testes que falham hoje" MUST NOT mudar. Nenhum teste MUST ser pulado, e nenhum `# pragma: no cover` ou equivalente MUST ser acrescentado.
- **FR-011**: `LOGGING`, `send_default_pii` e a inicialização do Sentry em settings MUST NOT mudar. `temba/msgs/usecases/broadcast_media.py`, `temba/api/v2/internals/broadcasts/idempotency.py`, `JWTAuthMixinRequired` e o autenticador JWT MUST NOT mudar.
- **FR-012**: Como nenhuma das duas correções altera comportamento de runtime (ver D-1 e "Avaliação em produção"), esta mudança MUST NOT acrescentar entrada em `WENI-CHANGELOG.md`. Se a implementação vier a alterar algum caminho de runtime além do `django.setup()` condicional, MUST acrescentar um bullet `fix:` sob a próxima versão.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: O comando de reprodução passa de 13 failures para 0 failures. A contagem de errors fica em, no máximo, os 8 `test_trigger_flow_uuid_*` locais.
- **SC-002**: Os quatro grupos do workflow de CI terminam verdes no pull request.
- **SC-003**: Os 3 testes novos existem, e os 2 de regressão falham quando rodados sem as correções e passam com elas. Essa demonstração fica registrada no pull request.
- **SC-004**: O diff do pull request tem zero alterações nas asserções dos 13 testes, zero `skip` novo e zero `# pragma: no cover` novo.
- **SC-005**: Os 64 testes atuais de `temba.api.v2.internals.msgs` passam, mais os 2 novos do mesmo módulo.
- **SC-006**: `./code_check.py` termina sem erros.

## Peak Load (Principle XII)

Não se aplica. Nenhum caminho de requisição, task, consumer, consulta ou estado compartilhado muda. D-1 roda uma vez por processo, na importação de um pacote que só o processo uvicorn e os testes importam, e não muda o que esse processo faz. D-2 e D-3 existem só na suíte de testes. Não há carga nova a declarar.

## Assumptions

- O ambiente de produção é o descrito em "Avaliação em produção": `settings.py.prod`, gunicorn com `temba.wsgi:application` e sentry-sdk 1.45.1 travado no `poetry.lock`.
- A ordem de execução no CI é a do runner do Django: alfabética por módulo dentro de cada label, como na reprodução local.
- O CI do grupo `api` tem Mailroom disponível (`.github/workflows/ci.yml:124`), por isso os 8 errors locais não aparecem lá.
- O custo de criar um `Hub` por requisição de teste (cópia rasa do escopo) é desprezível perto do custo da própria requisição.

## Test Strategy

**Testes novos** (Principle XIV; cada bug corrigido ganha teste de regressão):

| Teste | Cobre | Antes da correção | Depois |
|-------|-------|-------------------|--------|
| `temba.fastapi_app.tests.TestPackageImport.test_import_with_django_configured_keeps_existing_loggers` | Causa A, AC-3, FR-001, FR-007 | falha (logger fica `disabled`) | passa |
| `temba.api.v2.internals.msgs.tests.TestMsgStreamObservability.test_stream_request_scope_does_not_leak` | Causa B, AC-4, FR-004, FR-008 | falha (tags e processor no escopo externo) | passa |
| `temba.api.v2.internals.msgs.tests.TestStreamSentryProductionScope.test_wsgi_request_scope_is_discarded` | Conclusão de produção, AC-6, FR-009 | passa (fixa o contrato do sentry-sdk) | passa |

**Testes existentes que fecham os critérios**:

- Os 13 testes da tabela "Testes que falham hoje" (AC-1).
- `temba.api.v2.internals.msgs`, os 64 atuais (AC-5), em especial `test_sentry_event_omits_message_content`, que verifica FR-033 e FR-035 no caminho do cliente de teste agora com hub por requisição.
- Os testes que fazem requisição dentro de um cliente do Sentry já ligado, e que mostram que os eventos capturados na requisição continuam chegando ao cliente do teste (FR-005): `temba/flows/tests.py:3877` e `:3900` (`with sentry_sdk.Hub(client)` e `DjangoIntegration`), `temba/api/v2/internals/broadcasts/tests.py:2633` e `:2655`, e os próprios testes 5 a 13 (`capture_sentry_events` com `bind_client`).

**Ordem de execução para demonstrar a regressão**: primeiro os testes novos, sem as correções, e o resultado (2 failures) vai para o PR. Depois D-1 e D-2, e os comandos abaixo.

**Comandos**:

```sh
# AC-1: 0 failures (até 8 errors locais de Mailroom)
poetry run python manage.py test temba.api.v2.internals.broadcasts temba.api.v2.internals.contacts.tests.UpdateContactFieldsViewTest temba.api.v2.internals.msgs temba.api.v2.tests.WhatsappBroadcastsInlineMediaTest --keepdb

# AC-3, AC-4, AC-5, AC-6
poetry run python manage.py test temba.fastapi_app temba.api.v2.internals.msgs --keepdb

# AC-2: o grupo api como o CI roda (os outros três grupos rodam no workflow do PR, porque a base de testes é compartilhada)
poetry run coverage run manage.py test --keepdb --noinput temba.api

# AC-7
./code_check.py
```

**Riscos de teste**: D-2 vale para toda subclasse de `TembaTestMixin`. Um teste que dependesse de ler, fora da requisição, algo que a requisição gravou no escopo global do Sentry passaria a falhar. A busca por `Hub.current.scope`, `last_event_id`, `_tags` e `_event_processors` em `temba/` não encontrou nenhum caso, e os quatro grupos do CI confirmam.

## Rollout and Rollback

Não há rollout de runtime: D-1 não muda o processo uvicorn, e D-2 e D-3 só existem na suíte. Rollback é reverter o commit. Os 13 testes voltariam a falhar no grupo `api`.

## Constitution Alignment

Este é o Constitution Check do ciclo SDD Lite. O preset `vtex-cx-engineering` não está instalado (TODO SPECKIT_PRESET), por isso esta seção e a Test Strategy foram escritas à mão.

| Princípio | Como esta mudança cumpre |
|-----------|--------------------------|
| I. Version Control and Review | Entra por pull request com review e `.github/workflows/ci.yml` verde nos quatro grupos (AC-2). |
| II. Security and Secrets | Nenhum segredo, nenhuma dependência nova. O teste D-3 usa o `SentryWsgiMiddleware` do sentry-sdk já travado. |
| III. Observability | Corrige o desligamento indevido de loggers estruturados nos testes. Nenhum log de produção muda. |
| IV. Versioned Contracts | Nenhum contrato público muda: nem DRF, nem FastAPI, nem Courier, nem eventos. |
| V. Specification Traceability | Abre com `## Origin Without Product Spec`. Cada critério de aceitação está ligado a um teste nomeado. |
| VI. No Silent Divergence | Não se aplica: não há Product Spec. As decisões das specs 019 e 022 são mantidas, e o FR-006 preserva os FR-033 a FR-036 da 022. |
| VII. Commit Messages | Commits atômicos sugeridos: `test: add regressions for logger and sentry leaks`, `fix: skip django.setup when apps are ready`, `fix: isolate sentry scope per test request`. Cada descrição tem até 50 caracteres. |
| VIII. Changelog Maintenance | Sem entrada: nenhuma mudança visível ao usuário nem de runtime (FR-012, D-1 e "Avaliação em produção"). |
| IX. Never Trust the Client | Não se aplica: nenhuma entrada externa nova nem alterada. |
| X. Fail Gracefully | Não se aplica: nenhuma chamada a dependência externa muda. |
| XI. Bounded Retry | Não se aplica: nenhuma propagação entre serviços. |
| XII. Scalability and Peak Load | Nenhum estado em memória de processo é introduzido no runtime. Peak Load declarado como não aplicável, com o motivo. |
| XIII. Diagnosable Errors | Os eventos do stream continuam com `project_uuid`, `correlation_id`, `caller`, `account_id=none` e `user_id=none` (FR-006, AC-5, AC-6). Os eventos de mídia inline voltam a trazer só as próprias tags. `TODO(SENTRY_PII)` continua fora do escopo e `send_default_pii` não muda. |
| XIV. Tests Exercise Flows | Dois testes de regressão que falham antes e passam depois, e um teste do contrato de produção. As asserções existentes não mudam, nenhum teste é pulado e nenhum `# pragma: no cover` é acrescentado. O gate é o CI mais `./code_check.py`. |
| XV. Explicit Over Clever | O hub por requisição é declarado onde acontece (`client_class` da base de testes), com comentário da restrição (o `ClientHandler` não passa pelo `WSGIHandler`). A condição de `django.setup()` fica explícita, com a docstring corrigida. Não há literal com significado novo. |
| XVI. Contained Changes | Só `temba/fastapi_app/__init__.py`, `temba/tests/` e os arquivos de teste dos dois módulos. `LOGGING`, a inicialização do Sentry, o endpoint de stream e os arquivos protegidos pela restrição não mudam (FR-006, FR-011). |
| XVII. Explicit, Scoped Authorization | Não se aplica: nenhuma permissão nem endpoint muda. `JWTAuthMixinRequired` e o autenticador JWT não são tocados. |
