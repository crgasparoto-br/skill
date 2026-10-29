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


## Estado pos-merge e cadeia de recuperacao (23/10/2026)

- A [PR #113](https://github.com/crgasparoto-br/skill/pull/113) foi mergeada em `develop` no commit `418e5fcc312d90911fd8ec66e2e036b7bebdee43`; a [release #117](https://github.com/crgasparoto-br/skill/pull/117) foi mergeada em `main`. Nenhuma dessas operacoes converte o dossie pendente em aprovado.
- No [workflow #39961079004](https://github.com/crgasparoto-br/skill/actions/runs/39961079004) da PR #113, o material `5e06cc1f115057633b1f82655134ea79ccdabc58` executou **2.309** casos JUnit aprovados; a coleta tecnica passou, mas a certificacao falhou com `certification-inputs.json absent: semantic closures have not been supplied`. O artifact `12505226511` mantem os fatos historicos de teste, nao o fechamento dos 52 oraculos.
- A [PR corretiva #118](https://github.com/crgasparoto-br/skill/pull/118) nasce da `develop` integrada e tem o dossie reancorado ao numero de PR/branch atuais. A identidade do SHA material e os JUnit IDs **devem ser coletados novamente** no HEAD de #118 para certificar, pois a evidencia de #113 e historica.
- A auditoria de protecao de branches verificou `required_status_checks=[]` nos rulesets de `develop` e `main`; a [issue #119](https://github.com/crgasparoto-br/skill/issues/119) trata a configuracao administrativa dos contexts obrigatorios. Nao afirmar que um gate vermelho impede merge enquanto a verificacao de rulesets nao comprovar a protecao.
- **Nenhuma obrigacao foi promovida a `covered` nesta atualizacao.** Permanecem pendentes a revisao real de 52 cenarios/oraculos, vinculos positivos/negativos/regressao aos JUnit IDs do novo SHA, relatorios criticos e proveniencia das rejeicoes anteriores. O manifesto permanece `review_state=incomplete`, e o produtor deve continuar recusando certificacao.



## Revisão semântica incremental, com oráculos (25/10/2026)

- No material de partida `1209d8bac815a23772a160d9b4cf950dba944622`, `OBL-038` estava provisoriamente coberta, e outras 51 permaneciam pendentes. A revisão desta mudança inspecionou especificamente 21 obrigações de comportamento determinístico; seus identificadores `OBL`, fontes e testes de refutação constam nos registros individuais de `reviewed-closure.json` e nos `test_bindings` do manifesto.
- Revisadas neste lote: OBL-009, OBL-016, OBL-017, OBL-018, OBL-020, OBL-021, OBL-023, OBL-025, OBL-026, OBL-027, OBL-028, OBL-030, OBL-032, OBL-033, OBL-034, OBL-035, OBL-037, OBL-042, OBL-046, OBL-047, OBL-049. Cada entrada tem controles positivo/negativo/regressão distintos, com ID JUnit formal já existente na suíte; o produtor voltará a conferir a execução no novo SHA. A revisão preliminar **não** afirma que nomes de testes sozinhos provam equivalência de oráculos.
- **Progresso do dossiê: 22/52 provisoriamente cobertas; 30/52 pendentes.** `review_state=incomplete`, sem hashes certificados; `pass_c`, matrizes críticas, riscos, controles herdados e auditoria externa seguem pendentes. A certificação deve permanecer bloqueada. Uma possível regressão de CI será corrigida no SHA material, sem enfraquecer gates.
- Pendências que não podem ser declaradas implementadas por contagem de testes incluem execução real de revisão de issue, revisão read-only independente, comprovação completa de oráculos/consumidores e certificação/auditoria após handoff. Não há aprovação independente ou autorização de merge.


## Segundo lote verificado de decisões provisórias — 25/10/2026

- No material de partida `702ecb01ebfa16e7d6e9b644305996b32f5925f7`, 22 obrigações eram provisoriamente `covered`; revisadas outras **14**: OBL-001, OBL-005, OBL-011, OBL-013, OBL-014, OBL-019, OBL-024, OBL-031, OBL-039, OBL-041, OBL-043, OBL-048, OBL-051, OBL-052. Os oráculos e fontes de cada caso estão descritos individualmente em `reviewed-closure.json`, e seus vínculos positivo/negativo/regressão constam de `manifest.json`.
- **Estado: 36/52 registros provisoriamente cobertos e 16/52 ainda pendentes.** Continua `review_state=incomplete` e `pass_c=pending`. A obrigação de auditoria independente, certificação terminal e controles críticos não pode ser inferida de testes verdes. Não gerar certificado com este dossiê.
- Os casos ausentes não devem ser promovidos por analogia nem reusando os mesmos testes para oráculos diferentes sem prova. O SHA material atual deve ser revalidado no GitHub Actions; a etapa de comparação dos bindings é estrita e recusa testes não executados, `skipped` e SHA incorreto.


## Terceiro lote de verificacoes de implementacao — 25/10/2026

- Lote de 10 revisoes: OBL-002, OBL-003, OBL-004, OBL-007, OBL-008, OBL-010, OBL-012, OBL-015, OBL-029, OBL-050. Fontes, casos JUnit, classes de refutacao e racional especifico registrados individualmente no `reviewed-closure.json`/manifest.
- **Estado: 46/52 registros provisoriamente `covered`; 6 pendentes: OBL-006, OBL-022, OBL-036, OBL-040, OBL-044 e OBL-045.** Esses cenarios exigem prova adicional: exemplo real de revisao de issue, autorizacao de operacoes destrutivas, refutacao read-only independente, auditoria/certificado apos handoff e consumidor legado para teste obsoleto. Nao completar por inferencia.
- Manifesto continua `incomplete`, `pass_c=pending`, hashes/reports criticos nao emitidos. Nao se declarou certificado, aprovacao independente nem autorizacao de merge.


## Revisão concreta dos testes existentes na Issue #112 (sem invocar Skill) — 25/10/2026

Objetivo desta revisão: produzir a orientação exigida por OBL-006 e OBL-036 na fonte canônica `revisar-issue/references/specification-standard.md`, sem assumir inexistência de cobertura e sem exigir testes novos por similaridade de títulos.

| Risco/cenário da issue | Inventário de casos/fixtures existentes observado | Decisão de revisão | Justificativa observável |
|---|---|---|---|
| Diff apenas de testes | `entregar-issue/tests/test_codebase_grounding.py::test_test_only_feature_diff_triggers_gate_without_global_hygiene`, `test_missing_test_decision_blocks_even_for_test_only_diff` e `test_go_test_only_and_runner_manifests_activate_gate` | `covered-by-existing` | O primeiro exige test_only sem higiene global, o segundo recusa omissão da decisão, o terceiro cobre Go/Cypress; reusar antes de duplicar |
| Criação e modificação de testes | `test_modified_test_coverage_requires_existing_test_candidate`, `test_added_test_cannot_claim_covered_by_existing_with_real_candidate`, `test_distinct_oracle_is_not_rejected_by_nominal_similarity` | `extend-existing` se mesmo oráculo; `new-test-required` para oráculo independente | Fixtures Git reais comprovam BASE e cenário de integração distinto; não deduzir equivalência por nome |
| Descontinuação de contrato/teste legado | `higienizar-repositorio/tests/test_hygiene_profile.py::test_test_lifecycle_hygiene_requires_runner_oracle_review`, `entregar-issue/tests/test_codebase_grounding.py::test_deleted_test_requires_preserved_controls` | `keep` / `needs-investigation` | O teste sintético `tests/removed_contract.py` não é coletado, mas é preservado; falta prova de inexistência de consumidores para excluir. Scanner não apaga |
| Runner customizado/descoberta dinâmica | `test_configured_pytest_filename_is_a_test` parametrizado para pytest.ini, pyproject.toml, tox.ini e setup.cfg; `test_unparseable_pytest_discovery_is_unknown`; `test_head_only_runner_configuration_cannot_prove_existing_test_coverage` | `covered-by-existing` para runners inspecionados; `not-testable/blocked` para plugins dinâmicos não acessíveis | Verificado runner real pytest para configurações disponíveis; plugin externo não observável permanece UNKNOWN, nunca ausência presumida |
| Compatibilidade de formatos | `entregar-issue/tests/test_deterministic_planning.py::test_historical_v2_plan_schema_and_runtime_compatible`; `entregar-issue/tests/test_codebase_grounding.py::test_legacy_v1_is_explicitly_rejected_for_test_diff` | `covered-by-existing` | Compatibilidade histórica aceita onde segura e rejeição explícita para diff de testes v1 insuficiente |
| Auditoria independente posterior | `scripts/verify_independent_pr_audit.py` e checks de GitHub Actions; revisão autenticada atual ausente | `not-testable/blocked` até certificado e auditor externo | O implementador não fabrica review independente nem toma CI técnico verde como aprovação |

A revisão utiliza os paths e oráculos inspecionados nos testes do repositório; casos Go/Cypress fora de runner executável não são declarados integração E2E comprovada. Não existe recomendação para remover ou criar teste redundante. Cada decisão foi vinculada ao controle já existente, preservando a distinção entre inventário, execução e equivalência semântica.

### Encerramento provisório de regras conservadoras

- OBL-022: a operação destrutiva é expressamente proibida sem autorização/aviso; a PR não removeu arquivo de testes. O teste sintético de `git rm` serve somente para testar a negativa de perda de cobertura.
- OBL-045: o corpus de higiene exercita o sinal `removed_contract` e não apaga o teste, porque o inventário de consumidores/contrato legado não está confirmado. A ausência de coleta pelo runner não equivale à prova de obsolescência.
- **Progresso:** 50/52 registros provisoriamente `covered`, **2 pendentes**: OBL-040 (refutação independente efetiva) e OBL-044 (certificado, CI, auditoria posterior ao handoff). Ambos permanecem bloqueantes para aprovação da issue, sem dispensa por testes/documentação.
- Os controles globais `pass_c`, matrizes críticas, risco, controles herdados e linhagem de rejeições continuam sem fechamento formal. Manifesto `incomplete`, sem certificado. O handoff exige novo SHA material e auditoria externa autêntica.

## Estado revisado do contrato de fases — 25/10/2026

- **50/52** registros continuam com cobertura **provisória**: não constituem certificação nem auditoria independente.
- **OBL-040 permanece `pending`**: trata da capacidade funcional de `auditar-issue` para refutar enfraquecimento de testes; não é exclusivamente uma ação externa pós-handoff. Exige evidência discriminante dessa capacidade e fechamento na fase de implementação.
- **OBL-044 está `deferred` apenas para o ato de aprovação independente posterior**: sua decisão usa a própria frase da especificação, hash da fonte canônica e vínculo à issue pai #112, que deve permanecer aberta. As exigências materiais de documentação, testes e CI continuam sendo gates prévios obrigatórios, não podem ser diferidas por essa classificação.
- O contrato de `deferred` requer correspondência entre `decision_locator` e o texto exato da obrigação, vínculo ao corpo da issue autenticado, lista de obrigações diferidas no certificado e verificação da issue pai aberta no gate confiável. Isso **não** significa que o certificado tenha sido produzido.
- `manifest.review_state=incomplete`, `pass_c=pending`, `artifact_sha256={}`, relatórios críticos e fechamento de rejeições anteriores ainda ausentes. Não liberar PR, merge ou fechamento da issue antes de nova certificação e auditoria independente exact-SHA.
