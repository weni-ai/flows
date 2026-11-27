# Research: etapa 0 do upgrade do Django, parte 1 — testes de proteção

**Feature**: `025-django-upgrade-stage0` | **Date**: 2026-11-27 | **Plan**: [plan.md](plan.md)

Este documento cobre só o "como". Requisitos, decisões D-1 e D-2 e escopo vêm da [spec](spec.md) e não são rediscutidos aqui. Os levantamentos abaixo foram feitos no commit `fcf408e0c` (o `9bb192176` mais a troca de `.specify/feature.json`), com Django 3.2.25, smartmin 3.1.0, django-hamlpy 1.7.0, django-timezone-field 5.1, pytz 2025.2 e tzdata 2025.3 instalados pelo `poetry.lock`.

A pesquisa das outras partes da etapa 0, feita no mesmo plano antes da divisão em quatro specs, fica com as specs `026-django-upgrade-stage0-removed-apis` (trocas mecânicas e filtro de avisos), `027-django-upgrade-stage0-post-logout` (logout) e `028-django-upgrade-stage0-remove-csv-imports` (`csv_imports`). Os arquivos entram no PR de cada uma e não são linkados daqui.

## R1. Requisitos da 024 cobertos por esta spec

- **Decision**: esta spec cobre as FR-012 e FR-021 da 024 e, do conjunto geral, as FR-001 a FR-003 e a FR-025. A tabela "Rastreabilidade com a 024" do [plan.md](plan.md) liga cada um a uma verificação.
- **Rationale**: a 024 diz que os requisitos marcados para uma etapa são o mínimo das specs filhas dessa etapa. Na etapa 0, as FR-006 e FR-019 ficam com a 026, a FR-008 com a 027 e a FR-007 com a 028. A FR-020 (smoke em staging) não se aplica aqui, porque o PR não muda runtime. A FR-004 (dependências) e a FR-005 (`sentry-sdk`) valem trivialmente: nenhuma dependência muda.
- **Alternatives considered**: nenhuma.

## R2. `TimezoneParityTest`: como o teste obtém o fuso sem `pytz`

- **Decision**:
  - O teste não importa `pytz` nem `zoneinfo`. Ele obtém o objeto de fuso pelo próprio `TimeZoneField`: grava o nome com `Org.objects.filter(id=...).update(timezone=nome)` e recarrega com `refresh_from_db(fields=["timezone"])`.
  - As funções que recebem o fuso como argumento (`datetime_to_str`, `previous_local_day_window`, `ContactImport._parse_value`) recebem o `org.timezone` recarregado.
  - As entradas de data e hora são literais em UTC, com `datetime.timezone.utc`, ou `date`/`datetime` ingênuos quando a função é justamente a que aplica o fuso.
- **Rationale**: no django-timezone-field 5.1, `from_db_value` devolve `pytz` quando `USE_DEPRECATED_PYTZ` é `True` ou ausente com Django <4.0, e `ZoneInfo` quando é `False` (`timezone_field/utils.py:use_pytz_default`). O mesmo código de teste roda então com `pytz` nas etapas 0 e 1 e com `zoneinfo` na etapa 2, sem nenhuma alteração. É isso que a 024 exige ("os valores esperados MUST NOT mudar" e "MUST passar sem nenhuma alteração").
- **Asserções neutras**: toda asserção compara texto ou valores que as duas implementações produzem igual quando o instante é o mesmo:
  - `isoformat()` em UTC (`valor.astimezone(datetime.timezone.utc).isoformat()`);
  - `isoformat()` local obtido por `astimezone(org.timezone)` a partir do instante, nunca o `datetime` interno da função;
  - texto formatado, `date`, nomes de fuso (`str(tz)`) e inteiros.

  Ficam proibidos no teste: `.zone`, `.key`, `.dst()`, `isinstance` contra classes de fuso, `repr` de fuso e comparação direta de objetos `tzinfo`. O `dst()` de `Europe/Dublin` difere entre as duas bibliotecas (o modelo atual do IANA trata o inverno irlandês como horário de verão negativo).
- **Determinismo**:
  - `Schedule` recebe `now` explícito.
  - `short_datetime` roda com `patch.object(timezone, "now", ...)`, como `TemplateTagTest.test_short_datetime`.
  - O export usa `start_date` e `end_date`, e nunca o `timezone.now()` do fim padrão.
  - A lista de fusos é a exceção: `PRETTY_TIMEZONE_CHOICES` é montada na importação do módulo com `datetime.now()`, então o rótulo de `America/New_York` e `Europe/Dublin` depende da data em que a suíte roda. Esses dois rótulos são comparados contra um conjunto de dois literais.
  - `format_datetime` e o export de contatos recebem o instante literal. O middleware renderiza o filtro `|date` sobre o mesmo instante, dentro do `get_response`.
  - `flows.flow_results` usa `datetime.now(tz)`. O teste substitui `temba.flows.views.datetime.now` e devolve o instante literal convertido para o fuso recebido.
  - `validate_layers` recebe o `now` literal. `_check_project` fica sob `patch`, porque a parte sob teste é a seleção pela hora local, e a chamada seguinte sai para o datalake.
- **Alternatives considered**: construir os fusos no teste com `pytz.timezone(...)`. Rejeitado na D-2 da spec.

## R3. Como os valores esperados são calculados e fixados (D-1)

- **Decision**: os literais são capturados do código atual, rodando o próprio teste, e nunca recalculados dentro dele:
  1. No branch do PR, criado a partir de `main`, o teste é escrito com as entradas e com os dicionários de esperados vazios.
  2. Uma alteração temporária, que não é commitada, faz cada `subTest` imprimir `repr()` do valor obtido. A suíte roda com `poetry run python manage.py test temba.utils.tests.TimezoneParityTest --keepdb`.
  3. A saída vira os literais do teste. A alteração temporária é removida.
  4. Revisão independente das transições: para cada `(fuso, data)`, o revisor confere a duração do dia local (23 h na entrada do horário de verão, 25 h na saída, 24 h nos controles) e o lado escolhido nos horários inexistentes e ambíguos, contra a tabela de R4. Um literal que pareça "errado" não é corrigido (FR-004). A divergência é anotada na descrição do PR.
  5. A suíte roda de novo, sem a alteração temporária, e passa. A descrição do PR registra o commit base e `pytz.__version__`.
- **Rationale**: a D-1 exige valores do código atual e fixados como literais. Rodar o próprio teste garante que a entrada usada na captura é a mesma da asserção, inclusive nos casos que dependem do banco (`Schedule`, export, `Grant` e `update_project_config`), que um script avulso no `manage.py shell` não reproduziria sem um banco de desenvolvimento preparado.
- **Alternatives considered**: script de geração commitado no repositório. Rejeitado: viraria uma segunda fonte de verdade, e na etapa 2 alguém poderia regenerar os literais com `zoneinfo`, o que anularia o teste.

## R4. Amostra do comportamento atual nas transições (pytz 2025.2)

Valores obtidos com uma sonda sobre o código atual, só para confirmar que os casos do plano atravessam as transições. Os literais do teste são os capturados no PR (R3).

| Fuso | Dia local | `previous_local_day_window` (início, fim em UTC) | Duração |
|---|---|---|---|
| `UTC` | 2026-03-08 | 2026-03-08T00:00:00Z, 2026-03-08T23:59:59Z | 24 h |
| `Africa/Kigali` | 2026-03-08 | 2026-03-07T22:00:00Z, 2026-03-08T21:59:59Z | 24 h |
| `America/New_York` | 2026-03-08 | 2026-03-08T05:00:00Z, 2026-03-09T03:59:59Z | 23 h |
| `America/New_York` | 2026-11-01 | 2026-11-01T04:00:00Z, 2026-11-02T04:59:59Z | 25 h |
| `Europe/Dublin` | 2026-03-29 | 2026-03-29T00:00:00Z, 2026-03-29T22:59:59Z | 23 h |
| `Europe/Dublin` | 2026-10-25 | 2026-10-24T23:00:00Z, 2026-10-25T23:59:59Z | 25 h |
| `America/Sao_Paulo` | 2018-11-04 | 2018-11-04T03:00:00Z, 2018-11-05T01:59:59Z | 23 h (o dia começa às 01:00 -02:00) |
| `America/Sao_Paulo` | 2026-11-04 | 2026-11-04T03:00:00Z, 2026-11-05T02:59:59Z | 24 h |

| Fuso | Hora local ingênua | `ContactImport._parse_value` | Lado escolhido pelo `localize` (`is_dst=False`) |
|---|---|---|---|
| `America/New_York` | 2026-03-08 02:30 (inexistente) | `2026-03-08T02:30:00-05:00` | offset de antes da transição |
| `America/New_York` | 2026-11-01 01:30 (ambígua) | `2026-11-01T01:30:00-05:00` | segunda ocorrência |
| `Europe/Dublin` | 2026-03-29 01:30 (inexistente) | `2026-03-29T01:30:00+00:00` | offset de antes da transição |
| `Europe/Dublin` | 2026-10-25 01:30 (ambígua) | `2026-10-25T01:30:00+01:00` | **primeira** ocorrência |
| `America/Sao_Paulo` | 2018-11-04 00:30 (inexistente) | `2018-11-04T00:30:00-03:00` | offset de antes da transição |

Outros pontos:

- `datetime_to_str(date(2018, 11, 4), ..., America/Sao_Paulo)` devolve `2018-11-04 01:00 -0200`, porque a meia-noite inexistente é normalizada.
- `TimeZoneFormField().choices` tem 433 entradas. Em 2026-11-27, os rótulos eram `(GMT-0500) America/New_York` e `(GMT+0000) Europe/Dublin`.
- `timezone_to_country_code` devolve `""`, `RW`, `US`, `IE` e `BR` para os cinco fusos.

**Achado para a etapa 2 (sem ação aqui)**: no horário ambíguo, o `pytz` escolhe a segunda ocorrência em Nova York e a primeira em Dublin, por causa do horário de verão negativo do modelo irlandês. Com `zoneinfo`, `fold=0` escolhe sempre a primeira ocorrência. A regra da FR-013 da 024 ("reproduzir `localize` com `is_dst=False`") não é então um `fold` fixo, e o `TimezoneParityTest` vai acusar a diferença em Nova York. O dado fica registrado aqui para a spec da etapa 2.

## R5. `HamlTemplatesCompileTest`: descoberta dos arquivos

- **Decision**:
  - Os diretórios são:
    - `engines["django"].engine.dirs`, ou seja, `TEMPLATES[0]["DIRS"]` (`templates/` e `node_modules/@nyaruka/temba-components/dist/templates`);
    - os diretórios de `django.template.utils.get_app_template_dirs("templates")` que ficam dentro de `settings.PROJECT_DIR` (os apps de `temba/`).
  - Diretório inexistente é ignorado.
  - Em cada diretório, `Path.rglob("*.haml")`, com o nome do template igual ao caminho relativo em formato POSIX. O primeiro diretório que contém um nome ganha, na mesma ordem dos loaders.
  - Para cada arquivo, dentro de `subTest(template=nome)`: `get_template(nome)`, e a asserção de que `template.origin.name` é o caminho do arquivo descoberto. Assim, um arquivo com o mesmo nome num diretório anterior não esconde um arquivo que falha.
  - O teste também exige que `frame.haml` e `includes/nav.haml` estejam entre os encontrados, para que uma configuração quebrada (zero arquivos) não passe em branco.
  - As exceções ficam em `KNOWN_BROKEN_TEMPLATES: dict[str, str]` (nome → motivo). Para cada entrada, o teste exige que o template continue falhando, para que uma entrada obsoleta não fique na lista.
- **Rationale**:
  - Hoje há 345 arquivos `.haml` versionados, todos em `templates/`. A 024 cita 334, um número anterior. Os apps de `temba/` não têm diretório `templates/`: `temba/templates` é o app Python de templates do WhatsApp, e `temba/api/v2/templates` é o pacote do endpoint. O `node_modules` só tem `.html`.
  - Uma sonda com essa descoberta compilou os 345 sem erro e sem sombreamento. A lista de exceções começa vazia.
  - `get_template` passa pelos loaders configurados, que começam por `temba.utils.haml.HamlFilesystemLoader` e `HamlAppDirectoriesLoader`: o HAML é convertido pelo `hamlpy` e o resultado é compilado pelo Django (tags, filtros e `{% load %}`). Os loaders são explícitos em `OPTIONS["loaders"]`, então não há cache entre chamadas.
  - `{% extends %}` e `{% include %}` só são resolvidos na renderização. A FR-002 pede compilação, e a renderização exigiria um contexto por template.
- **Alternatives considered**: listar só `templates/` com caminho fixo. Rejeitado porque a FR-002 pede também os diretórios dos apps, e a descoberta pela configuração acompanha qualquer mudança em `TEMPLATES` nas etapas 1 a 3.

## R6. Changelog e commits (Principles VII e VIII)

- **Changelog**: sem entrada. O PR só acrescenta testes e não tem mudança visível.
- **Commits** (até 50 caracteres):
  - `test: pin timezone behaviour with parity test`, com o `TimezoneParityTest` e os literais;
  - `test: compile every haml template`, com o `HamlTemplatesCompileTest`.

  Os documentos de `specs/024-django-5-2-upgrade/` e `specs/025-django-upgrade-stage0/` já estão no branch em commits `chore`/`docs` anteriores e vão no mesmo PR.
