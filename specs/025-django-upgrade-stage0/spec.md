# Engineering Spec: etapa 0 do upgrade do Django, parte 1 — testes de proteção

**Repository**: weni-ai/flows — backend

**Feature Branch**: `chore/django-upgrade-stage0`

**Created**: 2026-11-27

**Status**: Draft

**Input**: Primeira das quatro specs da etapa 0 da spec guarda-chuva [024-django-5-2-upgrade](../024-django-5-2-upgrade/spec.md): escrever, ainda no Django 3.2 e antes de qualquer outra mudança, os testes que fixam o comportamento atual de fuso horário e a compilação dos templates HAML. Eles protegem as outras specs da etapa 0 e as etapas 1 a 3.

**Cycle**: SDD Full. O código de produção muda num único arquivo de teste, mas o teste exercita `schedules`, `msgs`, `contacts`, `orgs`, `projects`, `flows`, `api` e `temba.middleware`, e os casos que ele fixa são os que a etapa 2 da 024 usa sem alteração. O [plan.md](plan.md) detalha o "como". Os demais gatilhos não se aplicam: sem migration, sem dependência, sem contrato público, sem Courier ou Mailroom e sem tipo de canal.

## Etapa 0 em quatro specs

Cada PR integrado em `main` tem a sua spec (024 FR-001). A etapa 0 é entregue por quatro specs, nesta ordem:

| Spec | PR | Depende de |
|------|----|------------|
| **025** (esta) | `TimezoneParityTest` e `HamlTemplatesCompileTest` | — |
| `026-django-upgrade-stage0-removed-apis` | APIs removidas no Django 4.0 e filtro de avisos | 025 em `main` |
| `027-django-upgrade-stage0-post-logout` | logout por POST | 026 em `main` |
| `028-django-upgrade-stage0-remove-csv-imports` | remoção do `smartmin.csv_imports` | 026 em `main` |

Os nomes das specs 026 a 028 ficam em texto, sem link. Os arquivos delas entram no PR de cada uma (024, regra das specs filhas) e ainda não existem em `main`.

O status de cada uma fica na tabela "Etapas e specs filhas" da 024.

## Origin Without Product Spec

- Product Spec: none
- Contexto: etapa 0 da spec 024 (D-2). Esta spec cobre as FR-012 e FR-021 da 024. As demais FR da etapa 0 ficam nas specs 026 a 028.
- Problem: Não existem testes que mostrem se o comportamento de fuso horário e a compilação dos templates HAML continuam iguais depois das trocas de API da spec 026 e das etapas 1 a 3 da 024 (Django 4.2, troca de `pytz` por `zoneinfo`, Django 5.2 e fork do `django-hamlpy`).
- Acceptance criteria:
  - AC-1: O comportamento atual de fuso horário de cada ponto de runtime da FR-001 fica fixado em valores literais, calculados pelo código atual. Teste: `temba.utils.tests.TimezoneParityTest` (novo), que passa contra o código atual.
  - AC-2: Todo template HAML dos diretórios de template configurados compila com os loaders do projeto. Teste: `temba.utils.tests.HamlTemplatesCompileTest` (novo).
  - AC-3: Os quatro grupos de `.github/workflows/ci.yml` ficam verdes, sem nenhum teste pulado e sem nenhum `# pragma: no cover` novo, e nenhum código de produção muda. Teste: execução do workflow no PR e a guarda de diff do [quickstart.md](quickstart.md) (FR-005).
  - AC-4: `./code_check.py` termina limpo, inclusive `makemigrations --check`.

## Decisões de implementação

### D-1: testes de proteção primeiro, com valores calculados pelo código atual

O `TimezoneParityTest` e o `HamlTemplatesCompileTest` entram antes de qualquer outra mudança da etapa 0 e passam contra o código atual. Os valores esperados de paridade são calculados rodando o código atual (com `pytz`) e fixados no teste como literais. Eles não são recalculados no teste, para que a etapa 2 da 024 os use sem alteração.

### D-2: o teste de paridade não depende de `pytz` nem de `zoneinfo`

O teste obtém o objeto de fuso pelo próprio `Org.timezone` (`TimeZoneField`), gravando o nome do fuso na org e recarregando o campo do banco. Assim, o mesmo código de teste recebe `pytz` nas etapas 0 e 1 e `ZoneInfo` na etapa 2, conforme `USE_DEPRECATED_PYTZ`. As asserções comparam só texto, datas, tuplas e inteiros, nunca objetos de fuso.

Alternativa rejeitada: construir os fusos no teste com `pytz.timezone(...)`. Obrigaria a mudar o teste na etapa 2, que é o que a FR-012 da 024 proíbe.

## Escopo neste repositório

**Muda**:

- `temba/utils/tests.py`: `TimezoneParityTest` e `HamlTemplatesCompileTest`.
- `specs/024-django-5-2-upgrade/` e `specs/025-django-upgrade-stage0/`: este é o primeiro PR da etapa 0, e leva a spec guarda-chuva junto.
- `.specify/feature.json` e `.cursor/rules/specify-rules.mdc`: só apontam esta spec para as ferramentas do speckit. Nenhum comportamento do Flows muda.

**Não muda**:

- Nenhum código de produção, template, setting, dependência, migration ou arquivo de `locale/`.
- `WENI-CHANGELOG.md`: o PR só acrescenta testes e não tem mudança visível (Principle VIII).
- Um template HAML que já falha hoje não é corrigido aqui (FR-002).

## User Scenarios & Testing *(mandatory)*

Quem usa esta mudança: os desenvolvedores das próximas specs da etapa 0 e das etapas 1 a 3, que precisam de testes que acusem regressão de fuso e de templates. Os usuários do Flows não percebem nada.

### User Story 1 - Comportamento de fuso e templates fixado por testes (Priority: P1)

Antes de qualquer troca, a suíte passa a registrar como o código atual converte datas por fuso e se todos os templates HAML compilam.

**Why this priority**: É a rede de segurança das specs 026 a 028 e da etapa 2 da 024, e não muda nada em produção.

**Independent Test**: os dois testes novos passam contra o código atual, e o diff fora de `specs/` só toca `temba/utils/tests.py`.

**Acceptance Scenarios**:

1. **Given** o código atual com `pytz`, **When** o `TimezoneParityTest` roda, **Then** cada caso da FR-001 bate com o literal fixado.
2. **Given** todos os arquivos `.haml` dos diretórios de template configurados, **When** o `HamlTemplatesCompileTest` roda, **Then** cada um compila com os loaders do projeto, exceto os listados na FR-002 com o motivo.
3. **Given** uma mudança de comportamento de fuso (por exemplo, `is_dst=True` no `localize` de `ContactImport._parse_value`), **When** o `TimezoneParityTest` roda, **Then** o caso afetado falha.

### Edge Cases

- **Template que já não compila hoje**: a FR-002 manda listar o arquivo como exceção explícita no teste, com o motivo. O template não é corrigido nesta spec.
- **Brasil sem horário de verão desde 2019**: os casos de `America/Sao_Paulo` incluem uma data atual e uma transição histórica (2018-11-04, quando a meia-noite local não existiu), porque `pytz` e `zoneinfo` carregam o histórico.
- **Rótulos da lista de fusos dependem da data**: os rótulos de `temba/utils/timezones.py` são montados na importação do módulo com `datetime.now()`. Para fusos com horário de verão, o teste aceita os dois offsets possíveis.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: MUST existir `temba.utils.tests.TimezoneParityTest` (024 FR-012), com valores esperados literais calculados pelo código atual, cobrindo os pontos de runtime que aplicam fuso diferente de UTC:
  - `Schedule.update_schedule` e `Schedule.calculate_next_fire` (`schedules/models.py:95` e `:150`), para repetição diária, semanal e mensal;
  - o intervalo de datas de `ExportMessagesTask.write_export` (`msgs/models.py:1416-1420`), verificando quais mensagens entram e quais ficam fora nas bordas do dia local;
  - `ContactImport._parse_value` (`contacts/models.py:2688`);
  - `datetime_to_str` (`utils/dates.py:9`);
  - `previous_local_day_window` (`utils/datalake/layer_validation.py:62`);
  - a tag `short_datetime` (`utils/templatetags/temba.py:211`);
  - a regra de formato de data dos EUA em `OrgCRUDL.Grant.pre_save` (`orgs/views.py:2935`, que usa `timezone.zone`);
  - a gravação de `Org.timezone` em `update_project_config` (`projects/usecases/project_update.py:59`);
  - a lista de fusos de `temba/utils/timezones.py`;
  - a tag `format_datetime` (`utils/templatetags/temba.py:251`) e `Org.format_datetime` (`orgs/models.py:973`), que a tag chama quando há org;
  - `TimezoneMiddleware` (`middleware.py:162`), que faz `timezone.activate(request.org.timezone)` e é o que os filtros `|date` e `|time` dos templates usam;
  - a conversão de `created_on` e `last_seen_on` em `ContactDownloadByStatusService._generate_xlsx_for_contacts` (`api/v2/internals/contacts/services.py:207`);
  - o `utcoffset` de `FlowCRUDL.Results.get_context_data` (`flows/views.py:1852`);
  - a seleção por hora local de `validate_layers` (`utils/datalake/layer_validation.py:119`, `VALIDATION_LOCAL_HOUR`).

  Esta lista é o inventário completo. Ficam de fora as conversões cujo fuso é UTC, porque UTC não muda entre `pytz` e `zoneinfo`, e os comandos de management que só montam banco local (`test_db`, `mailroom_db`): o `format_datetime` e o `astimezone` que eles chamam já estão no inventário. Os fusos MUST incluir `UTC`, `America/Sao_Paulo`, `Africa/Kigali`, `America/New_York` e `Europe/Dublin`, e as datas MUST incluir as transições de 2026 (EUA em 2026-03-08 e 2026-11-01; Irlanda em 2026-03-29 e 2026-10-25) e a de 2018-11-04 em `America/Sao_Paulo`.
- **FR-002**: MUST existir `temba.utils.tests.HamlTemplatesCompileTest` (024 FR-021). Ele carrega com `django.template.loader.get_template` todo arquivo `.haml` de `templates/` e dos diretórios `templates/` dos apps de `temba/`, e falha se algum lançar erro. Um template que já falha no commit base MUST aparecer numa lista explícita de exceções no próprio teste, com o motivo, e MUST NOT ser corrigido nesta spec.
- **FR-003**: O `TimezoneParityTest` MUST NOT importar `pytz` nem `zoneinfo` nem comparar objetos de fuso. Ele MUST obter o fuso pelo `Org.timezone` e comparar só texto, datas, tuplas e inteiros (D-2).
- **FR-004**: Nenhum valor esperado MUST ser recalculado dentro do teste. Um valor que pareça errado MUST NOT ser corrigido: ele registra o comportamento atual e é anotado na descrição do PR, junto com o commit base e as versões de `pytz` e do Django usadas na captura.
- **FR-005**: O PR MUST NOT alterar nenhum arquivo fora de `temba/utils/tests.py`, `specs/024-django-5-2-upgrade/`, `specs/025-django-upgrade-stage0/`, `.specify/feature.json` e `.cursor/rules/specify-rules.mdc`. Os dois últimos só podem mudar o ponteiro para esta spec.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Os dois testes novos passam no código atual, nos quatro grupos do CI, com zero testes pulados e zero `# pragma: no cover` novos.
- **SC-002**: A lista de exceções do `HamlTemplatesCompileTest` fica vazia, ou cada entrada tem o motivo.
- **SC-003**: As specs 026 a 028 chegam a `main` sem alterar nenhum valor esperado dos dois testes.

## Peak Load (Principle XII)

Não se aplica. A mudança só acrescenta testes e não altera nenhum caminho de runtime.

## Assumptions

- O `pytz` instalado pelo `poetry.lock` (2025.2) é o mesmo em todos os ambientes de teste. Uma base de fusos diferente poderia mudar os literais históricos, por isso a descrição do PR registra a versão (FR-004).
- O banco de teste do CI aceita as operações que o teste faz (criar schedules, mensagens, exports e orgs), como os testes atuais desses apps.

## Test Strategy

**Testes novos**:

| Teste | Cobre |
|-------|-------|
| `temba.utils.tests.TimezoneParityTest` | AC-1, FR-001, FR-003, FR-004 |
| `temba.utils.tests.HamlTemplatesCompileTest` | AC-2, FR-002 |

**Testes existentes que fecham os critérios**: a suíte completa nos quatro grupos (AC-3).

**Comandos**:

```sh
poetry run python manage.py test temba.utils.tests.TimezoneParityTest temba.utils.tests.HamlTemplatesCompileTest --keepdb
poetry run coverage run manage.py test --keepdb --noinput
poetry run python manage.py makemigrations --check --dry-run
./code_check.py
```

## Rollout and Rollback

Merge sem validação funcional em staging, porque o PR só acrescenta testes. O rollback é reverter o commit.

## Constitution Alignment

Revisão no nível da spec. O Constitution Check formal do ciclo SDD Full está no [plan.md](plan.md). O preset `vtex-cx-engineering` não está instalado (TODO SPECKIT_PRESET), por isso esta seção e a Test Strategy foram escritas à mão.

| Princípio | Como esta mudança cumpre |
|-----------|--------------------------|
| I. Version Control and Review | Um PR com review e CI verde, com spec própria (024 FR-001). |
| II. Security and Secrets | Nenhuma dependência nova. Nenhum segredo. |
| III. Observability | Não se aplica: nenhum log ou métrica muda. |
| IV. Versioned Contracts | Nenhum contrato muda. Sem migration. |
| V. Specification Traceability | Abre com `## Origin Without Product Spec`, cita a 024 como contexto, e cada AC aponta para um teste. |
| VI. No Silent Divergence | Não se aplica: não há Product Spec. As FR-012 e FR-021 da 024 estão cobertas pelas FR-001 e FR-002. |
| VII. Commit Messages | `test: pin timezone behaviour with parity test` e `test: compile every haml template`. |
| VIII. Changelog Maintenance | Sem entrada: só testes, sem mudança visível. |
| IX. Never Trust the Client | Não se aplica. |
| X. Fail Gracefully | Não se aplica. |
| XI. Bounded Retry | Não se aplica. |
| XII. Scalability and Peak Load | Peak Load não aplicável, com o motivo. |
| XIII. Diagnosable Errors | Cada caso roda em `subTest` com o fuso, a data e a função, e uma falha de template mostra o nome do arquivo. |
| XIV. Tests Exercise Flows | O teste de paridade passa pelos fluxos reais (`create_schedule`, `write_export`, a view de `Grant`, `update_project_config`, a tag `format_datetime`, o `TimezoneMiddleware` com o filtro `|date`, o export de contatos, a view `flows.flow_results` e `validate_layers`), e não por funções isoladas. |
| XV. Explicit Over Clever | Fusos, datas, formato e valores esperados são constantes nomeadas da classe. |
| XVI. Contained Changes | No código do Flows, só `temba/utils/tests.py` muda. `.specify/feature.json` e `.cursor/rules/specify-rules.mdc` só apontam esta spec (FR-005). |
| XVII. Explicit, Scoped Authorization | Não se aplica: nenhuma permissão muda. |
