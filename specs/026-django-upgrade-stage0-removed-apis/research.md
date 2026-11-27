# Research: etapa 0 do upgrade do Django, parte 2 — APIs removidas no Django 4.0 e filtro de avisos

**Feature**: `026-django-upgrade-stage0-removed-apis` | **Date**: 2026-11-27 | **Plan**: a criar com `/speckit-plan`

Esta pesquisa foi feita no plano da 025, quando a etapa 0 ainda era uma spec só, e veio para cá na divisão em quatro specs. O `/speckit-plan` desta spec parte dela: confere os números contra o `main` atualizado (com a 025 integrada) e completa o que faltar. Os levantamentos foram feitos no commit `fcf408e0c`, com Django 3.2.25 instalado pelo `poetry.lock`.

## R1. Requisitos da 024 cobertos por esta spec

- **Decision**: esta spec cobre as FR-006 e FR-019 da 024 e, do conjunto geral, as FR-001 a FR-005, a FR-020 (smoke em staging antes de produção) e a FR-025 (rollback descrito no PR).
- **Rationale**: é a primeira spec da etapa 0 que muda runtime e vai para produção, então a FR-020 se aplica aqui.

## R2. `django-upgrade`: versão, fixers e arquivos

- **Decision**:
  - Rodar `django-upgrade==1.33.0` com `uvx`, com `--target-version 3.2` e só os fixers `utils_translation`, `django_urls`, `utils_encoding` e `utils_http` (`--only`), só sobre os arquivos que o primeiro comando de inventário da spec encontra.
  - A versão fica registrada na descrição do PR. A ferramenta não entra no `pyproject.toml`.
- **Rationale**:
  - Sem `--only`, o `--target-version 3.2` também aplicaria fixers fora do inventário, como `request_headers` (troca `request.META["HTTP_X_..."]` por `request.headers`, por exemplo em `orgs/views.py:2891`), `default_app_config`, `management_commands` e `admin_register`. Isso viola o Principle XVI e a FR-002.
  - Os nomes dos quatro fixers foram conferidos no código da 1.33.0 (`django_upgrade/fixers/`). A 1.33.0 exige Python ≥3.10, então roda no 3.11 do projeto.
  - Sete arquivos importam `include, url` de `django.conf.urls` (`temba/urls.py` e os `urls.py` de `api`, `channels`, `classifiers`, `orgs`, `request_logs` e `tickets`). O inventário da spec só procura o nome `url`, então um `from django.conf.urls import include` que sobre depois do fixer é aceito: o `include` desse módulo continua no Django 4.x e 5.x. O plano confirma o que o `django_urls` faz com esse import.
  - Rodar só sobre os arquivos do inventário evita reescrever os dois `re_path` que já existem (`channels/types/instagram/type.py` e `channels/types/whatsapp_cloud/type.py`). O `django_urls` converte `re_path` existente para `path` quando consegue.
- **Alternatives considered**: `sed` em massa (rejeitado na D-1); rodar todos os fixers e reverter à mão o que estiver fora do inventário, rejeitado porque transforma a revisão em caça a mudanças não pedidas.

## R3. O que o `django-upgrade` faz errado ou não faz, e é corrigido à mão

Uma execução de teste numa cópia de `temba/` (fora do repositório) com os quatro fixers mudou 211 arquivos e mostrou quatro pontos que precisam de correção à mão:

1. **Conversor `<int:...>` numa rota pública**: o `django_urls` transforma `(?P<nome>\d+)` em `<int:nome>` e o regex de UUID em `<uuid:nome>`. Isso muda o tipo do kwarg que a view recebe (de `str` para `int` ou `UUID`) e o casamento (`\d+` aceita dígitos Unicode, o conversor `int` só aceita `[0-9]+`). Nos arquivos do inventário, isso acontece numa única rota: `temba/api/v2/urls.py:124` (`templates/translations/(?P<template_id>\d+)$`), que é um endpoint DRF público (Principle IV, FR-005). A linha volta para `re_path(r"^templates/translations/(?P<template_id>\d+)$", ...)`. Os outros 133 `path(...)` gerados têm regex literal.
2. **Chamadas dentro de f-strings**: com Python 3.11, uma f-string é um único token, e o `utils_http` reescreve o import (`urlquote` → `quote`) mas não a chamada dentro dela. Sobram três nomes indefinidos, que viram `NameError` em runtime:
   - `temba/orgs/views.py:501` (`urlquote(redirect_url)` → `quote(redirect_url)`);
   - `temba/utils/views.py:249` (`urlquote(request.path)` → `quote(request.path)`);
   - `temba/contacts/views.py:1213` (`urlquote_plus(search)` → `quote_plus(search)`).

   O flake8 do `./code_check.py` acusa F821 nesses pontos, e o primeiro comando de inventário da spec também os encontra.
3. **`is_safe_url` com argumento posicional**: o fixer gera `url_has_allowed_host_and_scheme(redirect, self.request.get_host())`. É equivalente (o segundo parâmetro posicional é `allowed_hosts`, e uma `str` vira `{str}`), mas a forma da tabela de inventário é `allowed_hosts=host`. As duas chamadas (`contacts/views.py:753` e `msgs/views.py:622`) ganham o nome do argumento à mão, para que a revisão compare o diff com a tabela sem interpretação.
4. **Imports duplicados**: o fixer acrescenta `from urllib.parse import quote` e `from django.urls import path, re_path` em linhas novas, mesmo quando o arquivo já importa de `urllib.parse` (por exemplo `orgs/views.py:11`). O isort do `./code_check.py` junta as linhas.

Ficam fora dos fixers com `--target-version 3.2`, e são feitos à mão, como a D-1 prevê:

- `request.is_ajax()` em `orgs/views.py:3597` → `request.headers.get("x-requested-with") == "XMLHttpRequest"`;
- `django.utils.timezone.utc` → `datetime.timezone.utc` (o fixer `utils_timezone` só existe a partir do alvo 4.1). Nos arquivos do inventário, o nome `timezone` já é o `django.utils.timezone`. O UTC do `datetime` entra com o alias que o projeto já usa: `from datetime import timezone as dt_timezone` (precedente em `temba/conversion_events/views.py`), ou `dt.timezone.utc` onde o arquivo já faz `import datetime as dt` (`api/v2/internals/contacts/views.py` e `tests.py`).

Nenhum dos 189 arquivos com `ugettext*`/`ungettext*` é migration nem arquivo de teste, então a troca não toca `migrations/`, e a exceção da FR-002 ("exceto o nome importado nos próprios arquivos de teste") só se aplica a `timezone.utc` e `force_text` em `flows/tests.py`, `channels/tests.py`, `api/v2/internals/contacts/tests.py` e `tests/requests.py`.

- **Alternatives considered**: aceitar `<int:template_id>`. Rejeitado porque muda o kwarg de um endpoint público (FR-005).

## R4. Filtro de `RemovedInDjango40Warning` (D-2, FR-004)

- **Decision**: no bloco `if TESTING:` de `temba/settings_common.py` (linha 40), depois de `DEBUG = False`, entra:

  ```python
  warnings.filterwarnings("error", category=RemovedInDjango40Warning, module=r"temba\.")
  ```

  com `import warnings` (bloco da biblioteca padrão) e `from django.utils.deprecation import RemovedInDjango40Warning` (bloco do Django) no topo do arquivo, e um comentário de uma linha com a restrição: o filtro fica aqui, e não no runner, porque parte dos avisos sai durante o `django.setup()`.
- **Rationale**:
  - Todos os avisos de remoção do 3.2 que importam aqui (`url`, `ugettext*`, `ungettext*`, `force_text`, `smart_text`, `urlquote*`, `urlunquote*`, `is_safe_url`, `is_ajax`) usam `stacklevel=2`. Assim, o aviso é atribuído ao módulo que chama a API, e `module=r"temba\."` (casado com `re.match` contra o `__name__` desse módulo) pega todo chamador em `temba.*`, inclusive `temba.settings_common` e os `tests.py`. Avisos atribuídos a `weni.*` (o `weni-rp-apps` usa `url()`), `smartmin.*` ou `mozilla_django_oidc.*` não viram erro.
  - O `TESTING` é calculado em `settings_common.py` a partir de `sys.argv`, e o `temba.settings_ci` do CI importa `temba.settings`, que importa `settings_common`. O filtro vale então no CI e no `manage.py test` local, e não vale em `runserver`, `compress` ou produção.
  - O `DiscoverRunner` do 3.2 não passa `warnings` para o `TextTestRunner`, que por isso não troca os filtros. O `TembaTestRunner` também não mexe em `warnings`.
  - Há precedente no projeto: `temba/settings.py:113` já instala um `filterwarnings("error", ..., module=...)` em settings.
  - O `django.utils.timezone.utc` do 3.2 é `pytz.utc` e não emite aviso (o aviso só existe a partir do 4.1). A troca da FR-001 para `timezone.utc` é verificada pelo segundo comando de inventário da spec, que só olha os arquivos em que `timezone` é o `django.utils.timezone`, e não pelo filtro.
- **Ordem dos commits**: o filtro entra depois das trocas. Antes disso, o próprio `settings_common.py` (linha 13, `ugettext_lazy`) quebraria o `django.setup()` dos testes.
- **Verificação manual do cenário 2 da US1**, sem commitar: acrescentar `from django.utils.translation import ugettext_lazy` e uma chamada `ugettext_lazy("x")` no nível de módulo de `temba/utils/text.py`; `poetry run python manage.py test temba.utils.tests.InitTest --keepdb` falha no `django.setup()` com `RemovedInDjango40Warning` atribuído a `temba.utils.text`; reverter e confirmar que passa.
- **Alternatives considered**: um teste que confira o filtro em `warnings.filters`. Rejeitado: a categoria muda a cada etapa (FR-019 da 024), e o AC-1 já é fechado pela suíte inteira rodando com o filtro.

## R5. Commits, changelog e rebase

- **Commits** (até 50 caracteres), um por fixer, com as correções de R3 que pertencem a ele:
  1. `refactor: replace ugettext with gettext` (`utils_translation`);
  2. `refactor: replace url with path and re_path` (`django_urls`, mais a volta da rota `templates/translations` para `re_path`);
  3. `refactor: replace removed encoding and http utils` (`utils_encoding` e `utils_http`, mais as três f-strings e o `allowed_hosts=`);
  4. `refactor: replace is_ajax and timezone.utc` (à mão);
  5. `test: fail on django 4.0 removal warnings` (R4);
  6. `docs: add django upgrade entry to changelog` (FR-006).
- **Changelog**: um bullet `* chore: ...` sob o cabeçalho da próxima versão do `WENI-CHANGELOG.md` (criado no formato `3.x.y` + `----------` do arquivo, se ainda não existir). As specs 027 e 028 têm bullets próprios.
- **Rebase**: num conflito, o PR descarta o próprio lado no arquivo, rebasea e roda de novo o fixer daquele commit, em vez de resolver à mão. Antes do merge, os dois comandos de inventário rodam de novo sobre `main` atualizado.
