# Engineering Spec: etapa 0 do upgrade do Django, parte 4 — remoção do `smartmin.csv_imports`

**Repository**: weni-ai/flows — backend

**Feature Branch**: a criar (sugestão: `chore/remove-csv-imports`)

**Created**: 2026-11-27

**Status**: Draft

**Input**: Última das quatro specs da etapa 0 da spec guarda-chuva [024-django-5-2-upgrade](../024-django-5-2-upgrade/spec.md): remover o app `smartmin.csv_imports`, sem uso no Flows, antes que o smartmin 5.1 o remova.

**Cycle**: SDD Lite. A mudança fica em `temba/settings_common.py`, numa linha de `temba/urls.py` e nos testes de `temba/orgs`, sem migration, sem contrato público do Principle IV, sem Courier ou Mailroom e sem tipo de canal. A spec é o único artefato de desenho, por isso nomeia arquivos, linhas e a ordem de implementação.

## Origin Without Product Spec

- Product Spec: none
- Contexto: etapa 0 da spec 024 (D-2). Esta spec cobre a FR-007 da 024. Depende da [026](../026-django-upgrade-stage0-removed-apis/spec.md) em `main`, e não depende da [027](../027-django-upgrade-stage0-post-logout/spec.md).
- Problem: O smartmin 5.1, exigido pelo Django 5.2 na etapa 3, removeu o app `smartmin.csv_imports`, que está em `INSTALLED_APPS`, em `temba/urls.py` e nas permissões de grupo do Flows. Nenhum template, view, model ou link do Flows usa o app, e removê-lo junto com o Django 5.2 juntaria duas fontes de regressão num deploy só.
- Acceptance criteria:
  - AC-1: As rotas de `/imports/` respondem 404 e o nome `csv_imports.importtask_list` deixa de resolver. Teste: `temba.orgs.tests.CsvImportsRemovedTest.test_imports_routes_are_gone` (novo).
  - AC-2: As permissões dos grupos carregam sem `csv_imports`, e as demais permissões de todos os grupos continuam iguais. Teste: `temba.orgs.tests.CsvImportsRemovedTest.test_group_permissions_load_without_csv_imports` (novo), mais os testes atuais de permissões em `temba.orgs`.
  - AC-3: Os quatro grupos de `.github/workflows/ci.yml` ficam verdes, sem nenhum teste pulado e sem nenhum `# pragma: no cover` novo, e `./code_check.py` termina limpo, inclusive `makemigrations --check`.

## Decisões de implementação

### D-1: remover o app sem migration e sem apagar a tabela

`smartmin.csv_imports` sai de `INSTALLED_APPS` (`settings_common.py:317`), as duas entradas `csv_imports.importtask.*` saem de `GROUP_PERMISSIONS["Administrators"]` e `["Editors"]` (linhas 741 e 881) e a rota `imports/` sai de `temba/urls.py`. A tabela `csv_imports_importtask` fica no banco, órfã. Apagá-la fica para outra mudança.

Alternativa rejeitada: manter o app até a etapa 3. Juntaria a remoção com a troca do Django e do smartmin num deploy só, contra a D-2 da 024.

### D-2: aceitar o efeito colateral do smartmin 3.1.0, sem mudar o smartmin

`smartmin/views.py:25` importa `from smartmin.csv_imports.models import ImportTask` no nível do módulo, e todo CRUDL de `temba/` importa `smartmin.views`. Sem o app instalado, o Django não falha: ele atribui o model ao app instalado que contém o módulo, que é `smartmin`. O model vira `smartmin.ImportTask`, com tabela `smartmin_importtask`. Uma sonda confirmou que o `django.setup()` e o carregamento de `temba.urls` funcionam. As consequências estão em "Detalhes técnicos". Nenhuma delas é migration, contrato ou comportamento visível, e evitá-las exigiria mudar o smartmin, que esta spec não faz (nenhuma dependência muda).

## Escopo neste repositório

**Muda**:

- `temba/settings_common.py`: sem `smartmin.csv_imports` em `INSTALLED_APPS` e sem `csv_imports.importtask.*` nos dois grupos, com as demais entradas na mesma ordem.
- `temba/urls.py`: sem a linha da rota `imports/`.
- `temba/orgs/tests.py`: `CsvImportsRemovedTest`.
- `WENI-CHANGELOG.md`: um bullet `chore` sob a próxima versão.

**Não muda**:

- Nenhuma dependência e nenhuma migration. A tabela `csv_imports_importtask` continua no banco.
- As linhas de `csv_imports` em `django_content_type` e `auth_permission`.
- O smartmin.

## User Scenarios & Testing *(mandatory)*

Quem usa esta mudança: o time que vai fazer a etapa 3, que precisa de um projeto sem o app que o smartmin 5.1 remove. Os usuários do Flows não percebem nada, porque nenhuma tela leva a `/imports/`.

### User Story 1 - App `csv_imports` removido (Priority: P1)

O app `smartmin.csv_imports`, sem uso, sai do projeto antes que o smartmin 5.1 o remova.

**Why this priority**: É pequeno e só bloqueia a etapa 3, mas sai mais barato agora, isolado e reversível sozinho.

**Independent Test**: `poetry run python manage.py test temba.orgs.tests.CsvImportsRemovedTest temba.orgs --keepdb`, conforme [contracts/imports-removed.behavior.md](contracts/imports-removed.behavior.md).

**Acceptance Scenarios**:

1. **Given** o app removido, **When** alguém acessa `/imports/importtask/`, **Then** recebe 404, anônimo ou superusuário.
2. **Given** o app removido e um banco com a permissão `csv_imports.importtask_list` atribuída a `Administrators`, **When** as permissões de grupo são carregadas, **Then** nenhum erro ocorre, a permissão de `csv_imports` sai do grupo e as demais permissões de todos os grupos continuam iguais.

### Edge Cases

- **`GET /imports/` já responde 404 hoje**: o `ImportTaskCRUDL` só declara `importtask/` (`list`) e `importtask/read/<pk>/` (`read`). Para que o AC-1 falhe se a rota voltar, o teste também verifica `/imports/importtask/`, `/imports/importtask/read/1/` e o `reverse` do nome.
- **Banco de teste com `--run-syncdb`**: cria a tabela `smartmin_importtask` (D-2). É inofensivo, porque nada a consulta.
- **Acesso remanescente a `/imports/`**: recebe 404. O rollback é imediato.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `smartmin.csv_imports` MUST sair de `INSTALLED_APPS`, de `temba/urls.py` e das duas listas de permissões em `settings_common.py`, sem migration (024 FR-007).
- **FR-002**: Depois do `post_migrate`, o conjunto de permissões de cada grupo MUST ser o anterior menos as de `app_label == "csv_imports"`, e nenhum grupo MUST receber permissão de `smartmin.importtask`.
- **FR-003**: `WENI-CHANGELOG.md` MUST ganhar, sob a próxima versão, um bullet `chore:` que cite a remoção de `/imports/` (app `smartmin.csv_imports`, sem uso).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Em staging, depois do `migrate` do deploy, a consulta de permissões da Test Strategy volta zero linhas nos três ambientes.
- **SC-002**: Na semana seguinte ao deploy, a taxa de 5xx e de eventos novos no Sentry fica no máximo 10% acima da média das 4 semanas anteriores (024 SC-003).

## Peak Load (Principle XII)

Não se aplica. Uma rota sem uso sai, e nenhum caminho de runtime ganha trabalho.

## Assumptions

- A rota `/imports/` não é usada por nenhum cliente externo: nenhum template, view ou link do Flows aponta para ela.
- O `post_migrate` do deploy roda o `check_all_group_permissions` do smartmin em cada ambiente, como hoje.

## Detalhes técnicos

### Efeito no banco de cada ambiente

| Tabela | Efeito |
|---|---|
| `auth_group_permissions` | o `post_migrate` (`check_all_group_permissions`) remove `csv_imports.importtask.*` de `Administrators` e `Editors`, porque elas saem de `GROUP_PERMISSIONS` |
| `django_content_type`, `auth_permission` | o `post_migrate` acrescenta o `ContentType` `smartmin.importtask`, as quatro permissões padrão e as de `PERMISSIONS["*"]` (`settings_common.py:429`), sem atribuí-las a nenhum grupo. É escrita de dados, não migration. As linhas de `csv_imports` ficam |
| `csv_imports_importtask` | intocada, órfã |
| `smartmin_importtask` | criada só no banco de teste (`--run-syncdb`), nunca em produção, porque o `smartmin` não tem migrations |

Na etapa 3, o smartmin 5.1 deixa de importar `ImportTask`, e o `ContentType` `smartmin.importtask` fica órfão. A limpeza (`remove_stale_contenttypes`) fica para outra mudança.

### Permissões de grupo

| Grupo | Antes | Depois |
|---|---|---|
| `Administrators` | `csv_imports.importtask.*` + demais | demais, sem mudança |
| `Editors` | `csv_imports.importtask.*` + demais | demais, sem mudança |
| outros grupos de `GROUP_PERMISSIONS` | sem `csv_imports` | sem mudança |

### Implementação, na ordem

1. **Testes primeiro**, em `temba/orgs/tests.py`, na `class CsvImportsRemovedTest(TembaTest)` da Test Strategy. Rodar `poetry run python manage.py test temba.orgs.tests.CsvImportsRemovedTest --keepdb` e confirmar que os dois falham: o app ainda está em `INSTALLED_APPS`, e o curinga `csv_imports.importtask.*` mantém a permissão no grupo.
2. Em `temba/settings_common.py`: remover `"smartmin.csv_imports",` de `INSTALLED_APPS` (linha 317) e `"csv_imports.importtask.*",` de `GROUP_PERMISSIONS["Administrators"]` e `["Editors"]` (linhas 741 e 881), sem mexer na ordem das demais entradas.
3. Em `temba/urls.py`: remover a linha da rota `imports/` (`include("smartmin.csv_imports.urls")`).
4. Rodar `poetry run python manage.py makemigrations --check --dry-run` (sem saída) e `poetry run python manage.py test temba.orgs.tests.CsvImportsRemovedTest temba.orgs --keepdb` (verde). Conferir `rg -n 'csv_imports' temba templates` vazio.
5. **Changelog** (FR-003).

Commits (até 50 caracteres): `chore: remove smartmin csv_imports` (testes e implementação juntos, para que todo commit fique verde; a execução vermelha do passo 1 fica na descrição do PR) e `docs: note imports removal in changelog`.

## Test Strategy

**Testes novos**, em `temba.orgs.tests.CsvImportsRemovedTest(TembaTest)`:

| Teste | Verifica | Cobre |
|---|---|---|
| `test_imports_routes_are_gone` | `"smartmin.csv_imports" not in settings.INSTALLED_APPS`; GET em `/imports/`, `/imports/importtask/` e `/imports/importtask/read/1/`, anônimo e com `login(self.superuser)`, responde 404; `reverse("csv_imports.importtask_list")` levanta `NoReverseMatch` | AC-1, FR-001 |
| `test_group_permissions_load_without_csv_imports` | nenhuma entrada de `settings.GROUP_PERMISSIONS` começa com `csv_imports.`. Simula o banco de produção: `ContentType.objects.get_or_create(app_label="csv_imports", model="importtask")` e uma `Permission` com `codename="importtask_list"` nesse tipo, atribuída a `Administrators`. Guarda, por grupo, o conjunto `{f"{p.content_type.app_label}.{p.codename}"}` e chama `check_all_group_permissions(sender=apps.get_app_config("airtime"))` (`from smartmin.management import check_all_group_permissions`), porque o `PERMISSIONS_APP` é `temba.airtime` (`settings_common.py:362`) e o smartmin ignora qualquer outro `sender`. Depois, `csv_imports.importtask_list` saiu de `Administrators`, os conjuntos de todos os grupos sem as entradas de `csv_imports` são iguais aos guardados, e nenhum grupo tem permissão de `smartmin.importtask` | AC-2, FR-002 |

**Testes existentes que fecham os critérios**: `temba.orgs` (permissões e login) e a suíte completa (AC-3).

**Comandos**:

```sh
poetry run python manage.py test temba.orgs.tests.CsvImportsRemovedTest temba.orgs --keepdb
poetry run coverage run manage.py test --keepdb --noinput
poetry run python manage.py makemigrations --check --dry-run
./code_check.py
```

**Em staging, depois do `migrate` do deploy** (SC-001):

```sql
SELECT g.name, ct.app_label, p.codename
FROM auth_group_permissions gp
JOIN auth_group g ON g.id = gp.group_id
JOIN auth_permission p ON p.id = gp.permission_id
JOIN django_content_type ct ON ct.id = p.content_type_id
WHERE ct.app_label = 'csv_imports' OR (ct.app_label = 'smartmin' AND ct.model = 'importtask');
```

Esperado: zero linhas. O `ContentType` `smartmin.importtask` pode existir sem nenhum grupo associado.

## Rollout and Rollback

Deploy em staging nos três ambientes, com a consulta acima e o smoke da FR-020 da 024, e depois em produção. Não há migration. O rollback é reverter o PR: o `post_migrate` do deploy devolve as permissões `csv_imports.importtask.*` aos grupos, e o `ContentType` `smartmin.importtask` fica, sem efeito.

## Constitution Alignment

SDD Lite: esta seção é o Constitution Check. O preset `vtex-cx-engineering` não está instalado (TODO SPECKIT_PRESET), por isso esta seção e a Test Strategy foram escritas à mão.

| Princípio | Como esta mudança cumpre |
|-----------|--------------------------|
| I. Version Control and Review | Um PR com review e CI verde, com spec própria (024 FR-001). |
| II. Security and Secrets | Nenhuma dependência nova. Uma tela sem uso deixa de existir. |
| III. Observability | Não se aplica: nenhum log ou métrica muda. |
| IV. Versioned Contracts | `/imports/` é uma tela interna do smartmin, sem link no Flows, não um contrato. O comportamento fica fixado em [contracts/imports-removed.behavior.md](contracts/imports-removed.behavior.md). Sem migration. |
| V. Specification Traceability | Abre com `## Origin Without Product Spec`, cita a 024 como contexto, e cada AC aponta para um teste. |
| VI. No Silent Divergence | Não se aplica: não há Product Spec. A FR-007 da 024 está coberta pela FR-001. |
| VII. Commit Messages | `chore: remove smartmin csv_imports` e `docs: note imports removal in changelog`. |
| VIII. Changelog Maintenance | Um bullet `chore` (FR-003). |
| IX. Never Trust the Client | Não se aplica. |
| X. Fail Gracefully | Não se aplica: nenhuma chamada externa muda. |
| XI. Bounded Retry | Não se aplica. |
| XII. Scalability and Peak Load | Peak Load não aplicável, com o motivo. |
| XIII. Diagnosable Errors | Não muda o que vai para o Sentry. |
| XIV. Tests Exercise Flows | O teste de permissões reproduz o banco de produção e roda o mesmo `check_all_group_permissions` do deploy. Os testes foram escritos antes da mudança. |
| XV. Explicit Over Clever | O efeito colateral do smartmin 3.1.0 fica registrado (D-2), em vez de escondido. |
| XVI. Contained Changes | Três pontos de configuração e os testes. A tabela órfã e o `ContentType` ficam para outra mudança. |
| XVII. Explicit, Scoped Authorization | As permissões `csv_imports.importtask.*` saem dos grupos junto com a rota que elas protegiam (FR-002). |
