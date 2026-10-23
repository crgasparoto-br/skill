# Issue #112 — registro verificável da revisão de evidências

> **Estado: EM REVISÃO, não certificado.** Este documento não substitui `reviewed-closure.json`, as matrizes formais ou auditoria independente. Evidências de `pytest` são fatos de execução e não prova automática de equivalência semântica.

## Âncoras verificadas

| Fonte | Âncora | Papel e limite |
|---|---|---|
| Issue canônica | [#112](https://github.com/crgasparoto-br/skill/issues/112), SHA-256 do corpo `9a1bc299fc5514ffebc31dbc43a4e9f83963d4a093c786f686c7fa5e56007b1a` | Especificação, 52 obrigações extraídas no run abaixo |
| Início da implementação | `8cf01341030de7762b98b73c6a19efde5ad71461` | Ancestral de `a5c71a5f1ba3cf6e1ad05b2284c12c35f91a8446`, primeiro commit da PR |
| Snapshot de coleta | [artifact 12497159222](https://github.com/crgasparoto-br/skill/actions/runs/39944254214/artifacts/12497159222), material `c047217e0bbb334b62221c49d6e24fcca27edc47` | `requirement-closure.json`, 52 `candidate_key`, 2.305 IDs JUnit, log e digests; é **histórico** e deve ser regenerado no HEAD final |
| Testes técnicos | [Validate skills 39944249033](https://github.com/crgasparoto-br/skill/actions/runs/39944249033) | 2.305 testes + 11 subtestes, sem classificação de cobertura por requisito |
| Rejeição prévia | [Comentário 6350885227](https://github.com/crgasparoto-br/skill/pull/113#issuecomment-6350885227) e [6352025888](https://github.com/crgasparoto-br/skill/pull/113#issuecomment-6352025888) | Relatam A-112-01..05; são **histórico**, não relatório imutável de auditoria independente nem prova de encerramento |
| Certificação bloqueada | [run 39944254214](https://github.com/crgasparoto-br/skill/actions/runs/39944254214) | Coleta `success`, certificação `failure` por ausência de fechamento semântico |

## Revisão do escopo: rastreabilidade preliminar

| Grupos de obrigações | Superfície canônica a confrontar | Controle concreto já localizado | O que ainda precisa de refutação |
|---|---|---|---|
| OBL-001–005, OBL-026–029 | `AGENTS.md`, `entregar-issue/references/implementation-workflow.md` e contratos do catálogo | `entregar-issue/tests/test_codebase_grounding.py::test_gate_is_registered_and_loaded_progressively` | Auditar coerência entre todas as cópias, sem usar somente texto do PR |
| OBL-006, OBL-036, OBL-051 | `revisar-issue/references/specification-standard.md` | Critério documentado de inventário com `UNKNOWN` quando árvore indisponível | Evidência de uma revisão realmente executada sobre reuso dos casos |
| OBL-007, OBL-012–015, OBL-019, OBL-030, OBL-033, OBL-037 | `entregar-issue/references/codebase-grounding-gate.md`, `entregar-issue/scripts/validate_codebase_grounding.py` | `test_missing_test_decision_blocks_even_for_test_only_diff`; `test_distinct_oracle_is_not_rejected_by_nominal_similarity` | Testar oráculo e equivalência por cenário; inventário real de fixtures/parametrizações |
| OBL-016–018, OBL-022, OBL-031–032, OBL-039, OBL-045–046 | `validate_codebase_grounding.py`, política de exclusão da Skill e autorização | `test_deleted_test_requires_preserved_controls`; `test_distinct_oracle_is_not_rejected_by_nominal_similarity` | Demonstrar controle antes/depois de cada exclusão real, caso exista; não tratar descoberta estática como completude |
| OBL-008, OBL-040, OBL-048 | `auditar-issue/references/audit-checklist.md`, `auditar-issue/references/codebase-grounding-audit.md` | Regras normativas de rederivação independente e controles negativos | Auditor read-only distinto deve refutar a implementação; não usar aprovação do implementador |
| OBL-009, OBL-021, OBL-041, OBL-052 | `higienizar-repositorio/references/test-lifecycle-hygiene.md` | Procedimento de diagnóstico sob demanda, sem remoção automática | Confirmar que não existe runner invisível nem contrato histórico nos candidatos à obsolescência |
| OBL-010, OBL-028, OBL-034, OBL-042 | `corrigir-ci/SKILL.md`; `entregar-issue/scripts/require_actions_handoff_certificate.py` | `test_missing_semantic_closure_is_blocked_even_when_technical_facts_exist` | CI verde é separada de certificação, e falha da suíte nunca pode ser convertida em evidência positiva |
| OBL-011, OBL-025, OBL-049 | `entregar-issue/schemas/codebase-grounding.schema.json`; `planning_contract_runtime.py`; manifestos compartilhados | `test_legacy_v1_is_explicitly_rejected_for_test_diff`; `test_historical_v2_plan_schema_and_runtime_compatible` | Verificar migrações históricas e todas as cópias pelo gate oficial |
| OBL-020, OBL-023–024, OBL-035, OBL-038, OBL-043, OBL-047 | `plan_execution.py`, detecção de testes do runner, `validate_codebase_grounding.py` | `test_dynamic_runner_unavailable_is_unknown_not_ready`; `test_test_only_cypress_outside_conventional_folder_triggers_gate`; `test_planner_classifies_test_only_and_preserves_gate_contract` | Executar mutações negativas e cobertura de `pytest.ini`, Go, Cypress, `.feature`, `.robot`; nome de arquivo não é prova semântica |
| OBL-027 | Branch `feat/112-test-lifecycle-governance` → `develop` | SHA da PR e CI vinculados ao HEAD material | Revalidar base/HEAD antes de emitir qualquer certificado |
| OBL-044 | Gate `certified-handoff` e auditoria independente | Coleta e validação técnica disponíveis | **Não pode ser marcado como cumprido nesta etapa**: certificado e auditoria ainda não emitidos |
| OBL-050 | Suítes existentes da entrega e auditoria | Casos negativos e regressão presentes na suíte exact-SHA | Confirmar que novos casos não duplicaram oráculos já cobertos |

## Pendências impeditivas para a certificação

1. Revisar cada uma das 52 `candidate_key` imutáveis extraídas do mesmo corpo da Issue #112. Marcar `covered` somente após inspeção de cenário e oráculo; registrar racional por requisito e diferir explicitamente pós-handoff quando aplicável.
2. Preencher `test_bindings` com IDs **inteiros e exatos** do JUnit `passed` atual, discriminando controles positivos, negativos e regressões. Rótulos na tabela acima são referências de navegação, não os IDs finais do JUnit.
3. Gerar `codebase-grounding.json` schema v2 para cada arquivo de teste modificado, com `subject_sha`, `base_sha`, busca de candidatos, decisão e prova de execução revalidada. Recomputar `CODE-GROWTH-001` pelo Git no HEAD final.
4. Gerar matriz crítica de ataques, saturação de risco, controles herdados e reconciliação de documentação em fontes canônicas; executar validadores oficiais sobre os JSONs gerados.
5. Recuperar relatório original de rejeição independente e histórico imutável de fechamentos A-112-01..05, produzir `audit-remediation`, `learning-closure` e `audit-escape-closure`. Comentário da PR não equivale a snapshot independente.
6. Atualizar hashes SHA-256 de todos os arquivos do dossiê, declarar `review_state=approved` somente após evidências completas e executar o gate de certificação exact-SHA seguido de auditoria independente.

**Regra de segurança:** manter `manifest.review_state=incomplete` enquanto qualquer item estiver sem prova. Não criar `certification-inputs.json` antecipadamente e não liberar `workflow_run` privilegiado por sucesso apenas da coleta.
