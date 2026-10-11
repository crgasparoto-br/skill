# Classificação de achados e contrato de retorno

Em toda auditoria que produza findings, atribuir a cada item ID estável, requisito/critério vinculado, localização, evidência própria, severidade, aplicabilidade e uma destas disposições: `blocking`, `actionable-recommendation`, `optional-recommendation`, `out-of-scope` ou `invalid-finding`. Não classificar sugestão de fase futura como blocker sem exigência no contrato atual. `out-of-scope` e `invalid-finding` exigem justificativa verificável; quando houver incerteza material, manter o achado explícito e não inventar decisão.

Para reauditoria, comparar por ID **todos** os itens acionáveis anteriores com HEAD e evidência novos, informar `resolved`, `still-open`, `regressed` ou `not-applicable`, sem descartar recomendações acionáveis. Cada `resolved` exige comportamento/controle comprovado no novo SHA, não apenas commit, teste adicionado, checklist ou afirmação do implementador. Se correção for parcial, registrar `still-open`; a aprovação final continua proibida diante de blockers.

Entregar o ledger de findings como contrato consumível por `entregar-issue` sem executar escrita durante auditoria. Preservar validade independente: auditoria no mesmo contexto da implementação é somente pré-auditoria, nunca aprovação independente.

## Manifesto verificável para a entrega

Para cada rodada, emitir o conjunto integral e imutável de IDs por `repository`, `pr_number` e `audit_round`. O consumidor deve recuperar o manifesto diretamente da revisão original autenticada, e não de uma lista fornecida pela skill implementadora. Atestar separadamente cada decisão de exclusão e cada resolução vinculada ao HEAD auditado. Só o processo verificador independente, com consulta autenticada aos comentários/reviews/checks e verificação de identidade, pode emitir uma atestação consumível pelo gate `entregar-issue`. Não aceitar um JSON entregue pelo implementador como prova de independência.
