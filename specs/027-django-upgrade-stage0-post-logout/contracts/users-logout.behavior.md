# Contrato de comportamento: `/users/logout/`

**Feature**: `027-django-upgrade-stage0-post-logout` | **Spec**: [../spec.md](../spec.md)

A rota é uma tela de sessão do próprio usuário, não um contrato público do Principle IV. Este documento fixa o comportamento que os testes de `temba.orgs.tests.LogoutTest` verificam e que a etapa 3 da 024 vai restringir (só POST).

## Rota

| Item | Valor |
|---|---|
| Caminho | `/users/logout/` |
| Nome | `users.user_logout` (o mesmo de hoje) |
| Declaração | `temba/urls.py`, imediatamente antes de `path("users/", include("smartmin.users.urls"))` |
| View | `temba.orgs.views.LogoutView`, subclasse de `django.contrib.auth.views.LogoutView` |
| Sobrescrito | só `dispatch` (log do GET). `next_page`, `redirect_field_name` e `get_next_page` herdados (FR-002). |

## Redirecionamento (igual para GET e POST)

O campo é `next`, lido do POST e depois da query string. O nome `go`, que o smartmin passa, nunca foi usado (ver D-2 na spec).

| `next` na requisição | Destino (`Location`) |
|---|---|
| ausente | `/` (`LOGOUT_REDIRECT_URL`) |
| relativo ou do próprio host (por exemplo `/users/login`) | o próprio `next` |
| outro host ou esquema não permitido (por exemplo `https://evil.example/`) | `/users/logout/` (o caminho da própria requisição) |

## Matriz de requisição

| Método | CSRF | Sessão depois | Status | Log `logout via GET` |
|---|---|---|---|---|
| POST | válido | encerrada | 302 | não |
| POST | ausente ou inválido | mantida | 403 | não |
| GET | não se aplica | encerrada | 302 | sim, com `referer_host` |

## Interface

- `templates/includes/nav.haml:247`: `%a.posterize(href="{% url 'users.user_logout' %}?next=/users/login")`.
- O handler `.posterize` de `templates/frame.haml` (linhas 446-457 e 636-645) envia um POST para o caminho do `href`, com os parâmetros da query como campos ocultos e o `{% csrf_token %}` do form `#posterizer` (linhas 557-559). O resultado é um POST para `/users/logout/` com `csrfmiddlewaretoken` e `next=/users/login`.
- Fora do escopo: o link comentado em `temba/orgs/views.py:3197-3208` e o ramo `orgs.org_service` do nav, que já usa `posterize`.

## Log

Ver a seção "Registro `logout via GET`" da [spec](../spec.md). Exemplo de requisição e registro:

- `GET /users/logout/?next=/users/login` com `Referer: https://user:secret@Connect.Example.com:8443/path?token=abc`
- registro: mensagem `logout via GET`, `referer_host="connect.example.com"`, sem nenhum outro campo de `extra`.
