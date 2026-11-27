# Engineering Spec: etapa 0 do upgrade do Django, parte 2 — APIs removidas no Django 4.0 e filtro de avisos

**Repository**: weni-ai/flows — backend

**Feature Branch**: a criar (sugestão: `refactor/django-removed-apis`)

**Created**: 2026-11-27

**Status**: Draft

**Input**: Segunda das quatro specs da etapa 0 da spec guarda-chuva [024-django-5-2-upgrade](../024-django-5-2-upgrade/spec.md): trocar, ainda no Django 3.2, as APIs que o Django 4.0 remove pelos equivalentes que já existem no 3.2, e fazer a suíte falhar quando um código de `temba/` voltar a usá-las.

**Cycle**: SDD Full, porque a mudança passa por cerca de 211 arquivos de vários apps de `temba/`. O `/speckit-plan` roda depois que a [025](../025-django-upgrade-stage0/spec.md) estiver em `main`, para que o plano parta do código atualizado. A pesquisa já feita está em [research.md](research.md). Os demais gatilhos não se aplicam: sem migration, sem dependência, sem contrato público alterado, sem Courier ou Mailroom e sem tipo de canal.

## Origin Without Product Spec

- Product Spec: none
- Contexto: etapa 0 da spec 024 (D-2). Esta spec cobre as FR-006 e FR-019 da 024. As demais FR da etapa 0 ficam nas specs 025, 027 e 028.
- Problem: O código de `temba/` usa APIs que o Django 4.0 remove (`ugettext*`, `django.conf.urls.url`, `force_text`, `urlquote*`, `is_safe_url`, `is_ajax` e `django.utils.timezone.utc`). Enquanto elas existirem, a etapa 1 da 024 (Django 4.2) não sobe, e nada impede que um código novo volte a usá-las.
- Acceptance criteria:
  - AC-1: Nenhum módulo `temba.*` emite `RemovedInDjango40Warning` durante a suíte completa. Teste: o filtro da FR-004 transforma o aviso em erro, e os quatro grupos do CI ficam verdes.
  - AC-2: O comportamento de runtime não muda. Teste: a suíte atual passa sem alteração de asserção, e o `TimezoneParityTest` e o `HamlTemplatesCompileTest` da 025 passam sem nenhuma alteração.
  - AC-3: Nenhum uso das APIs da FR-001 sobra em `temba/`. Teste: os dois comandos de inventário da seção "Inventário" voltam vazios no PR. O segundo cobre `django.utils.timezone.utc`, que no Django 3.2 não emite aviso e por isso escapa do filtro da FR-004.
  - AC-4: Os quatro grupos de `.github/workflows/ci.yml` ficam verdes, sem nenhum teste pulado e sem nenhum `# pragma: no cover` novo.
  - AC-5: `./code_check.py` termina limpo, inclusive `makemigrations --check`.

## Inventário (commit `9bb192176`, 2026-11-27)

| Troca | Onde | Equivalência no Django 3.2 |
|-------|------|----------------------------|
| `ugettext`, `ugettext_lazy`, `ugettext_noop` → `gettext*`; `ungettext*` → `ngettext*` | 189 arquivos (`rg -l '\bugettext\w*\|\bungettext\w*' temba`) | Alias direto. Os `msgid` não mudam, então `locale/` não muda. |
| `django.conf.urls.url` → `re_path` (ou `path`, quando o regex é literal) | 28 arquivos: `temba/urls.py`, os `urls.py` de `api`, `api/v2`, `api/v2/internals/media`, `assets`, `channels`, `classifiers`, `dashboard`, `externals`, `flows`, `ivr`, `orgs`, `public`, `request_logs` e `tickets`; `channels/models.py`, `classifiers/models.py`, `tickets/models.py`; os `type.py` de `dialog360`, `email`, `facebookapp`, `plivo`, `twilio`, `vonage`, `whatsapp`, `dtone`, `freshchat` e `zendesk` | `url` é alias de `re_path`. |
| `force_text` → `force_str` | `channels/views.py`, `orgs/views.py`, `contacts/search/mailroom.py`, `flows/views.py`, `flows/tests.py`, `utils/text.py`, `utils/cache.py`, `tests/requests.py` | Alias direto. |
| `urlquote` → `urllib.parse.quote`; `urlquote_plus` → `quote_plus`; `urlunquote` → `unquote` | `channels/models.py`, `orgs/views.py`, `utils/views.py`, `contacts/views.py`, `msgs/views.py`, `utils/management/commands/perf_test.py` | Mesma função, com os mesmos `safe` padrão (`"/"` para `quote` e `""` para `quote_plus`). |
| `is_safe_url(url, host)` → `url_has_allowed_host_and_scheme(url, allowed_hosts=host)` | `contacts/views.py:32` e `:753`; `msgs/views.py:22` e `:622` | `is_safe_url` só delega para a nova. |
| `request.is_ajax()` → `request.headers.get("x-requested-with") == "XMLHttpRequest"` | `orgs/views.py:3597` | Mesma checagem que o Django faz. |
| `django.utils.timezone.utc` → `datetime.timezone.utc` | `api/v2/views.py:5894-5895`; `api/v2/internals/contacts/views.py:697-708`; `api/v2/internals/contacts/tests.py:2134-2135`; `channels/tests.py:2147` e `:2152` | Mesmo instante e mesma saída de `isoformat()` (`+00:00`). `make_aware` aceita os dois. |

Comandos para reabrir o inventário. Hoje, o primeiro encontra 211 arquivos e o segundo, as dez linhas de `timezone.utc` da tabela. Depois das trocas, os dois MUST voltar vazios:

```sh
rg -n -t py -e '\bugettext\w*' -e '\bungettext\w*' -e '\bforce_text\b' -e 'django\.conf\.urls import .*\burl\b' \
   -e '\burlquote' -e '\burlunquote\b' -e 'is_safe_url' -e '\.is_ajax\(' -e 'django\.utils\.timezone\.utc' temba
rg -n '(^|[^.\w])timezone\.utc\b' $(rg -l -t py '^from django\.utils import (.*\b)?timezone\b' temba)
```

- O primeiro procura só o nome `url` nos imports de `django.conf.urls`. O `include` desse módulo continua existindo no Django 4.x e 5.x, e a FR-001 não o proíbe.
- O segundo só olha os arquivos em que o nome `timezone` é o `django.utils.timezone`. Nos demais, `timezone.utc` já é o `datetime.timezone.utc` (por exemplo `api/v2/services/events.py` e `utils/datalake/`). O padrão também ignora `dt_timezone.utc` e `dt.timezone.utc`, que são as formas de destino.

## Decisões de implementação

### D-1: trocas mecânicas com `django-upgrade`, sem nova dependência

As trocas da tabela, menos as duas últimas linhas, são feitas com a ferramenta [`django-upgrade`](https://github.com/adamchainz/django-upgrade) (`--target-version 3.2`), rodada com `uvx` ou `pipx` só com os fixers do inventário, e o que ela não cobrir ou errar é feito à mão ([research.md](research.md) R2 e R3). A ferramenta não entra no `pyproject.toml`. O resultado passa por `./code_check.py` (Black e isort).

Alternativa rejeitada: `sed` em massa. Não entende imports, quebra linhas com mais de um nome importado e exige mais revisão manual.

### D-2: filtro de avisos instalado antes do `django.setup()`

No bloco `if TESTING:` de `temba/settings_common.py` (linha 40) entra `warnings.filterwarnings("error", category=RemovedInDjango40Warning, module=r"temba\.")`. Parte dos avisos é emitida na importação de models e URLs, ainda durante o `django.setup()`, então o filtro não pode ficar no `TembaTestRunner`. A opção `-W` da linha de comando também não serve: o campo de módulo dela exige o nome completo do módulo. O filtro vale só para avisos atribuídos a módulos `temba.*`. Avisos emitidos por smartmin, `weni-rp-apps` e outras bibliotecas não viram erro.

O filtro entra depois das trocas, porque o próprio `settings_common.py` usa `ugettext_lazy` hoje.

## Escopo neste repositório

**Muda**:

- Os arquivos da tabela "Inventário".
- `temba/settings_common.py`: as trocas da linha 13 e o filtro de avisos no bloco `if TESTING:`.
- `WENI-CHANGELOG.md`: um bullet `chore` sob a próxima versão.

**Não muda**:

- `pyproject.toml` e `poetry.lock` (nenhuma dependência).
- Nenhum `msgid` de `locale/`.
- Nenhuma migration.
- Os testes da 025 (`TimezoneParityTest` e `HamlTemplatesCompileTest`).
- O logout e o `smartmin.csv_imports` (specs 027 e 028).
- O uso de `pytz`, `index_together`, `assertFormError`, `DEFAULT_FILE_STORAGE` e `USE_L10N` (etapas 1 a 3 da 024).
- Os dois `re_path` que já existem (`channels/types/instagram/type.py` e `channels/types/whatsapp_cloud/type.py`).

## User Scenarios & Testing *(mandatory)*

Quem usa esta mudança: os usuários do Flows, que não podem perceber diferença; e os desenvolvedores da etapa 1, que precisam de um código sem APIs removidas.

### User Story 1 - Código sem APIs removidas no Django 4.0 (Priority: P1)

Um desenvolvedor roda a suíte e nenhum código de `temba/` usa API que o Django 4.0 remove. Um uso novo quebra o teste na hora.

**Why this priority**: É o grosso da etapa 0 e reduz o diff da etapa 1.

**Independent Test**: CI verde com o filtro da FR-004 ativo, e os testes da 025 sem alteração.

**Acceptance Scenarios**:

1. **Given** o filtro de avisos ativo, **When** a suíte completa roda, **Then** nenhum `RemovedInDjango40Warning` é emitido por `temba.*`.
2. **Given** um desenvolvedor que acrescenta `from django.utils.translation import ugettext_lazy` num módulo `temba.*`, **When** a suíte roda, **Then** ela falha com o aviso convertido em erro.
3. **Given** um redirect para outro host em `contacts/views.py` ou `msgs/views.py`, **When** a view valida o destino, **Then** o redirect continua recusado, como hoje.
4. **Given** a rota pública `templates/translations/<id>` da API v2, **When** recebe uma requisição, **Then** a view recebe o mesmo kwarg de hoje (texto casado por `\d+`).

### Edge Cases

- **`url()` com regex que não vira `path`**: fica `re_path` com o mesmo regex. A conversão para `path` só acontece quando o regex é literal, para não mudar o casamento de URL nem o tipo do kwarg (FR-005).
- **`ugettext` usado com outro nome** (`from django.utils.translation import ugettext as _`): o alias muda e o nome local `_` continua o mesmo.
- **Chamada dentro de f-string**: a ferramenta reescreve o import mas não a chamada dentro da f-string, o que deixaria um nome indefinido. Essas chamadas são corrigidas à mão ([research.md](research.md) R3).
- **Código novo com API removida aberto em paralelo**: depois do merge, o filtro quebra o CI de quem introduzir o uso, que é o comportamento pedido (cenário 2).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O código de `temba/` MUST deixar de usar `ugettext*`, `ungettext*`, `force_text`, `django.conf.urls.url`, `urlquote`, `urlquote_plus`, `urlunquote`, `is_safe_url`, `request.is_ajax()` e `django.utils.timezone.utc` (024 FR-006).
- **FR-002**: As trocas da FR-001 MUST NOT alterar comportamento. Nenhuma asserção de teste existente MUST mudar, exceto o nome importado nos próprios arquivos de teste.
- **FR-003**: Nenhum `msgid` de `locale/` MUST mudar.
- **FR-004**: Toda execução de teste MUST transformar em erro os `RemovedInDjango40Warning` atribuídos a módulos `temba.*`, com o filtro instalado no bloco `if TESTING:` de `temba/settings_common.py` (024 FR-019, D-2).
- **FR-005**: Uma rota MUST virar `path` só quando o regex é literal. As demais ficam `re_path` com o mesmo regex, sem conversor (`<int:...>`, `<uuid:...>`), para que nenhum endpoint mude o casamento nem o tipo do kwarg (024 FR-002).
- **FR-006**: `WENI-CHANGELOG.md` MUST ganhar, sob a próxima versão, um bullet `chore:` que cite a preparação para o Django 4.2 (troca das APIs que o Django 4.0 remove).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero `RemovedInDjango40Warning` de `temba.*` na suíte completa.
- **SC-002**: Os quatro grupos do CI verdes, com zero testes pulados e zero `# pragma: no cover` novos.
- **SC-003**: Na semana seguinte ao deploy, a taxa de 5xx e de eventos novos no Sentry fica no máximo 10% acima da média das 4 semanas anteriores (024 SC-003).

## Peak Load (Principle XII)

Não se aplica. As trocas não mudam o caminho executado: cada nome removido é alias ou delegação direta do novo. O filtro de avisos só existe em teste. Nenhum estado novo é introduzido.

## Assumptions

- A [025](../025-django-upgrade-stage0/spec.md) está em `main` antes do início desta spec, e os testes dela são a rede de segurança das trocas (AC-2).
- `django-upgrade` é usado só como ferramenta local, sem entrar no `pyproject.toml`, o que o Principle II permite, porque não é dependência do projeto.
- Com cerca de 211 arquivos, conflitos de rebase com PRs em andamento são prováveis. O plano define como resolvê-los sem revisão manual linha a linha ([research.md](research.md) R5).

## Test Strategy

**Testes novos**: nenhum. A proteção desta spec é o filtro da FR-004, ativo em toda execução de teste, e os testes da 025.

**Testes existentes que fecham os critérios**: a suíte completa (AC-1, AC-2 e AC-4), em especial `temba.utils.tests.TimezoneParityTest` e `HamlTemplatesCompileTest` (025, sem alteração), `temba.contacts` e `temba.msgs` (redirects com `url_has_allowed_host_and_scheme`), `temba.api` (rotas e payloads), `temba.api.v2.internals.contacts` (datas em UTC) e `temba.channels`.

**Verificações do PR**:

| Verificação | Cobre |
|-------------|-------|
| Os dois comandos de inventário vazios | AC-3, FR-001 |
| O diff de `WENI-CHANGELOG.md` tem um bullet `* chore:` sob a próxima versão, citando a preparação para o Django 4.2 | FR-006 |
| `git diff main --stat -- locale` vazio | FR-003 |
| `git diff main -U0 \| rg '^\+.*<(int\|uuid\|slug\|str\|path):'` vazio | FR-005 |
| `git diff main -- temba/utils/tests.py` vazio | AC-2 |
| Verificação manual do cenário 2 da US1 (uso novo de `ugettext_lazy` quebra o `django.setup()` dos testes), sem commitar | FR-004 |

**Comandos**:

```sh
poetry run coverage run manage.py test --keepdb --noinput
poetry run python manage.py makemigrations --check --dry-run
./code_check.py
```

## Rollout and Rollback

Deploy em staging nos três ambientes, com o smoke da FR-020 da 024 (FastAPI, consumer RabbitMQ, Celery worker e beat), e depois em produção. Não há migration. O rollback é reverter os commits do PR e refazer o deploy.

## Constitution Alignment

Revisão no nível da spec. O Constitution Check formal fica no `plan.md`. O preset `vtex-cx-engineering` não está instalado (TODO SPECKIT_PRESET), por isso esta seção e a Test Strategy foram escritas à mão.

| Princípio | Como esta mudança cumpre |
|-----------|--------------------------|
| I. Version Control and Review | Um PR com review e CI verde, com spec própria (024 FR-001). Commits atômicos por fixer. |
| II. Security and Secrets | Nenhuma dependência nova (`django-upgrade` só como ferramenta local). |
| III. Observability | Não se aplica: nenhum log ou métrica muda. |
| IV. Versioned Contracts | Nenhum contrato DRF, FastAPI, Courier ou RabbitMQ muda (FR-005). Sem migration. |
| V. Specification Traceability | Abre com `## Origin Without Product Spec`, cita a 024 como contexto, e cada AC aponta para um teste ou verificação. |
| VI. No Silent Divergence | Não se aplica: não há Product Spec. As FR-006 e FR-019 da 024 estão cobertas pelas FR-001 e FR-004. |
| VII. Commit Messages | Por exemplo: `refactor: replace ugettext with gettext`, `refactor: replace url with path and re_path`, `test: fail on django 4.0 removal warnings`. |
| VIII. Changelog Maintenance | Um bullet `chore` (FR-006). |
| IX. Never Trust the Client | A validação de redirect continua igual (US1, cenário 3). |
| X. Fail Gracefully | Não se aplica: nenhuma chamada a dependência externa muda. |
| XI. Bounded Retry | Não se aplica. |
| XII. Scalability and Peak Load | Nenhum estado novo. Peak Load não aplicável, com o motivo. |
| XIII. Diagnosable Errors | Não muda o que vai para o Sentry. |
| XIV. Tests Exercise Flows | A suíte inteira roda com o filtro, e os testes de fluxo da 025 protegem o comportamento de fuso e de templates. |
| XV. Explicit Over Clever | O filtro de avisos fica em settings, com o motivo de estar ali (D-2). |
| XVI. Contained Changes | Só o inventário, com os fixers restritos aos quatro necessários (D-1). |
| XVII. Explicit, Scoped Authorization | Não se aplica: nenhuma permissão muda. |
