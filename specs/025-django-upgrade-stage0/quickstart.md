# Quickstart: validar os testes de proteção da etapa 0

**Feature**: `025-django-upgrade-stage0` | **Plan**: [plan.md](plan.md)

Guia de validação do PR. Não contém implementação. Desenho: [plan.md](plan.md). Decisões: [research.md](research.md).

## Pré-requisitos

- Python 3.11, Poetry, PostgreSQL/PostGIS e Redis locais, como no `.github/workflows/ci.yml`.
- `poetry install`. Nenhuma dependência nova.

## Gates

```sh
poetry run coverage run manage.py test --keepdb --noinput
poetry run python manage.py makemigrations --check --dry-run
./code_check.py
```

Esperado:

- os quatro grupos do CI verdes;
- `makemigrations --check` sem saída;
- `./code_check.py` termina com "Code looks good";
- nenhum `# pragma: no cover` novo em `temba/` (`git diff main -- temba/ | rg '^\+.*pragma: no cover'` vazio);
- nenhum `skip` novo em `temba/` (`git diff main -- temba/ | rg '^\+.*(skip|expectedFailure)'` vazio).

Os dois `rg` olham só `temba/`. O diff dos documentos de spec cita essas palavras e não entra na conta.

## Os testes novos

```sh
poetry run python manage.py test temba.utils.tests.TimezoneParityTest temba.utils.tests.HamlTemplatesCompileTest --keepdb
```

Esperado:

- Os dois passam no código atual. A descrição do PR registra o commit base e `pytz.__version__` (2025.2).
- `KNOWN_BROKEN_TEMPLATES` está vazio (os 345 `.haml` compilam).
- Nenhuma linha do corpo de `TimezoneParityTest` contém `pytz`, `zoneinfo`, `.zone`, `.key`, `.dst(`, `isinstance(` ou `repr(`:

```sh
awk '/^class TimezoneParityTest\(/,/^class /' temba/utils/tests.py | rg -n '\.zone\b|\.key\b|\.dst\(|\bpytz\b|\bzoneinfo\b|\bisinstance\(|\brepr\('
```

Esperado: vazio. A classe seguinte é `HamlTemplatesCompileTest`, então o intervalo do `awk` para nela. O import de `pytz` que já existe no topo do arquivo fica de fora.

## Guarda de diff (FR-005)

A guarda junta o que já difere de `main` com o que ainda não está rastreado. `git diff main` sozinho não lista arquivo novo.

```sh
{
  git diff --name-only main
  git ls-files --others --exclude-standard
} | sort -u | rg -v '^(specs/(024-django-5-2-upgrade|025-django-upgrade-stage0)/|\.specify/feature\.json|\.cursor/rules/specify-rules\.mdc)$'
```

Esperado: só `temba/utils/tests.py`.

Antes de rodar, a árvore não pode ter arquivo das specs `026-django-upgrade-stage0-removed-apis`, `027-django-upgrade-stage0-post-logout` ou `028-django-upgrade-stage0-remove-csv-imports`. Um arquivo untracked dessas specs aparece na lista e a guarda falha. Eles entram nos PRs delas.

## Prova de que os testes acusam regressão

Manual, sem commitar:

- passar `is_dst=True` ao `tz.localize(value)` de `ContactImport._parse_value` faz o caso ambíguo de `America/New_York` falhar;
- acrescentar uma tag inexistente (`{% nao_existe %}`) num `.haml` faz o `HamlTemplatesCompileTest` falhar com o nome do arquivo.

Reverter as duas mudanças. Elas não ficam no diff. O que restar no status é só o que a guarda de diff acima permite.
