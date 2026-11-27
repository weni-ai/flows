# Data Model: etapa 0 do upgrade do Django, parte 1 — testes de proteção

**Feature**: `025-django-upgrade-stage0` | **Date**: 2026-11-27 | **Plan**: [plan.md](plan.md)

Sem migration. Nenhuma tabela, coluna ou índice novo. O PR só acrescenta testes, que escrevem apenas no banco de teste.

## 1. Tabelas usadas pelos testes

| Tabela | Uso |
|---|---|
| `orgs_org` (`timezone` texto, `date_format`, `proj_uuid`) | o `TimezoneParityTest` grava o fuso da org de teste, cria orgs pela view de `Grant` e usa `proj_uuid` em `validate_layers` |
| `schedules_schedule`, `msgs_msg`, `msgs_exportmessagestask`, `contacts_contact` | criadas e apagadas pelos casos do `TimezoneParityTest` |
| `flows_flow` | o caso de `utcoffset` carrega o flow `color_v13` pela view `flows.flow_results` |

Nenhuma tabela de produção é tocada.

## 2. `Org.timezone` como entrada do `TimezoneParityTest`

| Aspecto | Regra |
|---|---|
| Armazenamento | Texto com o nome IANA (`TimeZoneField`, `max_length=63`). |
| Leitura | `from_db_value` devolve `pytz` (etapas 0 e 1) ou `ZoneInfo` (etapa 2), conforme `USE_DEPRECATED_PYTZ`. |
| Escrita no teste | `Org.objects.filter(id=...).update(timezone=<nome>)` seguido de `refresh_from_db(fields=["timezone"])`. O teste nunca constrói o objeto de fuso. |
| Valores usados | `UTC`, `Africa/Kigali`, `America/New_York`, `Europe/Dublin` e `America/Sao_Paulo`. |
| Invariante da paridade | `str(org.timezone) == <nome>` e o texto gravado no banco é `<nome>`, nas três etapas. |

## 3. Casos de paridade como dados

Cada caso do `TimezoneParityTest` é uma tupla `(entrada, esperado)` declarada como constante nomeada da classe (Principle XV). A matriz completa está no [plan.md](plan.md) ("`TimezoneParityTest`").

| Elemento | Tipo | Regra |
|---|---|---|
| fuso | `str` | Um dos cinco nomes da seção 2. |
| data de referência | `date` | Data de transição ou de controle do fuso. |
| instante de entrada | `datetime` com `datetime.timezone.utc` | Literal. Nunca derivado de hora local dentro do teste. |
| hora local ingênua | `datetime` sem `tzinfo` | Só para `ContactImport._parse_value`, que é a função que aplica o fuso. |
| esperado | `str`, `date`, `tuple`, `list` ou `int` | Literal capturado do código atual ([research.md](research.md) R3). Nunca um objeto de fuso. |
