---

description: "Task list for 025-django-upgrade-stage0"
---

# Tasks: etapa 0 do upgrade do Django, parte 1 — testes de proteção

**Input**: `specs/025-django-upgrade-stage0/` ([spec.md](spec.md), [plan.md](plan.md), [research.md](research.md), [data-model.md](data-model.md), [quickstart.md](quickstart.md))

**Tests**: são a própria entrega. Os testes passam contra o código atual, sem nenhuma outra mudança de código.

**Organization**: uma única user story (US1) e um único PR. Não há fase Foundational.

**Checkpoint** (gate de merge do PR):

```sh
poetry run coverage run manage.py test --keepdb --noinput   # suíte verde nos quatro grupos
./code_check.py                                              # "Code looks good"
poetry run python manage.py makemigrations --check --dry-run # sem saída
```

Também valem: nenhum `# pragma: no cover` novo, nenhum teste pulado, nenhuma asserção existente alterada e nenhum arquivo alterado fora de `temba/utils/tests.py`, dos documentos de `specs/024-django-5-2-upgrade/` e `specs/025-django-upgrade-stage0/`, `.specify/feature.json` e `.cursor/rules/specify-rules.mdc` (FR-005). Esses dois só podem mudar o ponteiro para esta spec.

**Fora de escopo**: tudo das specs 026 a 028 (trocas de API, filtro de avisos, logout por POST, remoção de `csv_imports`) e das etapas 1 a 3 da 024. Nenhum código de produção, template, setting, dependência, migration ou changelog.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: pode rodar em paralelo (arquivo diferente, sem dependência pendente)
- **[Story]**: US1, conforme [spec.md](spec.md)

---

## Phase 1: Setup

**Purpose**: linha de base antes dos testes.

- [ ] T001 Em `main`, rodar o checkpoint (suíte, `./code_check.py` e `makemigrations --check`) e registrar o resultado. Uma falha aqui é anterior a esta spec e não é corrigida por ela. Falhas que dependem de serviço local (por exemplo, os testes `test_trigger_flow_uuid_*` sem Mailroom rodando) são registradas como do ambiente e conferidas no CI.
- [ ] T002 [P] Registrar o ambiente que gera os literais: o hash do commit base de `main`, `poetry run python -c "import pytz; print(pytz.__version__)"` (esperado `2025.2`) e `django.get_version()` (esperado `3.2.25`). Esses valores entram na descrição do PR (FR-004, `specs/025-django-upgrade-stage0/research.md` R3).

**Checkpoint**: linha de base registrada.

---

## Phase 2: User Story 1 — testes de proteção (Priority: P1) 🎯 MVP

**Goal**: o comportamento atual de fuso horário e a compilação de todos os templates HAML ficam fixados por testes (D-1, D-2, FR-001 a FR-004).

**Independent Test**: `poetry run python manage.py test temba.utils.tests.TimezoneParityTest temba.utils.tests.HamlTemplatesCompileTest --keepdb` passa no código atual. A guarda de diff do [quickstart.md](quickstart.md) só lista `temba/utils/tests.py`.

**Regra da fase**: nenhum arquivo de código fora de `temba/utils/tests.py` muda. O teste não importa `pytz` nem `zoneinfo`, e toda entrada com instante é literal com `datetime.timezone.utc` (FR-003, `specs/025-django-upgrade-stage0/research.md` R2).

- [ ] T003 [US1] Em `temba/utils/tests.py`, criar `class TimezoneParityTest(TembaTest)` logo depois de `TimezonesTest`, com:
  - imports novos no topo do arquivo: `Schedule` (`temba.schedules.models`), `ExportMessagesTask`, `Msg` e `SystemLabel` (`temba.msgs.models`), `ContactImport` (`temba.contacts.models`), `Org` (`temba.orgs.models`), `previous_local_day_window` e `validate_layers` (`temba.utils.datalake.layer_validation`), `update_project_config` (`temba.projects.usecases.project_update`), `TimezoneMiddleware` (`temba.middleware`), `ContactDownloadByStatusService` (`temba.api.v2.internals.contacts.services`), `RequestFactory` (`django.test`) e `Template` e `Context` (`django.template`). `connection` (`django.db`) e `format_datetime` (`temba.utils.templatetags.temba`) já estão importados e não são duplicados;
  - constantes de classe: `ZONES`, as datas por fuso e o instante de referência T de cada `(fuso, data)`, conforme a tabela "Fusos e datas" do `specs/025-django-upgrade-stage0/plan.md`; `SPECIAL_LOCAL_TIMES` com as cinco horas inexistentes ou ambíguas; `REGULAR_LOCAL_TIME = (9, 0)`; `PARITY_FORMAT = "%Y-%m-%d %H:%M:%S %z"`;
  - helper `_use_timezone(self, name)`: `Org.objects.filter(id=self.org.id).update(timezone=name)`, depois `self.org.refresh_from_db(fields=["timezone"])`, e devolve `self.org.timezone`;
  - helper `_utc(dt)` que devolve `dt.astimezone(datetime.timezone.utc).isoformat()`, e `_local(dt)` que devolve `dt.astimezone(self.org.timezone).isoformat()`.
- [ ] T004 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_schedules`: os 45 casos do item 1 do `plan.md`.
  - Para cada fuso, data D e hora H (09:00 e, quando existir, H*), três schedules (`Schedule.REPEAT_DAILY`, `REPEAT_WEEKLY`, `REPEAT_MONTHLY`), cada um com `Schedule.create_schedule(self.org, self.admin, start_time, period, days, now=now)` dentro de `subTest(zone=..., date=..., period=..., hour=...)`.
  - `start_time` é um literal UTC escrito com o offset de antes da transição. O dia de início é D − 1 (diário), D − 7 (semanal, com `days` igual ao dia da semana de D: `"U"` aos domingos e `"W"` em 2026-11-04) e o mesmo dia do mês anterior (mensal; 2026-01-29 para Dublin em 2026-03-29).
  - `now = start_time + timedelta(minutes=1)`.
  - Obtidos: `repeat_hour_of_day`, `repeat_minute_of_hour`, `repeat_day_of_month` e `repeat_days_of_week`; f1 = `next_fire` depois de `schedule.refresh_from_db()`, f2 = `schedule.calculate_next_fire(f1)` e f3 = `schedule.calculate_next_fire(f2)`, cada um com `_utc` e `_local`.
  - Comparar contra `EXPECTED_SCHEDULES`, um dicionário de classe vazio até T017.
- [ ] T005 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_message_export_range` (item 2 do `plan.md`).
  - Para cada fuso e data D: um contato, e quatro mensagens com `self.create_incoming_msg(contact, text, created_on=...)`, de textos `before`, `first`, `last` e `after`, com `created_on` em UTC iguais a início − 1 s, início, fim e fim + 1 s da janela esperada de `previous_local_day_window` para D (os mesmos literais de T008).
  - `task = ExportMessagesTask.create(self.org, self.admin, system_label=SystemLabel.TYPE_INBOX, start_date=D, end_date=D)`; `with self.mockReadOnly(): temp, _ = task.write_export()`; ler `load_workbook(temp.name).worksheets[0]` e coletar `(Date, Text)` das linhas depois do cabeçalho.
  - Apagar as quatro mensagens e o contato no fim do caso.
  - Comparar contra `EXPECTED_EXPORT_ROWS` (vazio até T017).
- [ ] T006 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_contact_import_values` (item 3 do `plan.md`).
  - Para cada fuso e data D: `ContactImport._parse_value(datetime(D, 09:00), tz=tz)` e, quando existir, com H*, sempre com `datetime` ingênuo.
  - Controles, uma vez: um `datetime` com `datetime.timezone.utc`, `date(2026, 3, 8)` e um `datetime` ingênuo com `tz=None`.
  - Comparar contra `EXPECTED_IMPORT_VALUES` (vazio até T017).
- [ ] T007 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_datetime_to_str` (item 4 do `plan.md`).
  - Para cada fuso e data D: `datetime_to_str(D, PARITY_FORMAT, tz)`, `datetime_to_str(T - 30 min, ...)` e `datetime_to_str(T + 30 min, ...)`, com T em UTC.
  - Controle: `datetime_to_str(None, PARITY_FORMAT, tz)` é `None`.
  - Comparar contra `EXPECTED_DATETIME_STR` (vazio até T017).
- [ ] T008 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_previous_local_day_window` (item 5 do `plan.md`): para cada fuso e data D, `previous_local_day_window(datetime(D + 1, 12, 0, tzinfo=datetime.timezone.utc), tz)`. Comparar a tupla `(date, início, fim)` contra `EXPECTED_DAY_WINDOWS` (vazio até T017).
- [ ] T009 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_short_datetime` (item 6 do `plan.md`).
  - Para cada fuso, data D e `date_format` em `"D"`, `"M"` e `"Y"` (gravado na org): `with patch.object(timezone, "now", return_value=T + 1 h)`, e `short_datetime({"user_org": self.org}, dtime)` para `dtime` em T − 30 min, T + 30 min e T − 13 h.
  - Caso de ano diferente: `America/Sao_Paulo`, `now` = 2026-11-04T04:00Z e `dtime` = 2018-11-04T02:30Z.
  - Comparar contra `EXPECTED_SHORT_DATETIME` (vazio até T017).
- [ ] T010 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_grant_date_format` (item 7 do `plan.md`).
  - Criar um usuário no grupo `Granters`, como em `temba/orgs/tests.py::test_org_grant`, e `self.login(...)` com ele.
  - Para cada fuso, um POST em `reverse("orgs.org_grant")` com os campos de `test_org_grant`, e-mail e nome distintos por fuso e `timezone=<fuso>`.
  - Obtidos, da org criada: `date_format` e `str(org.timezone)`. Comparar contra `EXPECTED_GRANT` (vazio até T017).
- [ ] T011 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_update_project_timezone` e `test_timezone_choices` (itens 8 e 9 do `plan.md`):
  - `test_update_project_timezone`: gravar um `proj_uuid` em `self.org`. Para cada fuso, `update_project_config(project_uuid=str(self.org.proj_uuid), timezone_location=<fuso>)`. Asserções: o texto lido com `connection.cursor()` e `SELECT timezone FROM orgs_org WHERE id = %s` e `str(Org.objects.get(id=self.org.id).timezone)` são o nome do fuso.
  - `test_timezone_choices`, com `field = TimeZoneFormField()`:
    - `len(field.choices)` contra `EXPECTED_CHOICES_COUNT`;
    - o rótulo literal de `UTC`, `Africa/Kigali` e `America/Sao_Paulo`;
    - o rótulo de `America/New_York` em `{"(GMT-0500) America/New_York", "(GMT-0400) America/New_York"}` e o de `Europe/Dublin` em `{"(GMT+0000) Europe/Dublin", "(GMT+0100) Europe/Dublin"}`;
    - os offsets dos rótulos em ordem não decrescente;
    - `str(field.clean(<fuso>)) == <fuso>`;
    - `timezone_to_country_code(self._use_timezone(<fuso>))` contra `EXPECTED_COUNTRY_CODES`.
- [ ] T012 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_format_datetime` (item 10 do `plan.md`).
  - Para cada fuso, data D e `date_format` em `"D"`, `"M"` e `"Y"`: `format_datetime({"user_org": self.org}, dtime)` e `self.org.format_datetime(dtime)`, com `dtime` em T − 30 min e T + 30 min.
  - Um controle por fuso, em T, com `seconds=True` nas duas chamadas.
  - Comparar contra `EXPECTED_FORMAT_DATETIME` (vazio até T017).
- [ ] T013 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_middleware_activates_org_timezone` (item 11 do `plan.md`).
  - Para cada fuso e data D: `RequestFactory().get("/")`, `request.org = self.org` e `TimezoneMiddleware(get_response)(request)`. O `get_response` renderiza `Template('{{ value|date:"Y-m-d H:i" }}').render(Context({"value": T}))`.
  - Controle, uma vez: `request.org = None`, que ativa `settings.USER_TIME_ZONE` (`Africa/Kigali`).
  - `timezone.deactivate()` ao fim de cada caso.
  - Comparar contra `EXPECTED_MIDDLEWARE_DATES` (vazio até T017).
- [ ] T014 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_contact_download_datetimes` (item 12 do `plan.md`).
  - Para cada fuso e data D: um contato com `created_on = T − 30 min` e `last_seen_on = T + 30 min`.
  - Dentro de `self.mockReadOnly()`: `ContactDownloadByStatusService._generate_xlsx_for_contacts(self.org, [contact.id])`. Ler "Created On" e "Last Seen On" com `load_workbook`.
  - Apagar o contato no fim do caso.
  - Comparar contra `EXPECTED_CONTACT_EXPORT` (vazio até T017).
- [ ] T015 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_flow_results_utcoffset` (item 13 do `plan.md`).
  - `flow = self.get_flow("color_v13")` e `self.login(self.admin)`, como em `temba/flows/tests.py::test_flow_results_with_hidden_results`.
  - Para cada fuso, data D e instante em T − 30 min e T + 30 min: `patch("temba.flows.views.datetime.now", side_effect=...)`, em que o `side_effect` recebe o fuso e devolve o instante convertido com `astimezone`.
  - GET em `reverse("flows.flow_results", args=[flow.uuid])` e ler `response.context["utcoffset"]`.
  - Comparar contra `EXPECTED_UTCOFFSET` (vazio até T017).
- [ ] T016 [US1] Em `temba/utils/tests.py`, `TimezoneParityTest.test_validate_layers_local_hour` (item 14 do `plan.md`).
  - Gravar `proj_uuid` em `self.org`. Para cada linha da tabela do item 14, chamar `validate_layers(now, [str(self.org.proj_uuid)])` com `patch` de `temba.utils.datalake.layer_validation._check_project`.
  - No `now` de hora local 2, uma chamada com dia e janela. No outro, nenhuma.
  - Comparar contra `EXPECTED_LAYER_HOUR` (vazio até T017).
- [ ] T017 [US1] Capturar e fixar os literais em `temba/utils/tests.py` (`specs/025-django-upgrade-stage0/research.md` R3):
  1. Acrescentar, sem commitar, um `print(repr(...))` do valor obtido em cada `subTest`.
  2. Rodar `poetry run python manage.py test temba.utils.tests.TimezoneParityTest --keepdb`.
  3. Copiar a saída para `EXPECTED_SCHEDULES`, `EXPECTED_EXPORT_ROWS`, `EXPECTED_IMPORT_VALUES`, `EXPECTED_DATETIME_STR`, `EXPECTED_DAY_WINDOWS`, `EXPECTED_SHORT_DATETIME`, `EXPECTED_GRANT`, `EXPECTED_CHOICES_COUNT`, `EXPECTED_COUNTRY_CODES`, `EXPECTED_FORMAT_DATETIME`, `EXPECTED_MIDDLEWARE_DATES`, `EXPECTED_CONTACT_EXPORT`, `EXPECTED_UTCOFFSET` e `EXPECTED_LAYER_HOUR`.
  4. Remover os `print` e rodar de novo: passa.

  Nenhum valor esperado é calculado dentro do teste (FR-004).
- [ ] T018 [US1] Revisar os literais de `temba/utils/tests.py` contra a amostra de `specs/025-django-upgrade-stage0/research.md` R4: dia local de 23 h na entrada do horário de verão, de 25 h na saída e de 24 h nos controles; `-05:00` no ambíguo de Nova York e `+01:00` no de Dublin; `2018-11-04 01:00 -0200` para a meia-noite de São Paulo; 433 opções. Os literais novos (T012 a T016) usam o mesmo offset da amostra para o mesmo instante. Um literal que pareça errado não é corrigido. Ele é anotado na descrição do PR como comportamento atual.
- [ ] T019 [US1] Em `temba/utils/tests.py`, criar `class HamlTemplatesCompileTest(TembaTest)` logo depois de `TimezoneParityTest`, com `test_all_haml_templates_compile` (`specs/025-django-upgrade-stage0/research.md` R5):
  - diretórios: `django.template.engines["django"].engine.dirs` e os de `django.template.utils.get_app_template_dirs("templates")` dentro de `settings.PROJECT_DIR`, nessa ordem, ignorando os inexistentes;
  - arquivos: `Path(dir).rglob("*.haml")`, com o nome do template igual ao caminho relativo em POSIX e o primeiro diretório ganhando;
  - asserção de que `"frame.haml"` e `"includes/nav.haml"` estão entre os nomes encontrados;
  - para cada nome fora de `KNOWN_BROKEN_TEMPLATES`, em `subTest(template=nome)`: `get_template(nome)`, e a asserção de que `Path(template.origin.name)` é o arquivo descoberto. Uma exceção falha o `subTest` com tipo e mensagem;
  - `KNOWN_BROKEN_TEMPLATES: dict[str, str] = {}` como constante da classe. Para cada entrada, a asserção de que `get_template` ainda levanta exceção.
- [ ] T020 [US1] Provar manualmente que os testes de `temba/utils/tests.py` acusam regressão, sem commitar (`specs/025-django-upgrade-stage0/quickstart.md`, "Prova de que os testes acusam regressão"):
  - `is_dst=True` no `tz.localize(value)` de `temba/contacts/models.py:2696` faz o caso ambíguo de `America/New_York` falhar;
  - uma tag inexistente num `.haml` faz o `HamlTemplatesCompileTest` falhar com o nome do arquivo.

  Reverter as duas mudanças. Elas não ficam no diff. O que restar no status é só o que a FR-005 permite.
- [ ] T021 [US1] Rodar as três guardas do `quickstart.md`: a de diff (só `temba/utils/tests.py`, além de `specs/024-django-5-2-upgrade/`, `specs/025-django-upgrade-stage0/`, `.specify/feature.json` e `.cursor/rules/specify-rules.mdc`), a de `pragma` e `skip` restrita a `temba/`, e a do corpo de `TimezoneParityTest` (`pytz`, `zoneinfo`, `.zone`, `.key`, `.dst(`, `isinstance(` e `repr(`). Commits (`research.md` R6): `test: pin timezone behaviour with parity test` (T003 a T018) e `test: compile every haml template` (T019).
- [ ] T022 [US1] Preparar o texto da descrição do PR, sem abrir o PR nem fazer push: ciclo SDD Full; AC-1 a AC-4 e FR-001 a FR-005 cobertos; sem migration; sem changelog (só testes, `research.md` R6); commit base e versões de `pytz` e Django (T002); literais anotados (T018); rollback: reverter o commit.

**Checkpoint**: suíte verde, `./code_check.py` limpo e `makemigrations --check` sem pendências. Os dois testes novos passam contra o código atual, sem nenhuma outra mudança de código.

---

## Phase 3: Fechamento

**Purpose**: merge e registro na 024. Nada aqui abre as specs 026 a 028.

- [ ] T023 Merge depois do checkpoint da Phase 2. Não há validação funcional em staging (só testes).
- [ ] T024 Depois do merge, atualizar a linha da 025 na tabela "Etapas e specs filhas" de `specs/024-django-5-2-upgrade/spec.md` para `em main desde AAAA-MM-DD` e o `Status` de `specs/025-django-upgrade-stage0/spec.md` para `Implemented`. Essa atualização entra no PR da `026-django-upgrade-stage0-removed-apis`, que é o próximo da etapa.

**Checkpoint**: 025 em `main`, e a 026 liberada para `/speckit-plan`.

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: sem dependência.
- **US1 (Phase 2)**: depende da Phase 1. T003 → T004…T016 (mesmo arquivo, em sequência) → T017 → T018; T019 depois de T003; T020, T021 e T022 no fim.
- **Fechamento (Phase 3)**: depende do merge.

### Parallel Opportunities

- T001 e T002, na Phase 1.
- Na Phase 2, tudo é no mesmo arquivo, então não há paralelismo real.

---

## Implementation Strategy

1. Phase 1 e Phase 2.
2. **Parar e validar**: os dois testes passam no código atual, e a guarda de diff só lista `temba/utils/tests.py`.
3. Merge. Não muda nada em produção, e passa a proteger as specs 026 a 028 e a etapa 2 da 024.

---

## Notes

- Nenhum `print` de captura (T017) e nenhuma mudança de prova (T020) entra em commit.
