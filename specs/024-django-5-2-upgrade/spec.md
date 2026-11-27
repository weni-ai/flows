# Engineering Spec (guarda-chuva): atualização do Django 3.2 para o 5.2 LTS em etapas

**Repository**: weni-ai/flows — backend

**Feature Branch**: não se aplica (spec guarda-chuva; cada etapa tem a sua)

**Created**: 2026-11-27

**Status**: Approved roadmap — etapa 0 dividida nas specs 025 a 028; 025 pronta para implementação

**Input**: User description: "Atualizar a versão do Django do projeto para a mais próxima da atual possível, correndo o menor risco de quebrar a aplicação. Estudar as dependências e apresentar alternativas." Alternativa escolhida: Django 5.2 LTS em etapas (3.2 → preparação → 4.2 → 5.2), com spec formal antes de codar.

**Cycle**: spec guarda-chuva, sem `plan.md` nem `tasks.md` próprios. Ela fixa o objetivo, as decisões D-1 a D-4, a ordem das etapas, os gates entre elas e os requisitos mínimos de cada uma. Cada etapa é entregue por uma ou mais specs filhas, uma por PR (FR-001), com o ciclo adequado à complexidade de cada uma (ver "Etapas e specs filhas").

## Etapas e specs filhas

| Etapa | Spec filha (uma por PR) | Ciclo | Pré-condição para criar ou iniciar a spec | Status |
|-------|------------------------|-------|-------------------------------------------|--------|
| 0 — preparação no 3.2 | [025-django-upgrade-stage0](../025-django-upgrade-stage0/spec.md): testes de proteção | SDD Full | nenhuma | plan e tasks prontos |
| 0 | `026-django-upgrade-stage0-removed-apis`: APIs removidas no 4.0 e filtro de avisos | SDD Full | 025 em `main` | entra no próprio PR |
| 0 | `027-django-upgrade-stage0-post-logout`: logout por POST | SDD Lite | 026 em `main` | entra no próprio PR |
| 0 | `028-django-upgrade-stage0-remove-csv-imports`: remoção do `smartmin.csv_imports` | SDD Lite | 026 em `main` | entra no próprio PR |
| 1 — degrau 4.2 com `pytz` | a criar (uma ou mais) | SDD Full | etapa 0 estável em produção por 1 semana; release do `weni-rp-apps` compatível com o 4.2 e o 5.2 publicada | não iniciada |
| 2 — `pytz` → `zoneinfo` no 4.2 | a criar (uma ou mais) | SDD Full | etapa 1 estável em produção por 1 semana; FR-014 rodada nos três ambientes | não iniciada |
| 3 — destino 5.2 | a criar (uma ou mais) | SDD Full | etapa 2 estável em produção por 1 semana; fork `weni-ai/django-hamlpy` publicado (FR-026); PostgreSQL ≥14 confirmado (FR-023) | não iniciada |

Regras para as specs filhas:

- Uma spec filha é entregue em exatamente um PR, e todo PR integrado em `main` tem a sua spec (FR-001). Os documentos da spec entram no próprio PR que ela descreve. A atualização de status de uma spec já integrada (nesta tabela e no `Status` dela) pode entrar no PR da spec seguinte.
- A divisão de uma etapa em specs é decidida quando a etapa começa, a partir do conteúdo da etapa em D-2. As specs de uma etapa seguem a ordem de dependência registrada nesta tabela.
- Cada spec filha abre com `## Origin Without Product Spec` (Principle V) e cita esta spec, no commit em que foi criada, como contexto de origem.
- Os requisitos desta spec marcados para uma etapa são o mínimo que as specs filhas dessa etapa, juntas, MUST cobrir. Cada spec filha diz quais requisitos desta spec ela cobre, detalha, fixa versões exatas e pode acrescentar requisitos. Ela MUST NOT remover nem contrariar um requisito desta spec sem antes alterar esta spec no mesmo PR.
- Ao fim de cada spec filha (deploy em produção mais a semana de observação de SC-003 e SC-004), a linha dela na tabela acima MUST ser atualizada com a data do deploy e o status `em produção desde AAAA-MM-DD`. Uma spec só com testes, sem deploy funcional, registra `em main desde AAAA-MM-DD`.
- Os critérios de aceite AC-1 a AC-7 desta spec são verificados ao fechar a etapa 3. Até lá, cada spec filha tem critérios próprios que fecham no seu PR.

## Origin Without Product Spec

- Product Spec: none
- Problem: O Flows roda o Django 3.2.25, que não recebe correção de segurança desde 1º de abril de 2024. Várias dependências estão presas a versões antigas pelo mesmo motivo, e o projeto não consegue aplicar correções de segurança do framework nem atualizar bibliotecas que já exigem Django mais novo.
- Acceptance criteria:
  - AC-1: Em produção (todos os ambientes: shared, India e Ireland), o Flows roda o Django 5.2.x na última versão de patch disponível no deploy. Teste: `temba.utils.tests.DjangoVersionTest.test_runs_supported_lts` (novo), que verifica que `django.VERSION[:2] == (5, 2)`, mais o `poetry.lock` do PR final.
  - AC-2: Os quatro grupos de `.github/workflows/ci.yml` (`api`, `channels`, `core` e `others`) ficam verdes em cada etapa, sem nenhum teste pulado e sem nenhum `# pragma: no cover` novo. Teste: execução do workflow no PR de cada etapa.
  - AC-3: Os testes rodam sem nenhum aviso de remoção do Django (`RemovedInDjangoXXWarning` da próxima série) emitido por código de `temba/`. Teste: o filtro de avisos da FR-019, ativo em toda execução de teste, transforma esses avisos em erro.
  - AC-4: Datas exibidas, filtros por período, agendamentos e exports continuam iguais aos de antes da troca de `pytz` por `zoneinfo`, inclusive em fusos com horário de verão e nas datas de transição. Teste: `temba.utils.tests.TimezoneParityTest` (novo, FR-012), mais os testes atuais de `temba.utils.dates`, `temba.msgs`, `temba.contacts` e `temba.utils.datalake`.
  - AC-5: O login, o logout e a navegação das telas servidas por smartmin e HAML continuam funcionando. Teste: `temba.orgs.tests` (login, logout e convite), mais o teste novo de logout por POST (FR-016) e a compilação de todos os templates HAML (FR-021).
  - AC-6: Nenhum contrato público muda: endpoints DRF em `temba/api`, rotas FastAPI em `temba/fastapi_app`, configuração de canal lida pelo Courier e eventos do RabbitMQ. As versões exigidas de Courier e Mailroom continuam as mesmas. Teste: os testes atuais de `temba.api`, `temba.fastapi_app` e `temba.channels`, sem alteração de asserção de payload.
  - AC-7: `./code_check.py` termina limpo, inclusive a checagem de migrations faltando, em cada etapa.

## Situação atual (levantada em 2026-11-27, commit `9bb192176`)

- **Django 3.2.25** (`pyproject.toml`: `Django = "^3.2.6"`).
- **Python**: `pyproject.toml` aceita `>=3.10,<3.12`. A imagem Docker (`docker/Dockerfile`, `python:3.11-slim-bookworm`) e o CI usam 3.11.
- **PostgreSQL 15 + PostGIS 3.5 no CI** (`.github/workflows/ci.yml`). A versão de produção não está no repositório.
- **Tamanho**: 1.191 arquivos Python em `temba/`, 334 templates HAML e 20 templates HTML.

Calendário oficial de suporte ([djangoproject.com/download](https://www.djangoproject.com/download/), consultado em 2026-11-27):

| Série | Suporte de segurança até | Python | PostgreSQL mínimo |
|-------|--------------------------|--------|-------------------|
| 3.2 LTS (atual) | encerrado em 2024-04-01 | 3.6–3.10 oficialmente; o projeto já roda 3.11 fora da faixa oficial | 9.6 |
| 4.2 LTS | encerrado em 2026-04-07 | 3.8–3.12 | 12 |
| 5.2 LTS | abril de 2028 | 3.10 ou mais | 14 |
| 6.0 | abril de 2027 | 3.12 ou mais | a confirmar no plano |
| 6.1 (mais recente, 6.1.3) | dezembro de 2027 | 3.12 ou mais | a confirmar no plano |
| 6.2 LTS (prevista para abril de 2027) | abril de 2030 | 3.12 ou mais | — |

## Alternativas avaliadas

### D-1: destino Django 5.2 LTS, passando por um 4.2 de curta duração

| Alternativa | Risco | Por que foi escolhida ou rejeitada |
|-------------|-------|------------------------------------|
| Parar no 4.2 LTS | Baixo | Rejeitada como destino: o 4.2 também já está sem suporte. Fica só como degrau temporário. |
| **5.2 LTS em etapas** | Médio, controlado | **Escolhida.** Suporte até abril de 2028, mais longo que o do 6.1. Roda no Python 3.11 atual e cabe nos limites de `weni-commons` e `weni-feature-flags` (Django abaixo de 6.0). |
| 6.1 direto | Alto | Rejeitada agora: exige Python 3.12 (troca da imagem e de todas as wheels compiladas), releases novas de `weni-commons` e `weni-feature-flags` e o `smartmin` 6.2.x, e o suporte acaba antes do 5.2. O caminho natural é ir do 5.2 para o 6.2 LTS numa spec futura. |

## Bloqueios de dependências

Limites declarados no `poetry.lock` atual e versões publicadas no PyPI em 2026-11-27. As versões exatas de cada etapa ficam para o `plan.md`. As faixas abaixo são as restrições que o plano precisa respeitar.

| Pacote | Atual | Limite atual | Para o 4.2 | Para o 5.2 | Observação |
|--------|-------|--------------|------------|------------|------------|
| `smartmin` | 3.1.0 | Django <4.0, redis <4.0 | 4.2.x (≥4.2.1) | 5.2.x (Python ≥3.11) | Quatro versões maiores de diferença. **A 5.1 removeu o app `smartmin.csv_imports`**, que está em `INSTALLED_APPS`. |
| `django-hamlpy` | 1.7.0 | Django >=3.2,<5.0 | 1.7.0 | fork `weni-ai/django-hamlpy` (D-4) | Sem release desde 2023-05. O código só usa APIs estáveis (`django.template.loaders`, `translation`, `AppConfig`). |
| `weni-rp-apps` (interno) | 2.13.2 | importa `django.conf.urls.url` | **release nova** | release nova | Quebra já no 4.0 (`weni/s3`, `weni/ticketer_queues`, `weni/auth`, `weni/channel_stats` e `weni/analytics_api`). Também prende `mozilla-django-oidc <3`, `drf-nested-routers <0.94`, `django-csp <4`, `django-environ <0.8` e `flower <0.10`. |
| `weni-commons` / `weni-feature-flags` (internos) | 1.8.0 / 2.2.0 | Django <6.0, django-redis <=6.0 | ok | ok | Bloqueiam só o 6.x. |
| `django-compressor` | 2.4.1 | usa `smart_text`, `force_text`, `providing_args` e `get_storage_class` | 4.4 ou mais | 4.6.0 (Python ≥3.10) | Quebra no 4.0. |
| `django-timezone-field` | 5.1 | Django <5.0 | 5.1 | 7.2.x | A 6.0 removeu o suporte a `pytz`. |
| `django-redis` | 4.12.1 | — | 5.4.0 | 6.0.0 (exige `redis` ≥4.0.2) | O `redis` vai de 3.5.3 para 4 ou mais na etapa 3. A 7.0 está fora do limite do `weni-commons`. |
| `djangorestframework` | 3.15.1 | — | 3.15.x | 3.16 ou mais | |
| `django-mptt` | 0.12.0 | usa `index_together` e `is_ajax` | 0.16 ou mais | 0.17 ou mais | |
| `django-templates-macros` | 0.2 | — | 0.3 | 0.3 | |
| `django-countries`, `django-cors-headers`, `django-csp`, `django-storages`, `django-celery-beat`, `django-prometheus`, `django-permissions-policy`, `elastic-apm`, `celery` | — | — | compatíveis ou com versão compatível publicada | idem | Ajuste de versão sem mudança de código esperada. |
| `mozilla-django-oidc` | 2.0.0 | preso por `weni-rp-apps` | 2.0.0 | 2.0.0 ou mais | O código do 2.0.0 já trata a troca de `is_safe_url`. Atualizar se o `weni-rp-apps` liberar. |
| `djangogrpcframework` | 0.2.1 | sem release desde 2021 | 0.2.1 | 0.2.1 | Usa só APIs estáveis. Nenhum uso de API removida encontrado. |
| `sentry-sdk` | 1.45.1 | — | 1.45.1 | 1.45.1 | **Não atualizar para 2.x nesta spec**: a spec 023 depende do contrato de `Hub` do 1.x (AC-6 da 023). A integração Django do 1.45.1 usa imports com alternativa para versões novas. |

## Mudanças necessárias no código de `temba/`

| Mudança | Volume | Removida em | Já possível no 3.2? |
|---------|--------|-------------|---------------------|
| `ugettext*` / `ungettext*` → `gettext*` / `ngettext*` | 189 arquivos | 4.0 | Sim |
| `django.conf.urls.url` → `re_path` / `path` | 28 arquivos | 4.0 | Sim |
| `force_text` → `force_str` | 8 arquivos | 4.0 | Sim |
| `urlquote`, `urlquote_plus` e `urlunquote` → `urllib.parse` | 6 arquivos | 4.0 | Sim |
| `is_safe_url` → `url_has_allowed_host_and_scheme` | 2 arquivos (`contacts/views.py` e `msgs/views.py`) | 4.0 | Sim |
| `request.is_ajax()` → cabeçalho `X-Requested-With` | 1 (`orgs/views.py:3597`) | 4.0 | Sim |
| Remover `smartmin.csv_imports` (app, rota `imports/` em `temba/urls.py:49` e permissões em `settings_common.py:741` e `:881`) | 3 pontos; nenhum template, view ou model usa o app | smartmin 5.1 | Sim |
| Logout por POST em vez de link GET (`orgs/views.py:3205`, `LogoutView` do smartmin) | 1 link + templates do menu | Django 5.0 | Sim |
| `index_together` → `Meta.indexes` (`ChannelCount`, dois models em `flows/models.py` e `Label` em `msgs/models.py`) | 4 models + migrations | 5.1 | **Não**: no 3.2 a troca vira remoção e recriação do índice, cara em tabelas grandes. No 4.2 existe `RenameIndex(old_fields=...)`, que é só uma renomeação. Se o autodetector não gerar essa operação sozinho, a migration MUST ser escrita à mão (FR-010). |
| `assertFormError(response, "form", ...)` → assinatura nova | cerca de 160 chamadas em 24 arquivos de teste | 5.0 | Não (a assinatura nova é do 4.1) |
| `DEFAULT_FILE_STORAGE` → `STORAGES` (`settings.py.prod:192`, `utils/s3/s3.py:76`, `assets/models.py:84` e teste em `utils/s3/tests.py:293`) | 4 pontos | 5.1 | Não (`STORAGES` é do 4.2) |
| `django.utils.timezone.utc` → `datetime.timezone.utc` | até 5 arquivos | 5.0 | Sim |
| Remover `USE_L10N` (`settings_common.py:139`) | 1 | 5.0 | Não (o padrão só muda no 4.0) |
| `pytz` → `zoneinfo` (`localize`, `normalize`, `pytz.timezone`, `pytz.UTC`) | 22 arquivos de runtime e 17 de teste; cerca de 300 usos | Django 5.0 (`USE_DEPRECATED_PYTZ`) e django-timezone-field 6.0 | Não. Ver D-3. |

## Decisões de implementação

### D-2: quatro etapas, cada uma com specs filhas (uma por PR), deploy e rollback próprios

| Etapa | Django | Conteúdo | Gate de saída |
|-------|--------|----------|---------------|
| 0 — preparação | 3.2 | Todas as trocas marcadas "Sim" na tabela acima, inclusive a remoção de `csv_imports` e o logout por POST. Filtro de avisos da FR-019. Testes de proteção das etapas seguintes, escritos e passando no 3.2: `TimezoneParityTest` (FR-012) e a compilação de todos os templates HAML (FR-021). Nenhuma dependência muda. | CI verde, deploy em produção sem regressão por 1 semana. |
| 1 — degrau 4.2 | 4.2 | Django 4.2 e dependências da coluna "Para o 4.2". `USE_DEPRECATED_PYTZ = True`, que mantém `pytz` no Django e no `TimeZoneField`. `index_together` → `indexes` com `RenameIndex`. `assertFormError` na assinatura nova. `STORAGES`. Release nova do `weni-rp-apps` publicada antes. | CI verde, deploy em produção sem regressão por 1 semana. |
| 2 — fuso horário | 4.2 | Troca de `pytz` por `zoneinfo` no código e `USE_DEPRECATED_PYTZ = False`. O `TimezoneParityTest` escrito na etapa 0 MUST passar sem nenhuma alteração nos valores esperados. | CI verde, deploy em produção sem regressão por 1 semana. |
| 3 — destino 5.2 | 5.2 | Django 5.2 e dependências da coluna "Para o 5.2". `django-hamlpy` conforme D-4. Python mínimo do `pyproject.toml` passa para 3.11. `redis` 4 ou mais. Remoção de `USE_L10N`. | CI verde, PostgreSQL ≥14 confirmado em todos os ambientes, deploy em produção. |

A janela em que produção fica no 4.2, já sem suporte, vai do deploy da etapa 1 ao da etapa 3 e MUST ficar dentro do limite da FR-024. Mesmo assim, o 4.2.30 recebeu correções de segurança até abril de 2026, mais de dois anos depois do último patch do 3.2.

Alternativa rejeitada: um PR único de 3.2 para 5.2. Junta quatro fontes independentes de regressão (APIs removidas, smartmin, fuso horário e hamlpy) num deploy só, e qualquer reversão desfaz tudo.

### D-3: a troca de fuso horário é uma etapa própria, ainda no 4.2

No 4.x, a mesma flag `USE_DEPRECATED_PYTZ` decide se o Django e o `django-timezone-field` 5.1 devolvem `pytz` ou `zoneinfo` (`timezone_field/utils.py:use_pytz_default`). `Org.timezone` é um `TimeZoneField` (`temba/orgs/models.py:313`), e há código que chama `tz.localize(...)` sobre ele: `contacts/models.py:2696`, `utils/dates.py:21`, `utils/datalake/layer_validation.py:64-65` e `msgs/models.py:1416-1420`. Com `zoneinfo`, `localize` não existe e a conversão muda de semântica nas transições de horário de verão. Fazer a troca no 4.2, com a flag como único interruptor, isola o maior risco funcional do upgrade de framework: se algo der errado, o rollback é voltar a flag e o código da etapa 2, sem mexer na versão do Django.

### D-4: `django-hamlpy` no Django 5.2

**Decisão (2026-11-27)**: fork em `weni-ai/django-hamlpy`, a partir da tag `1.7.0` do upstream (`nyaruka/django-hamlpy`), com uma única mudança funcional: o limite de Django passa de `>=3.2,<5.0` para `>=4.2,<6.0`. O fork é publicado num índice que o Poetry consiga resolver, e o `pyproject.toml` do Flows aponta para ele na etapa 3 (FR-026).

A análise do código instalado (`hamlpy/`) mostra que ele só importa `django.apps.AppConfig`, `django.conf.settings`, `django.template.TemplateDoesNotExist`, `django.template.loaders` (`app_directories` e `filesystem`), `django.utils.translation` e `django.views.generic`, todas presentes no 5.2. O risco técnico de rodar o mesmo código no 5.2 é baixo, e o teste da FR-021 o confirma. O risco que sobra é de manutenção e de cadeia de fornecimento (Principle II), coberto pela FR-026.

Alternativas rejeitadas:

- Vendorizar o pacote no Flows: mistura código de terceiros com o do projeto, e a atualização deixa de ser rastreável como dependência.
- Converter os 334 templates para HTML: muda toda a camada de templates junto com o framework, contra a D-2 e o Principle XVI.

## Escopo neste repositório

**Muda**:

- `pyproject.toml` e `poetry.lock`.
- Código de `temba/` listado em "Mudanças necessárias no código de `temba/`".
- `temba/settings_common.py` e `temba/settings.py.prod`: `USE_DEPRECATED_PYTZ` (temporário), `STORAGES`, remoção de `USE_L10N` e de `smartmin.csv_imports`.
- Migrations geradas pela troca de `index_together` (só `RenameIndex`) e pelas dependências atualizadas (`django-celery-beat`, `smartmin.users`, `django-mptt` e afins), quando houver.
- Templates do menu de usuário (logout por POST).
- `WENI-CHANGELOG.md`: um bullet por spec filha com mudança visível.

**Não muda**:

- Versão do Python em runtime (continua 3.11) e a imagem base do Docker.
- `sentry-sdk` (continua 1.45.1) e o comportamento do Sentry fixado pelas specs 022 e 023.
- Contratos públicos (Principle IV), Courier e Mailroom, inclusive a versão do Mailroom usada no CI (`7.1.22`).
- Os templates HAML (nenhuma conversão para HTML).
- Refatorações, renomeações ou mudanças de comportamento sem relação com o upgrade (Principle XVI).
- A tabela `csv_imports_importtask` no banco. Remover o app não apaga a tabela, e apagá-la fica para outra mudança.

## User Scenarios & Testing *(mandatory)*

Quem usa esta mudança: os usuários do Flows (web e API), que não podem perceber diferença; os desenvolvedores, que passam a ter um framework com correções de segurança; e o time de plataforma, que precisa de deploys pequenos e reversíveis.

### User Story 1 - Código preparado sem trocar a versão do Django (Priority: P1)

Um desenvolvedor aplica todas as trocas compatíveis com o 3.2 (etapa 0). O comportamento da aplicação não muda e a diferença das etapas seguintes fica menor.

**Why this priority**: Reduz o tamanho e o risco das etapas seguintes, pode ir para produção imediatamente e não depende de nenhum outro time.

**Independent Test**: CI verde no 3.2, com o filtro da FR-019 transformando em erro todo `RemovedInDjango40Warning` emitido por código de `temba/`.

**Acceptance Scenarios**:

1. **Given** o Django 3.2, **When** a suíte roda, **Then** nenhum código de `temba/` usa `ugettext`, `force_text`, `django.conf.urls.url`, `urlquote`, `is_safe_url` ou `is_ajax`.
2. **Given** um usuário logado, **When** ele clica em "Sair", **Then** a sessão termina por um POST com token CSRF. Um GET na rota de logout continua funcionando nesta etapa e é registrado em log, para identificar chamadores externos antes da etapa 3, quando o Django 5.0 o recusa (spec 027, FR-016).
3. **Given** a remoção de `smartmin.csv_imports`, **When** alguém acessa `/imports/`, **Then** recebe 404, e nenhuma outra tela ou permissão de grupo deixa de funcionar.

---

### User Story 2 - Flows rodando no Django 4.2 sem diferença para o usuário (Priority: P2)

O time faz deploy do Flows no 4.2 (etapa 1), com `pytz` ainda ativo. Telas, API, tasks e consumers funcionam como antes.

**Why this priority**: É o degrau que libera as versões novas de `smartmin`, `django-compressor` e companhia sem trocar ainda a semântica de fuso horário.

**Independent Test**: CI verde no 4.2. `makemigrations --check` limpo. As migrations de `index_together` contêm só operações `RenameIndex`.

**Acceptance Scenarios**:

1. **Given** o Django 4.2 e `USE_DEPRECATED_PYTZ = True`, **When** `Org.timezone` é lido, **Then** devolve um objeto `pytz`, como no 3.2.
2. **Given** as migrations da etapa, **When** rodam num banco com os índices atuais, **Then** só renomeiam índices, sem recriá-los.
3. **Given** a release nova do `weni-rp-apps`, **When** o app sobe, **Then** as rotas de `weni/` (auth, s3, analytics, channel stats e ticketer queues) respondem como antes.
4. **Given** `COMPRESS_OFFLINE = True` em produção, **When** a imagem é construída, **Then** a compressão offline dos assets termina sem erro.

---

### User Story 3 - Datas e fusos corretos com `zoneinfo` (Priority: P2)

O time desliga `pytz` (etapa 2). Datas, filtros por período, agendamentos e exports de cada org continuam iguais, inclusive em fusos com horário de verão.

**Why this priority**: É o maior risco funcional do upgrade e precisa ser verificado sozinho, antes do 5.2.

**Independent Test**: o `TimezoneParityTest`, escrito na etapa 0 com valores esperados calculados pelo código atual com `pytz`, passa sem alteração depois da troca (FR-012).

**Acceptance Scenarios**:

1. **Given** uma org em `America/Sao_Paulo`, `Africa/Kigali`, `America/New_York` ou `Europe/Dublin`, **When** um filtro por data local é convertido para UTC, **Then** o intervalo em UTC é o mesmo da implementação com `pytz`, inclusive no dia da transição de horário de verão.
2. **Given** um horário local inexistente ou ambíguo (transição de horário de verão), **When** é convertido, **Then** o resultado segue a regra registrada na FR-013, e não um deslocamento silencioso.
3. **Given** `USE_DEPRECATED_PYTZ = False`, **When** a suíte roda, **Then** nenhum código de `temba/` chama `localize` ou `normalize` de `pytz`.

---

### User Story 4 - Flows rodando no Django 5.2 LTS (Priority: P3)

O time faz deploy do Flows no 5.2 (etapa 3). Telas smartmin e HAML, login, API, tasks e consumers funcionam como antes, e o framework volta a ter suporte de segurança.

**Why this priority**: É o objetivo final, mas depende das três etapas anteriores e da decisão D-4.

**Independent Test**: CI verde no 5.2, AC-1 a AC-7.

**Acceptance Scenarios**:

1. **Given** o Django 5.2, **When** cada template HAML é compilado, **Then** nenhum falha (FR-021).
2. **Given** o `smartmin` 5.2.x, **When** as views CRUDL de `temba/` são exercitadas pela suíte, **Then** passam sem mudança de asserção.
3. **Given** o `redis` 4 ou mais e o `django-redis` 6, **When** o cache, os locks e a idempotência do endpoint de stream (spec 022) rodam, **Then** se comportam como antes.
4. **Given** um ambiente com PostgreSQL abaixo de 14, **When** o deploy da etapa 3 é preparado, **Then** ele é bloqueado (FR-023).

---

### Edge Cases

- **Rollback da etapa 1 para o 3.2**: o 3.2 não conhece `RenameIndex`. Antes de voltar a imagem, as migrations da etapa MUST ser revertidas com o código do 4.2 (FR-025).
- **Sessões e senhas entre versões**: o 4.x e o 5.x aumentam as iterações do PBKDF2, e o rehash acontece no login. O hash guarda o número de iterações, então uma versão anterior continua validando a senha num rollback. A compatibilidade das sessões assinadas entre o 3.2 e o 4.2 MUST ser verificada em staging, com uma sessão criada numa versão e lida na outra, nos dois sentidos.
- **`TimeZoneField` com valor fora de `zoneinfo`**: um fuso salvo que exista no `pytz` mas não no `tzdata` do sistema MUST ser detectado antes da etapa 2 (FR-014).
- **Processo FastAPI** (`temba/fastapi_app`, uvicorn): chama `django.setup()` e usa o ORM, então MUST subir em cada etapa (FR-020).
- **Consumers RabbitMQ e Celery beat**: usam o ORM e `django-celery-beat`, então MUST subir e processar uma mensagem de teste em cada etapa.
- **`TEST_EXCLUDE = ("smartmin",)`**: os testes do próprio smartmin continuam fora da suíte.
- **`COMPRESS_OFFLINE_CONTEXT`** (`settings.py.prod:125` e `settings_common.py:1235`): a compressão offline depende de renderizar templates no build. Uma falha nela quebra o build da imagem, não o runtime.

## Requirements *(mandatory)*

### Functional Requirements

**Gerais**

- **FR-001**: Todo PR integrado em `main` MUST ter spec filha própria, e cada spec filha MUST ser entregue em exatamente um PR, com CI verde. Uma etapa de D-2 pode ter várias specs filhas. Nenhuma spec filha MUST misturar mudanças de etapas diferentes. A etapa só termina quando todas as suas specs filhas estiverem em produção nos três ambientes, cada uma com a sua entrada no `WENI-CHANGELOG.md` quando tiver mudança visível.
- **FR-002**: Nenhuma etapa MUST alterar payload, status ou cabeçalho de resposta de endpoint DRF ou FastAPI, configuração de canal lida pelo Courier ou evento do RabbitMQ (Principle IV).
- **FR-003**: Nenhuma etapa MUST pular teste, acrescentar `# pragma: no cover` ou mudar asserção de comportamento. A única mudança de teste permitida é na forma de chamar APIs de teste do Django (por exemplo, a assinatura nova de `assertFormError`).
- **FR-004**: Toda dependência atualizada MUST ser declarada em `pyproject.toml` e travada em `poetry.lock`, vir do PyPI ou de um índice aprovado e passar por checagem de vulnerabilidades conhecidas (Principle II).
- **FR-005**: `sentry-sdk` MUST continuar na série 1.x, e os testes das specs 022 e 023 sobre o Sentry MUST continuar passando sem alteração.

**Etapa 0 (Django 3.2)**

- **FR-006**: O código de `temba/` MUST deixar de usar `ugettext*`, `ungettext*`, `force_text`, `django.conf.urls.url`, `urlquote*`, `urlunquote`, `is_safe_url`, `request.is_ajax()` e `django.utils.timezone.utc`.
- **FR-007**: `smartmin.csv_imports` MUST sair de `INSTALLED_APPS`, de `temba/urls.py` e das permissões de grupo em `settings_common.py`, sem migration que apague a tabela.
- **FR-008**: O logout MUST ser feito por POST com token CSRF em todos os pontos da interface que hoje usam link GET.

**Etapa 1 (Django 4.2)**

- **FR-009**: `USE_DEPRECATED_PYTZ` MUST ser `True` durante a etapa 1, e `Org.timezone` MUST continuar devolvendo `pytz`.
- **FR-010**: Os quatro `index_together` MUST virar `Meta.indexes` com os mesmos campos e na mesma ordem, e as migrations geradas MUST conter só `RenameIndex` para esses índices.
- **FR-011**: `DEFAULT_FILE_STORAGE` MUST ser substituído por `STORAGES`, mantendo a mesma classe de storage padrão em cada ambiente e a variável de ambiente que a escolhe hoje em `settings.py.prod:192`.

**Etapa 2 (fuso horário, ainda no 4.2)**

- **FR-012**: MUST existir `temba.utils.tests.TimezoneParityTest`, **escrito na etapa 0**. Para cada função de runtime que aplica um fuso diferente de UTC, ele compara a saída com valores esperados, calculados pelo código atual com `pytz` e fixados no teste, em pelo menos `UTC`, `America/Sao_Paulo`, `Africa/Kigali`, `America/New_York` e `Europe/Dublin`, incluindo os dias de transição de horário de verão. Na etapa 2, os valores esperados MUST NOT mudar. O inventário fechado na spec 025 deixa de fora a conversão cujo fuso é UTC e os comandos de management que só montam banco local (`test_db`, `mailroom_db`).
- **FR-013**: Horários locais inexistentes ou ambíguos MUST ter uma regra explícita e testada (`fold` do `zoneinfo`), escolhida para reproduzir o resultado atual do `pytz` (`localize` com `is_dst=False`).
- **FR-014**: Antes do deploy da etapa 2, uma consulta em cada ambiente MUST confirmar que todo valor distinto de `orgs_org.timezone` é aceito por `zoneinfo.ZoneInfo`. Os valores recusados MUST ser corrigidos antes do deploy.
- **FR-015**: Ao final da etapa 2, `USE_DEPRECATED_PYTZ` MUST ser `False` ou ausente, e nenhum código de runtime de `temba/` MUST importar `pytz`.

**Etapa 3 (Django 5.2)**

- **FR-016**: MUST existir um teste que faz logout por POST e verifica o fim da sessão, e outro que verifica que um GET na rota de logout não encerra a sessão. Antes da etapa 3, os chamadores externos encontrados pelo log `logout via GET` da etapa 0 MUST ter migrado para POST ou estar registrados na tabela de status, com responsável.
- **FR-017**: As chamadas de `assertFormError` e `assertFormsetError` MUST usar a assinatura que recebe o formulário (disponível desde o 4.1). Esta parte pode ser feita na etapa 1.
- **FR-018**: `USE_L10N` MUST ser removido das settings.
- **FR-019**: Toda execução de teste MUST transformar em erro os avisos de remoção do Django da próxima série (`RemovedInDjango40Warning` na etapa 0, `RemovedInDjango50Warning` e `RemovedInDjango51Warning` nas etapas 1 e 2, `RemovedInDjango60Warning` na etapa 3) atribuídos a módulos `temba.*`. O filtro MUST ser instalado antes de `django.setup()`, porque parte dos avisos é emitida na importação dos models e das URLs. Ele fica no bloco `if TESTING:` de `temba/settings_common.py`, com `module=r"temba\."`. A opção `-W` da linha de comando não serve: o campo de módulo dela exige o nome completo do módulo. Esta FR é introduzida na etapa 0 e atualizada a cada etapa.
- **FR-020**: O processo FastAPI, os consumers RabbitMQ, o Celery worker e o Celery beat MUST subir e processar uma requisição ou mensagem de teste no ambiente de staging antes do deploy de cada etapa em produção.
- **FR-021**: MUST existir um teste que carrega e compila todo template HAML de `templates/` e `temba/` com os loaders configurados, e falha se algum lançar erro.
- **FR-022**: O limite inferior de Python em `pyproject.toml` MUST passar para 3.11, exigido pelo `smartmin` 5.2.x. A imagem Docker e o CI já usam 3.11.
- **FR-023**: O deploy da etapa 3 MUST ser bloqueado enquanto algum ambiente (shared, India ou Ireland, em staging ou produção) rodar PostgreSQL abaixo de 14 ou PostGIS fora da faixa suportada pelo Django 5.2.

**Operação**

- **FR-024**: Produção MUST ficar no Django 4.2 por no máximo 8 semanas, contadas do deploy da etapa 1. Se a etapa 3 não estiver pronta nesse prazo, o motivo e a nova data MUST ser registrados neste spec.
- **FR-025**: Cada PR MUST descrever o procedimento de rollback da própria mudança, incluindo a ordem entre reverter migrations e voltar a imagem.
- **FR-026**: O fork `weni-ai/django-hamlpy` (D-4) MUST diferir da tag `1.7.0` do upstream só nos metadados de versão e no limite de Django, MUST rodar a suíte de testes do próprio pacote no Django 4.2 e no 5.2 e MUST ter um dono nomeado na Weni. O Flows MUST travá-lo por versão exata e hash no `poetry.lock`.

### Key Entities

- **Org.timezone**: fuso de cada org, guardado como texto e devolvido como objeto de fuso. É o ponto onde a troca de `pytz` por `zoneinfo` aparece para o usuário.
- **Índices de `index_together`**: quatro índices compostos em tabelas de contagem e de label (`ChannelCount`, dois models de contagem em `flows/models.py` e `Label`). Só mudam de nome.
- **Tabela `csv_imports_importtask`**: fica órfã depois da etapa 0, sem uso pelo código.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Ao fim da etapa 3, os três ambientes de produção rodam uma versão do Django com suporte de segurança até pelo menos abril de 2028.
- **SC-002**: Em cada etapa, os quatro grupos do CI terminam verdes, com zero testes pulados e zero `# pragma: no cover` novos.
- **SC-003**: Na semana seguinte a cada deploy, a taxa de erros 5xx e de eventos novos no Sentry fica no máximo 10% acima da média das 4 semanas anteriores, e nenhum erro novo aparece mais de 100 vezes por dia.
- **SC-004**: Na semana seguinte a cada deploy, o p95 de latência dos endpoints web e de API e a duração das tasks Celery mais frequentes ficam no máximo 10% acima da semana anterior ao deploy, medidos no horário de pico.
- **SC-005**: Zero chamados de suporte atribuídos a data, hora ou fuso errado nas 2 semanas seguintes ao deploy da etapa 2.
- **SC-006**: Ao fim, zero `DeprecationWarning` do Django emitidos por código de `temba/` na suíte completa.
- **SC-007**: Nenhuma etapa exige mais de 15 minutos de janela de manutenção. As migrations previstas são só renomeações.

## Peak Load (Principle XII)

Nenhum caminho novo de requisição, task ou consumer é criado, e nenhum estado novo é introduzido. A carga sustentada pela mudança é o pico atual de todo o Flows. O critério é de não regressão (SC-004), comparado ao pico da semana anterior a cada deploy.

- **Valor numérico**: **medição pendente**. O repositório não tem métricas de produção. O p95 e o throughput de pico dos endpoints web, de `temba/api` e das tasks Celery mais frequentes MUST ser medidos e registrados aqui antes do deploy da etapa 1.

## Assumptions

- A Weni consegue publicar a release do `weni-rp-apps` compatível com o 4.2 e o 5.2 antes da etapa 1. É dependência bloqueante, com dono fora deste repositório.
- O fork `weni-ai/django-hamlpy` (D-4, FR-026) fica publicado antes da etapa 3. Não bloqueia as etapas 0 a 2.
- Staging existe para os três ambientes e recebe cada etapa antes de produção (`.github/workflows/build-flows-push-tag-*.yaml` distinguem DEVELOP, STAGING e PRODUCTION).
- A versão de PostgreSQL de produção é desconhecida. A CI usa 15. A FR-023 trata isso como gate da etapa 3, e não da 1 ou da 2: o Django 4.2 exige 12 ou mais.
- O prazo de 8 semanas no 4.2 (FR-024) e os limites de 10% de regressão (SC-003 e SC-004) são padrões razoáveis e podem ser ajustados no `/speckit-clarify`.
- O Mailroom (Go, `7.1.22`) e o Courier compartilham o banco, mas não dependem de nome de índice nem da versão do Django.
- A rota `/imports/` do smartmin não é usada por usuários: nenhum template, view ou link do Flows aponta para ela.

## Test Strategy

**Testes novos**:

| Teste | Cobre | Etapa |
|-------|-------|-------|
| `temba.utils.tests.DjangoVersionTest.test_runs_supported_lts` | AC-1 | 3 (fixa a série do Django em cada etapa) |
| Logout por POST encerra a sessão (etapa 0); GET não encerra (etapa 3) | AC-5, FR-008, FR-016 | 0 (spec 027) e 3 |
| `temba.utils.tests.TimezoneParityTest` | AC-4, FR-012 (FR-013 acrescenta casos na etapa 2) | 0 (spec 025; passa no 3.2 com `pytz` e protege a etapa 2) |
| Compilação de todos os templates HAML | AC-5, FR-021 | 0 (spec 025; passa no 3.2 e protege as etapas 1 e 3) |
| `/imports/` responde 404 e as permissões de grupo carregam sem `csv_imports` | FR-007 | 0 (spec 028) |

**Testes existentes que fecham os critérios**: a suíte completa nos quatro grupos (AC-2 e AC-6), em especial `temba.orgs` (login, logout e convites), `temba.api` (contratos), `temba.fastapi_app`, `temba.api.v2.internals.msgs` (Sentry e idempotência no Redis, specs 022 e 023), `temba.utils.dates` e `temba.utils.datalake` (fusos) e `temba.utils.s3` (storage).

**Comandos por etapa**:

```sh
poetry run coverage run manage.py test --keepdb --noinput
poetry run python manage.py makemigrations --check --dry-run
./code_check.py
```

## Rollout and Rollback

| Etapa | Rollout | Rollback |
|-------|---------|----------|
| 0 | Deploy normal. | Voltar a imagem. Não há migration. |
| 1 | Staging dos três ambientes → produção. Migrations de `RenameIndex` antes da troca de imagem. | Reverter as migrations da etapa **com a imagem do 4.2** e depois voltar para a imagem do 3.2 (FR-025). |
| 2 | FR-014 rodada em cada ambiente → staging → produção. | Voltar a imagem da etapa 1 (que reativa `USE_DEPRECATED_PYTZ`). Não há migration. |
| 3 | FR-023 confirmada → staging → produção. | Reverter as migrations novas das dependências, se houver, com a imagem do 5.2, e voltar para a imagem da etapa 2. |

## Constitution Alignment

Revisão preliminar. O Constitution Check formal fica no `plan.md` (SDD Full).

| Princípio | Como esta mudança cumpre |
|-----------|--------------------------|
| I. Version Control and Review | Uma spec filha por PR, com review e CI verde, uma ou mais por etapa, sem misturar etapas (FR-001). |
| II. Security and Secrets | Atualiza dependências sem suporte de segurança. Toda dependência fica travada no `poetry.lock` e checada (FR-004). D-4 trata a cadeia de fornecimento do `hamlpy`. `mozilla-django-oidc` (autenticação) e `cryptography` são citados. |
| III. Observability | `sentry-sdk` mantido (FR-005). SC-003 monitora erros por etapa. |
| IV. Versioned Contracts | Nenhum contrato muda (FR-002, AC-6). As migrations ficam no mesmo PR e são reversíveis (FR-025). Versões de Courier e Mailroom inalteradas. |
| V. Specification Traceability | Abre com `## Origin Without Product Spec`. Cada AC aponta para um teste ou gate. |
| VI. No Silent Divergence | Não se aplica: não há Product Spec. |
| VII. Commit Messages | Commits atômicos por tipo de troca (por exemplo, `refactor: replace ugettext with gettext`, `chore: upgrade django to 4.2`). |
| VIII. Changelog Maintenance | Um bullet por spec filha com mudança visível (FR-001). O logout por POST (spec 027) é marcado como mudança de segurança. |
| IX. Never Trust the Client | A troca de `is_safe_url` por `url_has_allowed_host_and_scheme` mantém a validação de redirect. O logout passa a exigir POST com CSRF (FR-008). |
| X. Fail Gracefully | O cliente Redis mantém timeouts explícitos após a troca para `redis` 4 ou mais (US4, cenário 3). |
| XI. Bounded Retry | Não se aplica: nenhuma propagação entre serviços muda. |
| XII. Scalability and Peak Load | Nenhum estado novo. Peak Load declarado como não regressão, com o valor numérico pendente antes da etapa 1. |
| XIII. Diagnosable Errors | Não muda o que vai para o Sentry. |
| XIV. Tests Exercise Flows | Testes novos de logout, fuso, HAML e versão. Nenhum teste pulado nem asserção alterada (FR-003). |
| XV. Explicit Over Clever | `USE_DEPRECATED_PYTZ` é um interruptor explícito e temporário (FR-009, FR-015). Os prazos e limites estão em requisitos nomeados. |
| XVI. Contained Changes | Só o necessário para cada etapa. Refatorações fora do upgrade ficam proibidas ("Não muda"). |
| XVII. Explicit, Scoped Authorization | Não se aplica: nenhuma permissão de endpoint muda. A remoção das permissões `csv_imports.importtask.*` tira acesso a uma rota que deixa de existir. |
