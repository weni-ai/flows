# `POST /api/v2/internals/messages/stream` — matriz de comportamento do `flows`

Complementa [openapi.flows.yaml](openapi.flows.yaml) (pin `329a1db`). Status e corpos vêm do contrato. Esta página fixa a **ordem** de avaliação e o **efeito colateral** de cada desfecho. Decisões em [../research.md](../research.md) (R1, R2, R7 a R9).

## Ordem de avaliação

| # | Etapa | Falha → resposta | Efeito |
|---|---|---|---|
| 1 | Bearer module JWT (`RequiredJWTAuthentication`) | `403 {"detail": "..."}` (nunca `401`) | nenhum: sem linha, sem Redis |
| 2 | `ModuleJWTProjectScope`: corpo × claim | `403 {"detail": "You do not have permission to perform this action."}` | nenhum |
| 3 | `Idempotency-Key` válida (1–128 após `strip`) e `project_uuid` do corpo é UUID: consulta ou reserva | `200` replay / `409` / `503` | replay e `409` não escrevem; reserva escreve `inflight` |
| 4 | `MsgStreamSerializer` (campos de topo como hoje + seis campos de `msg`) | `400` (erros de `msg` sob `msg`) | libera a reserva, se houver |
| 5 | `Org` do `project_uuid` | `404 {"error": "Project not found"}` | libera a reserva, se houver |
| 6 | `create_message_db_only` por URN (com chave: dentro de `transaction.atomic()` junto com a conclusão) | `400 {"error": "<mensagem atual>"}` em `ValueError`; `503` em `RedisError`; `500` em outros | libera a reserva; com chave, a transação é desfeita |
| 7 | sucesso | `201 {"ids": [...]}` | com chave: `done` com os ids, validade de 24h |

## Desfechos

| `outcome` (FR-036) | `reason` | Status | Corpo | Linhas criadas | Registro da chave |
|---|---|---|---|---|---|
| `created` | — | `201` | `{"ids": [...]}` | 1 por URN | `done` (se houver chave) |
| `replayed` | — | `200` | `{"ids": [...]}` originais | 0 | inalterado |
| `conflict` | `idempotency_conflict` | `409` | `{"code": "idempotency_conflict", "error": "Idempotency-Key reused with different body"}` | 0 | inalterado |
| `conflict` | `idempotency_in_progress` | `409` | `{"code": "idempotency_in_progress", "error": "Request with this Idempotency-Key is already being processed"}` | 0 | inalterado |
| `rejected_validation` | — | `400` | erros DRF (os de `msg` sob `msg`) ou `{"error": ...}` do serviço | 0 | liberado |
| `rejected_auth` | — | `403` | `{"detail": ...}` | 0 | nenhum |
| `rejected_tenant` | — | `403` | `{"detail": ...}` | 0 | nenhum |
| `project_not_found` | — | `404` | `{"error": "Project not found"}` | 0 | liberado |
| `error` | `dedupe_unavailable` | `503` | `{"error": "Service temporarily unavailable"}` | 0 | liberação tentada |
| `error` | `unexpected` | `500` | resposta padrão de erro do servidor, sem detalhe interno | 0 com chave; sem chave, como hoje | liberação tentada |

Os valores de `outcome` são exatamente os do FR-036. O campo `reason` só distingue os casos de FR-023 e FR-026 e também é um identificador opaco.

## Sem `Idempotency-Key`, ou com chave inválida

As etapas 3 e a transação da etapa 6 não acontecem. O comportamento é o de hoje: as linhas são criadas uma a uma, sem `atomic` (FR-016, FR-018, FR-025).

## Headers

| Header | Regra |
|---|---|
| `Authorization: Bearer <module JWT>` | obrigatório; qualquer falha devolve `403` |
| `Idempotency-Key` | opcional; `strip()`; vazio ou com mais de 128 caracteres vale como ausente, sem `400` |
| `X-Correlation-ID` | opcional; de 1 a 128 caracteres, usado como veio e de forma opaca nos logs e nas tags do Sentry; fora disso é ignorado, sem rejeitar |
