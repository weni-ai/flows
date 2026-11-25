# Specification Quality Checklist: componentes de streaming do Shopping Assistant em `POST /api/v2/internals/messages/stream` (fatia Flows)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-23
**Last updated**: 2026-11-24
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- **Resolução (AD-004, 2026-11-23)**: o autor do Architecture doc resolveu CI-01, CI-02, L-01, L-02 e O-01 nas regras 1 a 4 do AD-004 (Amendment Log, segunda linha):
  - uma chave não declarada em `list_message`, `list_items[]`, `cta_message` e `msg.header` recebe `400`;
  - os campos de topo não mudam;
  - o `409` traz `code` `idempotency_conflict` ou `idempotency_in_progress`;
  - uma chave inválida é tratada como ausente;
  - toda falha de JWT ou de escopo devolve `403`, sem `401`.

  O FR-010 tem critério de aceitação nos cenários 15 a 19 da US2. Não há pendência de contrato, e Divergences continua `none`.
- **Pin**: o commit `fe00c1c` deixou de ser o texto vigente, porque é a versão que gerou as cinco inconsistências. Architecture doc e contratos estão fixados no commit da emenda, `329a1db8c1f3f62208b052457e0e3bc9654ce102`, que tem o mesmo conteúdo do `task-spec.md` local. A tag `019-sa-components-streaming/arch-v1` já existe no remoto e aponta para `148d5ee`, com o mesmo conteúdo. Mas o documento tagueado ainda diz `Status: Draft`, com a aprovação do tech lead do `flows` pendente. É preciso re-fixar na tag quando a aprovação constar nela.
- **Detalhes de implementação**: esta é uma engineering spec de um contrato HTTP interno. Caminho do endpoint, nomes de campos, códigos HTTP, `Msg.metadata` e `create_message_db_only` são o próprio contrato ou o escopo pedido, não escolhas de design. As referências a arquivos e classes estão nas seções Estado atual e Test Strategy, como contexto para o `/speckit-plan`. Os FRs descrevem comportamento.
- **Público**: o leitor é engenharia (tech lead do `flows` e do `nexus-ai`), como em toda engineering spec do Principle V. O "o quê" de produto fica na Product Spec pinada.
- Iteração de validação: 2. Todos os itens passam.
