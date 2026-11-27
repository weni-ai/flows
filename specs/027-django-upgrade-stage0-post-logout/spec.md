# Engineering Spec: etapa 0 do upgrade do Django, parte 3 — logout por POST

**Repository**: weni-ai/flows — backend

**Feature Branch**: a criar (sugestão: `fix/post-logout`)

**Created**: 2026-11-27

**Status**: Draft

**Input**: Terceira das quatro specs da etapa 0 da spec guarda-chuva [024-django-5-2-upgrade](../024-django-5-2-upgrade/spec.md): passar o link "sign out" para POST com token CSRF, mantendo o GET nesta etapa e registrando em log quem ainda o usa, antes que o Django 5.0 deixe de aceitá-lo.

**Cycle**: SDD Lite. A mudança fica no app `orgs` (view e testes), na rota de `temba/urls.py` e num template, sem migration, sem contrato público do Principle IV, sem Courier ou Mailroom e sem tipo de canal. A spec é o único artefato de desenho, por isso nomeia arquivos, linhas e a ordem de implementação. Se a revisão pedir `tasks.md` e `/speckit-implement`, a spec é promovida a SDD Full com `/speckit-plan`.

## Origin Without Product Spec

- Product Spec: none
- Contexto: etapa 0 da spec 024 (D-2). Esta spec cobre a FR-008 da 024 e prepara a FR-016 da etapa 3. Depende da [026](../026-django-upgrade-stage0-removed-apis/spec.md) em `main`.
- Problem: O link "sign out" faz logout por GET, que o Django 5.0 deixa de aceitar, e um GET de logout pode ser disparado por qualquer página de terceiros (sem proteção CSRF). Também não se sabe se algum sistema externo (o Weni Connect, por exemplo) faz logout por GET.
- Acceptance criteria:
  - AC-1: Clicar em "sign out" encerra a sessão por POST com token CSRF. Teste: `temba.orgs.tests.LogoutTest.test_post_logs_out` (novo) e `test_nav_sign_out_link_is_posterized` (novo).
  - AC-2: Um logout por GET continua funcionando nesta etapa e fica registrado em log, sem dado pessoal, para identificar chamadores externos antes da etapa 3. Teste: `temba.orgs.tests.LogoutTest.test_get_logs_out_and_is_logged` (novo).
  - AC-3: Um POST de logout sem token CSRF é recusado e a sessão continua. Teste: `temba.orgs.tests.LogoutTest.test_post_without_csrf_is_rejected` (novo).
  - AC-4: Os quatro grupos de `.github/workflows/ci.yml` ficam verdes, sem nenhum teste pulado e sem nenhum `# pragma: no cover` novo, e `./code_check.py` termina limpo, inclusive `makemigrations --check`.

## Decisões de implementação

### D-1: logout por POST pelo mecanismo `posterize` que já existe

O link "sign out" de `templates/includes/nav.haml:247` ganha a classe `posterize`. `templates/frame.haml` já liga `.posterize` (linha 636) a um form POST com `{% csrf_token %}` (linhas 557-559), e esse padrão já é usado para trocar de org (`frame.haml:293`) e em vários menus. Com `posterize`, os parâmetros da query viram campos ocultos do POST, então o `next` continua chegando.

### D-2: GET continua funcionando e é registrado

A rota `users/logout/` passa a ser declarada em `temba/urls.py` antes do `include("smartmin.users.urls")`, mantendo o nome `users.user_logout`. Ela aponta para uma subclasse do `LogoutView` do Django com o mesmo comportamento efetivo da rota do smartmin.

Esse comportamento efetivo não é o que os argumentos do smartmin sugerem. Em `smartmin/users/urls.py:14`, o smartmin passa `redirect_field_name="go"` e `next_page` como terceiro argumento de `url()`, ou seja, como kwargs da view, e o `LogoutView` os ignora. Na prática, o redirecionamento hoje usa o parâmetro `next` da requisição quando é seguro (o nav manda `?next=/users/login`). Quando o `next` é recusado, vai para o próprio caminho do logout. Sem `next`, vai para `LOGOUT_REDIRECT_URL` (`"/"`). A subclasse herda isso sem sobrescrever nada (FR-002).

A única diferença da subclasse é registrar `logger.info("logout via GET", extra={"referer_host": ...})` quando o método é GET, só com o host do `Referer` e sem identificador de usuário. O log fica em `dispatch`, porque o `dispatch` do `LogoutView` do 3.2 encerra a sessão e redireciona sem chamar `get()`.

Alternativas rejeitadas:

- Recusar GET já nesta etapa: antecipa a quebra de chamadores desconhecidos para um momento em que nada obriga a isso, e sem dado sobre quem são.
- Registrar o log num middleware: esconde o comportamento fora da view (Principle XV).
- Declarar a rota em `temba/orgs/urls.py`, como `users/login/`: também ganharia do smartmin, mas a ordem explícita ao lado do include em `temba/urls.py` deixa o motivo visível.

## Escopo neste repositório

**Muda**:

- `temba/orgs/views.py`: `logger` no nível do módulo e `class LogoutView(AuthLogoutView)`, logo depois de `LoginView`.
- `temba/urls.py`: rota `users/logout/` imediatamente antes de `path("users/", include("smartmin.users.urls"))`.
- `templates/includes/nav.haml:247`: classe `posterize` no link "sign out".
- `temba/orgs/tests.py`: `LogoutTest`.
- `WENI-CHANGELOG.md`: um bullet `fix` sob a próxima versão, marcado como mudança de segurança.

**Não muda**:

- Nenhuma dependência, migration ou setting.
- O trecho comentado de `temba/orgs/views.py:3197-3208` (link de logout do menu do SPA, dentro de uma string comentada) e o `logger` local da linha 1309.
- O ramo `orgs.org_service` do nav, que já usa `posterize`.
- Qualquer template HAML além de `includes/nav.haml`.

## User Scenarios & Testing *(mandatory)*

Quem usa esta mudança: os usuários do Flows, que continuam saindo do sistema pelo mesmo link; e o time que vai fazer a etapa 3, que precisa saber quem ainda faz logout por GET.

### User Story 1 - Logout por POST (Priority: P1)

O usuário clica em "sign out" e a sessão termina por um POST com token CSRF. Chamadas GET continuam funcionando nesta etapa e ficam registradas em log.

**Why this priority**: O Django 5.0 deixa de aceitar logout por GET. Mudar agora, observando os GETs, evita uma quebra surpresa na etapa 3.

**Independent Test**: `poetry run python manage.py test temba.orgs.tests.LogoutTest --keepdb`, conforme [contracts/users-logout.behavior.md](contracts/users-logout.behavior.md).

**Acceptance Scenarios**:

1. **Given** um usuário logado na tela com `includes/nav.haml`, **When** ele clica em "sign out", **Then** o navegador faz POST para `users.user_logout` com o token CSRF e `next=/users/login`, a sessão termina e ele é redirecionado para `/users/login`, como hoje.
2. **Given** um POST de logout com `next` apontando para outro host, **When** a requisição chega, **Then** a sessão termina e o redirecionamento não vai para o outro host: vai para o próprio caminho do logout, como hoje.
3. **Given** um usuário logado, **When** chega um GET em `/users/logout/`, **Then** a sessão termina como hoje e um log `logout via GET` é emitido só com o host do `Referer`.
4. **Given** um POST para o logout sem token CSRF, **When** a requisição chega, **Then** responde 403 e a sessão continua.

### Edge Cases

- **Logout chamado de dentro do SPA** (`spa_frame.haml`): o menu do SPA não tem link de logout hoje, porque o trecho de `orgs/views.py` está comentado. Nada muda ali.
- **Rota `users/logout/` declarada duas vezes**: a do Flows vem antes do include do smartmin e ganha, porque o Django resolve na ordem. A do smartmin fica inalcançável. O `reverse("users.user_logout")` devolve `/users/logout/` nos dois casos, porque o caminho é o mesmo.
- **`Referer` malformado** (por exemplo, colchete de IPv6 aberto): o `urlparse` levanta `ValueError`, que vira `referer_host=None`. Sem esse tratamento, um cabeçalho do cliente derrubaria o logout com 500 (Principles IX e X).
- **`next` recusado gera um GET de dentro do próprio Flows**: o `LogoutView` redireciona para o próprio caminho do logout, e o navegador segue com um GET, que gera um `logout via GET` com o host do Flows no `Referer`. A contagem do SC-002 separa os hosts do Flows dos demais.
- **Outros métodos** (HEAD, OPTIONS, PUT): continuam encerrando a sessão, como hoje no `LogoutView` do 3.2, e não geram log. A FR-003 só pede o log do GET.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O link "sign out" de `templates/includes/nav.haml` MUST fazer POST com token CSRF pelo mecanismo `posterize` (024 FR-008).
- **FR-002**: A rota `users/logout/` MUST manter o nome `users.user_logout` e o redirecionamento efetivo de hoje, que vale para GET e para POST: o `next` da requisição quando passa na validação de host do Django; o próprio caminho do logout quando o `next` é recusado (comportamento do `LogoutView` do 3.2); e `LOGOUT_REDIRECT_URL` quando não há `next`. A subclasse MUST NOT sobrescrever `next_page`, `redirect_field_name` nem `get_next_page`.
- **FR-003**: Um GET na rota de logout MUST continuar encerrando a sessão nesta etapa e MUST emitir um log `logout via GET` com, no máximo, o host do `Referer`. O log MUST NOT conter identificador de usuário, e-mail, cookie, caminho completo do `Referer`, porta, usuário e senha do `Referer` nem query string.
- **FR-004**: Um POST na rota de logout sem token CSRF válido MUST responder 403 e manter a sessão.
- **FR-005**: `WENI-CHANGELOG.md` MUST ganhar, sob a próxima versão, um bullet `fix:` que cite o logout por POST com proteção CSRF como mudança de segurança.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero chamados de suporte sobre login ou logout na semana seguinte ao deploy, e a taxa de 5xx e de eventos novos no Sentry no máximo 10% acima da média das 4 semanas anteriores (024 SC-003).
- **SC-002**: Duas semanas depois do deploy, a contagem de logs `logout via GET` por `referer_host`, separando os hosts do próprio Flows, fica registrada na tabela "Etapas e specs filhas" da 024, antes de abrir a primeira spec da etapa 1.

## Peak Load (Principle XII)

Não se aplica. O log de GET custa uma linha por logout. Nenhum estado novo é introduzido.

## Assumptions

- O clique em `.posterize` funciona em todas as telas que incluem `includes/nav.haml`, porque o handler está em `templates/frame.haml`, que inclui o nav (linha 307).
- O `CsrfViewMiddleware` (`settings_common.py:234`) recusa o POST sem token antes da view, com 403. GET, HEAD e OPTIONS não passam pela checagem de CSRF, como hoje.

## Detalhes técnicos

### Sessão no logout

Estados: **autenticada** (a sessão tem `_auth_user_id`) e **encerrada** (sem `_auth_user_id`).

| De | Evento | Para | Resposta | Log |
|---|---|---|---|---|
| autenticada | POST com CSRF válido | encerrada | 302 (destino no [contrato](contracts/users-logout.behavior.md)) | nenhum |
| autenticada | POST sem CSRF ou com CSRF inválido | autenticada | 403 do `CsrfViewMiddleware`; a view não roda | nenhum |
| autenticada | GET | encerrada | 302, como hoje | `logout via GET` |
| anônima | GET | anônima | 302 | `logout via GET` |
| anônima | POST com CSRF válido | anônima | 302 | nenhum |

### Registro `logout via GET`

| Campo | Valor | Regra |
|---|---|---|
| logger | `temba.orgs.views` | `logging.getLogger(__name__)` no nível do módulo (`logging` já é importado). |
| nível | `INFO` | |
| mensagem | `logout via GET` | Literal fixo, sem interpolação. |
| `referer_host` (em `extra`) | `str` em minúsculas ou `None` | `urlparse(request.META.get("HTTP_REFERER", "")).hostname`, que descarta usuário, senha, porta, caminho e query. É `None` sem `Referer` ou com `ValueError` do `urlparse`. |

### Implementação, na ordem

1. **Testes primeiro**, em `temba/orgs/tests.py`, na `class LogoutTest(TembaTest)` da Test Strategy. Rodar `poetry run python manage.py test temba.orgs.tests.LogoutTest --keepdb` e registrar as quatro falhas com o motivo. Um teste que passe aqui está errado e é corrigido antes de seguir.
2. **View**, em `temba/orgs/views.py`:
   - `LogoutView as AuthLogoutView` no import de `django.contrib.auth.views`, junto de `LoginView as AuthLoginView`;
   - `logger = logging.getLogger(__name__)` no nível do módulo;
   - `class LogoutView(AuthLogoutView)` logo depois de `class LoginView`, com docstring de uma linha sobre o porquê (achar quem ainda faz logout por GET antes de o Django deixar de aceitar);
   - sobrescrever só `dispatch(self, request, *args, **kwargs)`: quando `request.method == "GET"`, calcular `referer_host` e emitir o log; depois, `return super().dispatch(request, *args, **kwargs)`, que mantém o `auth_logout`, o redirecionamento e o `never_cache` da classe base.
3. **Rota**, em `temba/urls.py`: `from temba.orgs.views import LogoutView` e `path("users/logout/", LogoutView.as_view(), name="users.user_logout")` na linha imediatamente anterior a `path("users/", include("smartmin.users.urls"))`, com um comentário de uma linha: a rota precisa vir antes do include para ganhar da rota de logout do smartmin.
4. **Template**: em `templates/includes/nav.haml:247`, `%a(href="{% url 'users.user_logout' %}?next=/users/login")` vira `%a.posterize(href="{% url 'users.user_logout' %}?next=/users/login")`.
5. Rodar `poetry run python manage.py test temba.orgs.tests.LogoutTest temba.utils.tests.HamlTemplatesCompileTest temba.orgs --keepdb`: os quatro testes de `LogoutTest` passam, o `nav.haml` compila e os testes atuais de login e logout continuam verdes.
6. **Changelog** (FR-005).

Commits (até 50 caracteres): `fix: log out via post with csrf` (testes e implementação juntos, para que todo commit fique verde; a execução vermelha do passo 1 fica na descrição do PR) e `docs: note post logout in changelog`.

## Test Strategy

**Testes novos**, em `temba.orgs.tests.LogoutTest(TembaTest)`:

| Teste | Passos | Verifica | Cobre |
|---|---|---|---|
| helper `_assert_served_by_flows_logout(response)` | compara `f"{view_class.__module__}.{view_class.__qualname__}"`, com `view_class = response.resolver_match.func.view_class`, com `"temba.orgs.views.LogoutView"`, só por texto | a rota é atendida pela view do Flows | FR-002 |
| `test_post_logs_out` | `login(self.admin)` e POST em `reverse("users.user_logout")`, três vezes: `next=/users/login`, `next=https://evil.example/` e sem `next`, com novo login antes de cada uma; `assertNoLogs("temba.orgs.views", "INFO")` | 302 para `/users/login`, para `/users/logout/` e para `/`; `_auth_user_id` fora da sessão; o helper | AC-1, FR-002 |
| `test_nav_sign_out_link_is_posterized` | `login(self.admin)` e GET em `reverse("msgs.msg_inbox")` | com regex sobre o HTML, o `<a>` cujo `href` é `/users/logout/?next=/users/login` tem a classe `posterize`; a página tem `id="posterizer"` (ou com aspas simples, conforme a saída do hamlpy) e `csrfmiddlewaretoken` | AC-1, FR-001 |
| `test_get_logs_out_and_is_logged` | `login(self.admin)`; em `assertLogs("temba.orgs.views", "INFO")`, GET com `?next=/users/login` e `HTTP_REFERER="https://user:secret@Connect.Example.com:8443/path?token=abc"`; depois GET sem `Referer` e GET com `HTTP_REFERER="http://[::1"` | 302 para `/users/login` e sessão encerrada; um registro com `getMessage() == "logout via GET"` e `referer_host == "connect.example.com"`; `secret`, `token`, `/path`, `8443`, username e e-mail ausentes de `str(record.__dict__)`; `referer_host is None` nos outros dois GETs, sem 500; o helper | AC-2, FR-003 |
| `test_post_without_csrf_is_rejected` | `client = self.client_class(enforce_csrf_checks=True)`, `client.force_login(self.admin)` e POST com `{"next": "/users/login"}`, sem token | 403; `_auth_user_id` continua na sessão; o helper | AC-3, FR-004 |

**Testes existentes que fecham os critérios**: `temba.orgs` (login, convites e permissões) e `temba.utils.tests.HamlTemplatesCompileTest` (025, com o `nav.haml` alterado), mais a suíte completa (AC-4).

**Comandos**:

```sh
poetry run python manage.py test temba.orgs.tests.LogoutTest --keepdb
poetry run coverage run manage.py test --keepdb --noinput
poetry run python manage.py makemigrations --check --dry-run
./code_check.py
```

**Em staging, com o navegador**:

1. Entrar e clicar em "sign out". Na aba de rede: `POST /users/logout/` com `csrfmiddlewaretoken` e `next=/users/login`, resposta 302 para `/users/login`, e a sessão termina.
2. Abrir `/users/logout/` direto na barra de endereço (GET). A sessão termina, e o log da aplicação mostra `logout via GET` só com `referer_host`.
3. Conferir que nenhum registro `logout via GET` contém e-mail, id de usuário, caminho ou query.

## Rollout and Rollback

Deploy em staging nos três ambientes, com as verificações de navegador acima e o smoke da FR-020 da 024, e depois em produção. Não há migration. O rollback é reverter o PR: o link volta a ser GET, e nada nas specs 025 e 026 depende desta.

## Constitution Alignment

SDD Lite: esta seção é o Constitution Check. O preset `vtex-cx-engineering` não está instalado (TODO SPECKIT_PRESET), por isso esta seção e a Test Strategy foram escritas à mão.

| Princípio | Como esta mudança cumpre |
|-----------|--------------------------|
| I. Version Control and Review | Um PR com review e CI verde, com spec própria (024 FR-001). |
| II. Security and Secrets | Nenhuma dependência nova. O logout passa a usar POST com CSRF, o que fecha o logout forçado por páginas de terceiros. |
| III. Observability | Log estruturado `logout via GET` só com o host do `Referer`, sem dado pessoal (FR-003). |
| IV. Versioned Contracts | A rota de logout é uma tela de sessão, não um contrato público. O comportamento dela fica fixado em [contracts/users-logout.behavior.md](contracts/users-logout.behavior.md). Sem migration. |
| V. Specification Traceability | Abre com `## Origin Without Product Spec`, cita a 024 como contexto, e cada AC aponta para um teste. |
| VI. No Silent Divergence | Não se aplica: não há Product Spec. A FR-008 da 024 está coberta pela FR-001. |
| VII. Commit Messages | `fix: log out via post with csrf` e `docs: note post logout in changelog`. |
| VIII. Changelog Maintenance | Um bullet `fix` marcado como mudança de segurança (FR-005). |
| IX. Never Trust the Client | O `Referer` é tratado como entrada não confiável: só o host é lido, e um valor malformado vira `None`. O redirecionamento continua validado pelo Django (FR-002). O clique exige CSRF (FR-004). |
| X. Fail Gracefully | Um `Referer` malformado não derruba o logout. |
| XI. Bounded Retry | Não se aplica. |
| XII. Scalability and Peak Load | Nenhum estado novo. Peak Load não aplicável, com o motivo. |
| XIII. Diagnosable Errors | Não muda o que vai para o Sentry. |
| XIV. Tests Exercise Flows | Os testes passam pela rota real (POST, GET e POST sem CSRF) e pela página com o nav, e foram escritos antes da implementação. |
| XV. Explicit Over Clever | A rota é declarada explicitamente antes do include, com o motivo num comentário. O log fica na view, não num middleware. |
| XVI. Contained Changes | Uma view, uma rota, uma linha de template e os testes. Nenhum outro template muda. |
| XVII. Explicit, Scoped Authorization | A rota de logout é de sessão do próprio usuário. Nenhuma permissão de recurso muda. |
