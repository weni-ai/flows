# Implementation Plan: etapa 0 do upgrade do Django, parte 1 — testes de proteção

**Branch**: `chore/django-upgrade-stage0` | **Date**: 2026-11-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/025-django-upgrade-stage0/spec.md`

**Cycle**: SDD Full. Este plano detalha só o "como": requisitos, decisões D-1 e D-2 e escopo são os da spec. Os requisitos da [024](../024-django-5-2-upgrade/spec.md) cobertos aqui são os da tabela "Rastreabilidade com a 024".

## Summary

Um PR, só com testes, antes de qualquer outra mudança da etapa 0:

- `TimezoneParityTest` fixa, com literais capturados do código atual (`pytz`), a saída de cada ponto de runtime da FR-001, nos cinco fusos e nas datas de transição.
- `HamlTemplatesCompileTest` compila os 345 `.haml` descobertos pela configuração de templates.

Sem mudança de código de produção, sem migration, sem dependência nova. Decisões em [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11 (CI e Docker), `>=3.10,<3.12` no `pyproject.toml`.

**Primary Dependencies** (inalteradas, versões do `poetry.lock`):

- Django 3.2.25 e smartmin 3.1.0;
- django-hamlpy 1.7.0;
- django-timezone-field 5.1, pytz 2025.2 e tzdata 2025.3.

**Storage**: PostgreSQL/PostGIS, sem mudança de schema. O teste só escreve no banco de teste ([data-model.md](data-model.md)).

**Testing**: `TembaTest`, `poetry run coverage run manage.py test`, os quatro grupos do `.github/workflows/ci.yml` e `./code_check.py`. Os testes novos de `temba/utils/tests.py` rodam no grupo `others`.

**Target Platform**: serviço web Linux (gunicorn), Celery, consumers RabbitMQ e FastAPI. Nenhum deles muda.

**Project Type**: web-service (monolito Django `temba`).

**Performance Goals**: nenhum.

**Constraints**:

- nenhum arquivo fora de `temba/utils/tests.py`, dos documentos de `specs/024-*` e `specs/025-*`, `.specify/feature.json` e `.cursor/rules/specify-rules.mdc` muda (FR-005);
- o `TimezoneParityTest` não importa `pytz` nem `zoneinfo` (FR-003, [research.md](research.md) R2);
- nenhum `# pragma: no cover` ou teste pulado novo.

**Scale/Scope**: um arquivo de teste.

### Peak Load (Principle XII)

Não se aplica. Só testes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Antes da Phase 0

| Principle | Gate | Status |
|---|---|---|
| I. Version Control and Review | um PR com review e CI verde, com spec própria | PASS |
| II. Security and Secrets | sem segredo; sem dependência nova | PASS |
| III. Observability | nenhum log muda | N/A |
| IV. Versioned Contracts | nenhum contrato muda; sem migration | PASS |
| V. Specification Traceability | `## Origin Without Product Spec`; cada AC com teste | PASS |
| VI. No Silent Divergence | sem Product Spec | N/A |
| VII. Commit Messages | Conventional Commits até 50 caracteres; atômicos | PASS: R6 |
| VIII. Changelog Maintenance | sem mudança visível | N/A: R6 |
| IX a XI | nenhuma entrada do cliente, chamada externa ou propagação nova | N/A |
| XII. Scalability and Peak Load | Peak Load declarado | PASS: não aplicável, com o motivo |
| XIII. Diagnosable Errors | falha de teste mostra o caso | PASS |
| XIV. Tests Exercise Flows | o teste de paridade passa pelos fluxos reais | PASS: a verificar no desenho |
| XV. Explicit Over Clever | constantes nomeadas | PASS |
| XVI. Contained Changes | um arquivo de teste | PASS |
| XVII. Explicit, Scoped Authorization | nenhuma permissão muda | N/A |
| SDD Full | o teste exercita vários apps de `temba/` e o middleware | PASS |

Nenhuma violação. Phase 0 liberada.

### Depois da Phase 1

| Principle | Verificação no desenho | Status |
|---|---|---|
| XIV | o `TimezoneParityTest` passa por `create_schedule`, `write_export`, pela view de `Grant`, por `update_project_config`, pela tag `format_datetime`, pelo `TimezoneMiddleware`, pelo export de contatos, pela view `flows.flow_results` e por `validate_layers` | PASS |
| XV | constantes nomeadas para fusos, datas, formato, casos e esperados | PASS |
| XVI | só `temba/utils/tests.py` no código do Flows, mais os dois ponteiros do speckit; guarda de diff no [quickstart.md](quickstart.md) | PASS |

Nenhuma violação.

## Rastreabilidade com a 024

| 024 | Exige | Onde neste plano | Verificação |
|---|---|---|---|
| FR-001 | uma spec por PR; CI verde | esta spec é a primeira das quatro da etapa 0, num PR só | CI |
| FR-002 | nenhum payload, status ou cabeçalho de API muda | nenhum código de produção muda | guarda de diff |
| FR-003 | nenhum teste pulado, pragma novo ou asserção mudada | gates do [quickstart.md](quickstart.md) | `rg` no diff |
| FR-012 | `TimezoneParityTest` escrito na etapa 0 | "`TimezoneParityTest`" | literais do código atual; o teste não importa `pytz` |
| FR-021 | compilação de todo HAML | "`HamlTemplatesCompileTest`" | `HamlTemplatesCompileTest` |
| FR-025 | rollback descrito no PR | "Rollout e rollback" | descrição do PR |

## Project Structure

### Documentation (this feature)

```text
specs/025-django-upgrade-stage0/
├── spec.md
├── plan.md                         # este arquivo
├── research.md                     # Phase 0 (R1 a R6)
├── data-model.md                   # Phase 1
├── quickstart.md                   # Phase 1
├── checklists/requirements.md
└── tasks.md                        # Phase 2 (/speckit-tasks)
```

Sem `contracts/`: nenhuma rota ou interface muda.

### Source Code (repository root)

```text
temba/utils/tests.py               # NOVO: TimezoneParityTest, HamlTemplatesCompileTest
.specify/feature.json              # ponteiro do speckit para esta spec
.cursor/rules/specify-rules.mdc    # ponteiro do agente para este plan.md
```

**Structure Decision**: os testes ficam em `temba/utils/tests.py`, onde já estão `DatesTest`, `TimezonesTest` e os testes de template tags.

## `TimezoneParityTest`

`temba.utils.tests.TimezoneParityTest(TembaTest)`, com um método por função de runtime e um `subTest` por caso. Commits em [research.md](research.md) R6.

**Como o teste obtém o fuso**: um helper `_use_timezone(name)` faz `Org.objects.filter(id=self.org.id).update(timezone=name)`, depois `self.org.refresh_from_db(fields=["timezone"])`, e devolve `self.org.timezone`. Assim, o objeto vem do `TimeZoneField`: `pytz` hoje e `ZoneInfo` na etapa 2, sem mudar o teste ([research.md](research.md) R2). Toda entrada com instante é um literal com `datetime.timezone.utc`. Toda asserção compara texto, `date`, tupla ou inteiro, nunca objeto de fuso.

**Fusos e datas** (constantes da classe):

| Fuso | Data D | O que acontece | Instante de referência T (UTC) |
|---|---|---|---|
| `UTC` | 2026-03-08 e 2026-11-01 | controle | D às 03:00Z |
| `Africa/Kigali` | 2026-03-08 e 2026-11-01 | controle, UTC+2 fixo | D às 03:00Z |
| `America/New_York` | 2026-03-08 | 02:00 local vira 03:00 | 2026-03-08T07:00Z |
| `America/New_York` | 2026-11-01 | 02:00 local vira 01:00 | 2026-11-01T06:00Z |
| `Europe/Dublin` | 2026-03-29 | 01:00 local vira 02:00 | 2026-03-29T01:00Z |
| `Europe/Dublin` | 2026-10-25 | 02:00 local vira 01:00 | 2026-10-25T01:00Z |
| `America/Sao_Paulo` | 2018-11-04 | 00:00 local vira 01:00 (a meia-noite não existe) | 2018-11-04T03:00Z |
| `America/Sao_Paulo` | 2026-11-04 | data atual, UTC−3 fixo | 2026-11-04T03:00Z |

**Horas locais**: 09:00 em todas as datas. Além disso, a hora especial H* de cada transição:

| Fuso e data | H* | Tipo |
|---|---|---|
| `America/New_York` 2026-03-08 | 02:30 | inexistente |
| `America/New_York` 2026-11-01 | 01:30 | ambígua |
| `Europe/Dublin` 2026-03-29 | 01:30 | inexistente |
| `Europe/Dublin` 2026-10-25 | 01:30 | ambígua |
| `America/Sao_Paulo` 2018-11-04 | 00:30 | inexistente |

**Casos por função** (FR-001):

1. **`Schedule.update_schedule` e `Schedule.calculate_next_fire`** (`schedules/models.py:95` e `:150`), método `test_schedules`.
   - Para cada fuso, data D e hora H (09:00 e, quando existir, H*), três schedules: diário, semanal e mensal, criados com `Schedule.create_schedule(self.org, self.admin, start_time, period, days, now=now)`.
   - `start_time` é o instante em que o relógio local marca H no dia de início S, escrito como literal UTC. S fica antes da transição, então essa conversão não é ambígua:
     - diário: S = D − 1;
     - semanal: S = D − 7, com `repeat_days_of_week` igual ao dia da semana de D (`"U"` para todas as datas de domingo, `"W"` para 2026-11-04);
     - mensal: S = mesmo dia do mês anterior. Para Dublin em 2026-03-29, como fevereiro de 2026 não tem dia 29, S = 2026-01-29, e o caso também cobre o disparo ajustado para 28 de fevereiro.
   - Offsets usados para escrever os literais de S: UTC 0; Kigali +2; Nova York −5 (março) e −4 (outubro e novembro); Dublin 0 (janeiro e março) e +1 (setembro e outubro); São Paulo −3.
   - `now = start_time + 1 min`, para que `update_schedule` chame `calculate_next_fire(now)`.
   - Esperado:
     - `repeat_hour_of_day`, `repeat_minute_of_hour`, `repeat_day_of_month` e `repeat_days_of_week`;
     - três disparos seguidos: f1 = `next_fire` depois de `refresh_from_db()`, f2 = `calculate_next_fire(f1)` e f3 = `calculate_next_fire(f2)`;
     - cada disparo em `isoformat()` UTC e em `isoformat()` local via `astimezone(self.org.timezone)`.
   - Total: 45 casos (UTC e Kigali com 6 cada, Nova York e Dublin com 12 cada, São Paulo com 9).
2. **Intervalo de `ExportMessagesTask.write_export`** (`msgs/models.py:1416-1420`), método `test_message_export_range`.
   - Para cada fuso e data D, quatro mensagens de entrada (`create_incoming_msg(..., created_on=...)`), com `created_on` em UTC relativos à janela local W de D:
     - `before`: início de W − 1 s;
     - `first`: início de W;
     - `last`: fim de W, ou seja, 23:59:59 local;
     - `after`: fim de W + 1 s, ou seja, 00:00 local de D + 1.
   - Os instantes de W são os mesmos literais esperados do item 5.
   - `ExportMessagesTask.create(self.org, self.admin, system_label=SystemLabel.TYPE_INBOX, start_date=D, end_date=D)`, depois `write_export()` dentro de `self.mockReadOnly()`, e a planilha é lida com `openpyxl`.
   - Esperado: a lista literal de pares (coluna "Date", coluna "Text"), que hoje deve ser `first` e `last` com a data local ingênua que `prepare_value` grava (`utils/export.py:144`).
   - As quatro mensagens de cada caso são apagadas no fim do caso, para que um caso não entre na janela de outro.
3. **`ContactImport._parse_value`** (`contacts/models.py:2688`), método `test_contact_import_values`.
   - Para cada fuso e data D: `datetime` ingênuo de D às 09:00 e, quando existir, de D em H*, com `tz=org.timezone`. Esperado: o texto `isoformat()` devolvido.
   - Controles, uma vez: um `datetime` com UTC devolve o próprio `isoformat()`; `date(2026, 3, 8)` devolve `"2026-03-08"`; um `datetime` ingênuo com `tz=None` devolve `isoformat()` sem offset.
4. **`datetime_to_str`** (`utils/dates.py:9`), método `test_datetime_to_str`, com a constante `PARITY_FORMAT = "%Y-%m-%d %H:%M:%S %z"`.
   - Para cada fuso e data D, três entradas: a `date` D (caminho do `localize` da meia-noite), T − 30 min e T + 30 min, com UTC.
   - Controle: `None` devolve `None`.
5. **`previous_local_day_window`** (`utils/datalake/layer_validation.py:62`), método `test_previous_local_day_window`.
   - Para cada fuso e data D: `now` = D + 1 às 12:00Z. Nos cinco fusos, a data local desse instante é D + 1.
   - Esperado: a tupla `(D, início, fim)`, com início e fim em texto UTC.
6. **Tag `short_datetime`** (`utils/templatetags/temba.py:211`), método `test_short_datetime`.
   - Contexto `{"user_org": self.org}`, com `org.date_format` em `"D"`, `"M"` e `"Y"`, e `patch.object(timezone, "now", return_value=T + 1 h)`.
   - Entradas: T − 30 min e T + 30 min (ramo de hora, dentro de 12 h) e T − 13 h (ramo de data, com o dia local).
   - Um caso de ano diferente: `America/Sao_Paulo` com `now` = 2026-11-04T04:00Z e `dtime` = 2018-11-04T02:30Z, cuja data local é 2018-11-03.
   - Esperado: o texto devolvido.
7. **Formato de data dos EUA em `OrgCRUDL.Grant.pre_save`** (`orgs/views.py:2935`), método `test_grant_date_format`.
   - Para cada fuso, um POST em `orgs.org_grant` como usuário do grupo `Granters`, com os dados de `test_org_grant` e `timezone=<fuso>` (e-mail e nome distintos por fuso).
   - Esperado: o `date_format` da org criada (literal por fuso) e `str(org.timezone)`.
8. **Gravação de `Org.timezone` em `update_project_config`** (`projects/usecases/project_update.py:59`), método `test_update_project_timezone`.
   - Para cada fuso: `update_project_config(project_uuid=str(self.org.proj_uuid), timezone_location=<fuso>)`.
   - Esperado:
     - o texto gravado, lido com SQL direto (`SELECT timezone FROM orgs_org WHERE id = %s`);
     - `str(Org.objects.get(id=self.org.id).timezone)`;
     - os dois iguais ao nome do fuso.
9. **Lista de fusos de `temba/utils/timezones.py`**, método `test_timezone_choices`.
   - `len(TimeZoneFormField().choices)` contra o literal capturado (433 hoje).
   - Rótulo literal de `UTC`, `Africa/Kigali` e `America/Sao_Paulo`.
   - Rótulo de `America/New_York` em `{"(GMT-0500) America/New_York", "(GMT-0400) America/New_York"}` e de `Europe/Dublin` em `{"(GMT+0000) Europe/Dublin", "(GMT+0100) Europe/Dublin"}`. Esses rótulos são calculados na importação do módulo com `datetime.now()` ([research.md](research.md) R2).
   - Ordem não decrescente pelo offset do rótulo.
   - `str(field.clean(<fuso>)) == <fuso>`.
   - `timezone_to_country_code` contra os literais `""`, `"RW"`, `"US"`, `"IE"` e `"BR"`.
10. **Tag `format_datetime` e `Org.format_datetime`** (`utils/templatetags/temba.py:251` e `orgs/models.py:973`), método `test_format_datetime`.
    - Para cada fuso, data D e `date_format` em `"D"`, `"M"` e `"Y"`: `format_datetime({"user_org": self.org}, dtime)` e `self.org.format_datetime(dtime)`, com `dtime` em T − 30 min e T + 30 min (UTC).
    - Um controle por fuso, em T, com `seconds=True` nas duas chamadas.
    - Esperado: o texto de cada chamada.
11. **`TimezoneMiddleware`** (`middleware.py:162`), método `test_middleware_activates_org_timezone`.
    - Para cada fuso e data D: `RequestFactory().get("/")`, `request.org = self.org`, e `TimezoneMiddleware(get_response)(request)`. O `get_response` renderiza `Template('{{ value|date:"Y-m-d H:i" }}').render(Context({"value": T}))`.
    - Controle, uma vez: `request.org = None` ativa `settings.USER_TIME_ZONE` (`Africa/Kigali`) para o mesmo T de `Africa/Kigali`.
    - `timezone.deactivate()` ao fim de cada caso, para o fuso ativo não vazar.
    - Esperado: o texto renderizado. Esse caso fixa o mecanismo dos filtros `|date` e `|time`. Não renderiza os 61 templates que os usam.
12. **Export de contatos** (`api/v2/internals/contacts/services.py:207`), método `test_contact_download_datetimes`.
    - Para cada fuso e data D: um contato com `created_on = T − 30 min` e `last_seen_on = T + 30 min`, gravados por `update`.
    - Dentro de `self.mockReadOnly()`: `ContactDownloadByStatusService._generate_xlsx_for_contacts(self.org, [contact.id])`. A planilha é lida com `openpyxl`.
    - Esperado: os valores das colunas "Created On" e "Last Seen On". As duas colunas são datas locais ingênuas.
    - O contato é apagado no fim do caso.
13. **`utcoffset` de `FlowCRUDL.Results`** (`flows/views.py:1852`), método `test_flow_results_utcoffset`.
    - `flow = self.get_flow("color_v13")`, como em `temba/flows/tests.py::test_flow_results_with_hidden_results`, e `self.login(self.admin)`.
    - Para cada fuso, data D e instante em T − 30 min e T + 30 min: `patch("temba.flows.views.datetime.now", side_effect=...)`. O `side_effect` recebe o fuso e devolve esse instante convertido com `astimezone`.
    - GET em `reverse("flows.flow_results", args=[flow.uuid])`.
    - Esperado: `response.context["utcoffset"]`, em minutos, com sinal.
14. **Hora local de `validate_layers`** (`utils/datalake/layer_validation.py:119`), método `test_validate_layers_local_hour`.
    - A org de teste ganha `proj_uuid`. `VALIDATION_LOCAL_HOUR` é 2.
    - Para cada linha, um `now` em que a hora local é 2 e outro em que não é:

      | Fuso | `now` selecionado (hora local 2) | `now` não selecionado |
      |---|---|---|
      | `UTC` | 2026-03-08T02:00Z | 2026-03-08T03:00Z |
      | `Africa/Kigali` | 2026-03-08T00:00Z | 2026-03-08T01:00Z |
      | `America/New_York` | 2026-03-09T06:00Z | 2026-03-08T07:30Z (a hora 2 não existe nesse dia) |
      | `America/New_York` | 2026-11-01T07:00Z | 2026-11-01T05:30Z |
      | `Europe/Dublin` | 2026-03-29T01:00Z | 2026-03-29T00:30Z |
      | `Europe/Dublin` | 2026-10-25T02:00Z | 2026-10-25T00:30Z |
      | `America/Sao_Paulo` | 2018-11-04T04:00Z | 2018-11-04T03:30Z |
      | `America/Sao_Paulo` | 2026-11-04T05:00Z | 2026-11-04T06:00Z |

    - `patch` de `temba.utils.datalake.layer_validation._check_project`, para a chamada ao datalake não sair. `validate_layers(now, [str(self.org.proj_uuid)])`.
    - Esperado: no `now` selecionado, uma chamada com o dia e a janela do dia local anterior; no outro, nenhuma chamada.

**Como os valores esperados são calculados e fixados** ([research.md](research.md) R3):

1. O teste é escrito com entradas e esperados vazios no branch, sobre o código atual.
2. Uma alteração temporária, não commitada, imprime `repr()` de cada valor obtido. A suíte do teste roda uma vez.
3. A saída vira os literais (dicionários de constantes por método), e a alteração temporária sai.
4. O revisor confere as transições contra a amostra de [research.md](research.md) R4: dia de 23 h na entrada, de 25 h na saída, lado escolhido nas horas inexistentes e ambíguas.
5. O teste roda de novo, limpo. A descrição do PR registra o commit base e `pytz.__version__`.

Nenhum literal é recalculado no teste. Nenhum literal que pareça "errado" é corrigido: ele registra o comportamento atual (FR-004).

## `HamlTemplatesCompileTest`

`temba.utils.tests.HamlTemplatesCompileTest(TembaTest)`, com um método `test_all_haml_templates_compile` ([research.md](research.md) R5).

**Descoberta**:

1. Diretórios, na ordem dos loaders:
   - `django.template.engines["django"].engine.dirs` (`templates/` e `node_modules/@nyaruka/temba-components/dist/templates`);
   - os diretórios de `django.template.utils.get_app_template_dirs("templates")` dentro de `settings.PROJECT_DIR`, ou seja, os apps de `temba/` (hoje nenhum).
2. Diretório inexistente é ignorado. Em cada diretório, `Path(dir).rglob("*.haml")`, com o nome do template igual ao caminho relativo em POSIX. O primeiro diretório que contém um nome ganha.
3. `frame.haml` e `includes/nav.haml` MUST estar entre os encontrados, para que uma descoberta vazia falhe.

**Verificação**:

- Para cada nome, em `subTest(template=nome)`: `get_template(nome)`, que passa pelos loaders configurados (`temba.utils.haml.HamlFilesystemLoader` primeiro). A asserção é que `template.origin.name` é o arquivo descoberto. Uma exceção falha o `subTest` com o tipo e a mensagem.
- `KNOWN_BROKEN_TEMPLATES: dict[str, str] = {}` (nome → motivo). Hoje vazio: os 345 compilam. Para cada entrada, o teste exige que o template continue falhando, e o template não é corrigido nesta spec (FR-002).

## Rollout e rollback

| Rollout | Rollback |
|---|---|
| merge; só testes, sem deploy funcional | reverter o commit |

## Riscos de implementação

- **Contagem de fusos atrelada ao `pytz`**: o literal 433 vem de `pytz.common_timezones` da 2025.2. Se uma etapa futura trocar a fonte da lista, o teste acusa, que é a intenção (lista igual para o usuário). A 024 não prevê atualizar o `pytz` antes da etapa 2.
- **Achado para a etapa 2**: o `pytz` resolve o horário ambíguo de forma diferente em Nova York e em Dublin ([research.md](research.md) R4). O `TimezoneParityTest` vai acusar Nova York quando o código passar para `zoneinfo`. Registrar na spec da etapa 2.

## Complexity Tracking

Sem violações da constitution a justificar.
