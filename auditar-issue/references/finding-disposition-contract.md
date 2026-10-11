# Classificação de achados e contrato de retorno

Em toda auditoria que produza findings, atribuir a cada item ID estável, requisito/critério vinculado, localização, evidência própria, severidade, aplicabilidade e uma destas disposições: `blocking`, `actionable-recommendation`, `optional-recommendation`, `out-of-scope` ou `invalid-finding`. Não classificar sugestão de fase futura como blocker sem exigência no contrato atual. `out-of-scope` e `invalid-finding` exigem justificativa verificável; quando houver incerteza material, manter o achado explícito e não inventar decisão.

Para reauditoria, comparar por ID **todos** os itens acionáveis anteriores com HEAD e evidência novos, informar `resolved`, `still-open`, `regressed` ou `not-applicable`, sem descartar recomendações acionáveis. Cada `resolved` exige comportamento/controle comprovado no novo SHA, não apenas commit, teste adicionado, checklist ou afirmação do implementador. Se correção for parcial, registrar `still-open`; a aprovação final continua proibida diante de blockers.

Entregar o ledger de findings como contrato consumível por `entregar-issue` sem executar escrita durante auditoria. Preservar validade independente: auditoria no mesmo contexto da implementação é somente pré-auditoria, nunca aprovação independente.
