# Relatório: dias zerados em `GET /api/v2/projects/internal/message_count`

Investigação em produção em 26/11/2026, com Loki (`namespace="flows"`) e PostgreSQL do Flows pelo Grafana.

## Resumo

A task `update_unique_contact_counts` não teve culpa em 20, 21 e 22/11. Ela rodou todas as noites, processou as ~24,5 mil orgs ativas sem nenhuma falha e gravou o que o Elasticsearch devolveu. O problema de 21 e 22/11 foi no Elasticsearch. O de 14/11 foi do lado do Flows: a task foi interrompida no meio. O de 20/11 não é erro.

| Dia | Valor no CX Internal Admin | Causa |
|---|---|---|
| 14/11 | `count: 1` | O pod de celery foi derrubado com a task rodando |
| 20/11 | ~39 mil | Queda real de tráfego no feriado da Consciência Negra |
| 21/11 e 22/11 | `count: 0` | O alias `contacts` do ES apontava para um índice incompleto |

## Como a task conta

A task roda às 08:00 UTC (`crontab(hour=8, minute=0)`, com `TIME_ZONE = "GMT"`). Para cada org ativa, ela faz um `_count` no alias `contacts` do ES, filtrando contatos com `last_seen_on` dentro do dia anterior, e grava o resultado em `orgs_uniquecontactcount`.

O `last_seen_on` guarda só a **última** interação do contato. A contagem só faz sentido se rodar logo depois do fim do dia, e com o índice em dia.

## 21/11 e 22/11: alias `contacts` trocado para um índice incompleto

Por volta das 03:07 UTC de 22/11, o indexador (`indexer-6f5bf9bbc8-tp9b7`) passou a escrever no índice `contacts_2026_11_13_1` em vez de `contacts_2024_09_09`. Esse índice foi criado em 13/11 e estava incompleto. O contato mais recente nele era de abril de 2022.

A `check_elasticsearch_lag` do Flows, que roda a cada 5 minutos e lê o alias `contacts`, começou a logar drift às 03:10:

```
2026-11-22T03:10:52  drift between ElasticSearch and DB. Newest DB(... modified_on: 2026-11-22 03:10:51) Newest ES(id: 43282047, modified_on: 2022-04-27 18:15:53)
2026-11-22T04:05:56  ... Newest ES(id: 51840340, modified_on: 2022-09-21 11:18:42)
2026-11-23T03:50:55  ... Newest ES(id: 34289366, modified_on: 2025-05-30 08:14:25)
2026-11-23T12:50:53  ... Newest ES(id: 57570918, modified_on: 2025-07-18 15:08:17)
2026-11-23T12:55:53  ... Newest ES(id: 178942259, modified_on: 2026-11-22 03:07:59)
2026-11-23T13:05:58  ... Newest ES(id: 178995870, modified_on: 2026-11-23 12:34:28)
```

O "Newest ES" foi subindo em ordem crescente de `modified_on` por 34 horas: era o indexador tentando alcançar o presente a partir de 2022. Ao mesmo tempo, o indexador logou milhares de `error deleting contact`, porque os contatos não existiam no índice novo.

Em 23/11 às 12:55, o "Newest ES" pulou para 22/11 03:07:59, o instante em que o problema começou. O alias voltou para `contacts_2024_09_09`, que tinha os dados até a troca. Entre 13:00 e 13:30, um novo deploy do indexador (`indexer-858dfbf46c-*`) voltou a escrever em `contacts_2024_09_09`, e o drift sumiu.

As duas execuções afetadas caíram dentro dessa janela:

- 22/11 08:00 (referente a 21/11): o índice só tinha contatos modificados até 2022. Nenhum tinha `last_seen_on` em 21/11.
- 23/11 08:00 (referente a 22/11): o índice estava em 2025. Nenhum contato tinha `last_seen_on` em 22/11.

Nos logs, essas duas execuções terminaram com `completed successfully`, sem nenhuma org com falha. O ES respondeu `200` a todas as consultas.

O indexador do Flows não fez a troca do alias: ele só passou a usar o índice novo depois dela. Durante essa janela, a busca de contatos do Flows (grupos dinâmicos, filtros, envios por query) também leu o índice incompleto.

**A confirmar com quem administra o ES:** quem trocou o alias às 03:07 UTC de 22/11 e por que `contacts_2026_11_13_1` estava incompleto.

```
GET _cat/aliases/contacts?v
GET _cat/indices/contacts*?v&s=creation.date
```

Também vale olhar o activity log do Elastic Cloud (`weni-prod.es.sa-east-1.aws.found.io`) nesse horário.

## 14/11: pod derrubado no meio da execução

A execução de 15/11 08:00 (referente a 14/11) começou no pod `celery-568cbbc886-jpr4r`. Às 08:01:00 o pod recebeu `Warm shutdown`, e o `celery-568cbbc886-6tldq` subiu no lugar dele. Até 08:02 a task fez cerca de 4 mil das ~24,5 mil consultas e nunca logou o término.

Só essas primeiras orgs ganharam linha para 14/11, e somaram 1. As outras ~20 mil ficaram sem linha. Como a task é agendada pelo beat e não é retomada, ninguém refez o dia. O "succeeded" que aparece para esse dia não tem respaldo nos logs.

## 20/11: queda real de tráfego

A `channels_channelcount` mostra a mesma queda:

| Dia | Mensagens recebidas |
|---|---|
| 17/11 (ter) | 330.463 |
| 18/11 (qua) | 326.516 |
| 19/11 (qui) | 335.652 |
| 20/11 (sex, feriado) | 172.225 |
| 21/11 (sáb) | 161.344 |
| 24/11 (ter) | 397.330 |

O indexador estava em dia, e a execução de 21/11 08:00 rodou antes do incidente. O valor de ~39 mil é real.

## Dá para reprocessar?

Não com a task atual. Rodar hoje `update_unique_contact_counts(target_date="2026-11-21")` contaria só quem falou em 21/11 e não voltou desde então, e isso subestima bastante.

Criei o comando `backfill_unique_contact_counts`. Ele calcula, para cada org ativa, os contatos distintos com mensagem recebida (`msgs_msg`, `direction = 'I'`) no dia UTC. Esse dado não muda depois. Sem `--commit`, o comando só imprime os totais:

```
python manage.py backfill_unique_contact_counts 2026-11-19
python manage.py backfill_unique_contact_counts 2026-11-14 2026-11-21 2026-11-22
python manage.py backfill_unique_contact_counts 2026-11-14 2026-11-21 2026-11-22 --commit
```

1. Rodar primeiro para um dia normal (19/11) e comparar o "recalculated total" com o "stored total", que veio do ES. A definição não é idêntica, porque `last_seen_on` também pode mudar por eventos de canal, então os números não vão bater exatamente.
2. Se a diferença for aceitável, rodar os três dias com `--commit`. O comando atualiza as linhas existentes e cria as que faltam, inclusive as ~20 mil orgs sem linha em 14/11.

A consulta lê a faixa de um dia de `msgs_msg` pelo índice de `created_on`. O banco que o Grafana acessa é o primário de produção, sem `statement_timeout`. Melhor rodar fora do horário de pico.

## Horário da consulta do CX Internal Admin

A task começa às 08:00 UTC e termina entre 08:05 e 08:10 (confirmado nos logs de 10 a 26/11). Buscando às 07:00 UTC, "ontem" ainda não existe. O endpoint só devolve dias que têm linha, então o zero de "ontem" vem do lado do admin. Buscar a partir das 09:00 UTC resolve.

## O que ainda vale mudar na task

- **Checar o ES antes de contar.** Reaproveitar a lógica da `check_elasticsearch_lag`: se o ES estiver mais de 5 minutos atrás do banco, a task falha e tenta de novo, em vez de gravar zeros.
- **Parar de depender de `last_seen_on`.** Mesmo com o ES saudável, quem fala no dia D e volta entre 00:00 e 08:00 UTC de D+1 já não entra na conta de D. Contar a partir de `msgs_msg`, como o comando de recálculo faz, resolve isso e permite reprocessar.
- **Resistir à queda do pod.** A task não retoma de onde parou e não avisa quando não termina. Também vale corrigir a docstring, que fala em "5am UTC" quando o agendamento é às 08:00.
