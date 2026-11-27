# Contrato de comportamento: remoção de `/imports/`

**Feature**: `028-django-upgrade-stage0-remove-csv-imports` | **Spec**: [../spec.md](../spec.md)

`/imports/` é uma tela interna do smartmin, sem link no Flows e sem contrato público (Principle IV). Este documento fixa o que `temba.orgs.tests.CsvImportsRemovedTest` verifica.

## Rotas

| Requisição | Hoje | Depois desta spec |
|---|---|---|
| `GET /imports/importtask/` (`csv_imports.importtask_list`) | tela do smartmin para quem tem a permissão | 404 |
| `GET /imports/importtask/read/1/` (`csv_imports.importtask_read`) | idem | 404 |
| `GET /imports/` | 404 (o `ImportTaskCRUDL` só tem `read` e `list` e não declara a raiz) | 404 |
| `reverse("csv_imports.importtask_list")` | `/imports/importtask/` | `NoReverseMatch` |

O 404 vale para usuário anônimo, usuário comum e superusuário, porque a rota deixa de existir antes de qualquer checagem de permissão.

## Configuração

| Item | Depois desta spec |
|---|---|
| `INSTALLED_APPS` | sem `smartmin.csv_imports` |
| `GROUP_PERMISSIONS["Administrators"]` e `["Editors"]` | sem `csv_imports.importtask.*`; demais entradas na mesma ordem |
| `temba/urls.py` | sem a linha de `imports/` |
| Migrations | nenhuma; `makemigrations --check` limpo |

## Permissões após o `post_migrate`

Ver "Permissões de grupo" na [spec](../spec.md). O teste reproduz o banco de produção: cria um `ContentType` `csv_imports.importtask` com uma permissão, atribui essa permissão a `Administrators`, roda `check_all_group_permissions` e verifica que:

- a permissão sai do grupo;
- as demais permissões de todos os grupos continuam iguais;
- nenhum grupo recebe permissão de `smartmin.importtask` (D-2 da spec).
