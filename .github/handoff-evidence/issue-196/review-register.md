# Registro de revisão semântica — issue #196 / PR #197

> Este registro foi preparado pelo **implementador**. Não é auditoria independente, atestação solo autenticada, certificado ou autorização de merge. O status `covered` em `reviewed-closure.json` é **provisório** enquanto `manifest.review_state=incomplete`.

## Identidade do contrato

- Repositório: `crgasparoto-br/skill`; base obrigatória: `develop`.
- Fonte primária: [issue #196](https://github.com/crgasparoto-br/skill/issues/196).
- PR e branch: [#197](https://github.com/crgasparoto-br/skill/pull/197), `feat/issue-196-audit-checklist-closure`.
- Revisão canônica: `25` obrigações rederivadas, cada uma vinculada ao seu `candidate_key` no arquivo `reviewed-closure.json`.
- Checkboxes de aceite: `7` abertos, nenhuma escrita na issue pelo implementador antes de autenticar a auditoria.
- Proveniência de testes: material disponível em artifacts do GitHub Actions; os bindings são índices para o runner confiável e exigem validação pelo SHA final.
- Histórico de rejeição: A-001 e A-002 no SHA auditado `fc304f252ff4ec7d2bb7234946c8bac94ff65796`; falta o resultado externo assinado/autenticado e o hash verificável do parecer completo. Não inventar esse hash nem atestação.

## Matriz de 25 obrigações (preliminar)

A declaração `Provisório` identifica código/testes/documentação mapeados pelo implementador, **não** comprovação independente. `Diferido` representa cláusula cuja execução real requer parecer aceito, escrita autorizada ou read-back posterior. O relatório canônico contém os textos integrais, hashes, IDs e justificativas.

| Obrigação | Disposição atual | ID funcional | Evidência/revisão preliminar | Texto estritamente diferido |
|---|---|---|---|---|
| OBL-001 | Provisório | R196-001 | A finalidade da issue foi convertida em contrato nas Skills e no parser offline; test_mark_verified_unmark_failed_and_preserve_other_sections ver | — |
| OBL-002 | Provisório | R196-002 | O contrato histórico foi fechado em auditar-issue (somente leitura) e entregar-issue (escrita autorizada) com ponto de integração explícito; test | — |
| OBL-003 | Provisório | R196-003 | A seção auditar-issue/references/report-template.md exige matriz por critério com origem, texto e checkbox observado; tests/test_issue_templates. | — |
| OBL-004 | Provisório | R196-004 | A revisão de implementação foi incorporada ao modelo auditar-issue/references/report-template.md e ao checklist de auditoria, incluindo CI, teste | — |
| OBL-005 | Provisório | R196-005 | O modelo auditar-issue/references/report-template.md separa decisão e ação do veredito global; tests/test_audit_completeness_gate.py mantém os cr | — |
| OBL-006 | Diferido | R196-006 | Obrigação 006 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita  | Reconciliar o checklist no GitHub em fase de escrita autorizada pós-auditoria, p |
| OBL-007 | Provisório | R196-007 | auditar-issue/references/report-template.md estabelece matriz por posição, texto da origem, checkbox, evidência e ação; tests/test_issue_template | — |
| OBL-008 | Provisório | R196-008 | O parser offline exige decisão explícita para cada critério, evidências para status decisivos e estado inicial, e reabre checkbox sem prova. Test | — |
| OBL-009 | Diferido | R196-009 | Obrigação 009 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita  | 3. A fase pós-auditoria autorizada deve marcar somente os critérios comprovados  |
| OBL-010 | Provisório | R196-010 | Os casos test_reopen_checked_criteria_without_verified_evidence e test_mark_verified_unmark_failed_and_preserve_other_sections comprovam o compor | — |
| OBL-011 | Provisório | R196-011 | O parser rejeita drift material, divergência de texto, posição e SHA; testes test_reject_material_issue_drift e test_reject_stale_sha_and_identit | — |
| OBL-012 | Provisório | R196-012 | O código só produz proposta offline e a Skill mantém CI/auditoria como gates separados; test_solo_attestation_is_allowed_without_claiming_indepen | — |
| OBL-013 | Provisório | R196-013 | AGENTS.md e as Skills existentes foram estendidos sem criar nova Skill; Validate skills #44416696697 aprovou catálogo e referências, com testes d | — |
| OBL-014 | Provisório | R196-014 | auditar-issue/SKILL.md mantém modo somente leitura, enquanto entregar-issue/references/issue-checklist-reconciliation.md define write ownership;  | — |
| OBL-015 | Diferido | R196-015 | Obrigação 015 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita  | [ ] O parecer apresenta cada critério de aceite individualmente com evidência ex |
| OBL-016 | Diferido | R196-016 | Obrigação 016 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita  | [ ] A auditoria cobre e registra todas as verificações de implementação aplicáve |
| OBL-017 | Diferido | R196-017 | Obrigação 017 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita  | a atualização ocorre em etapa autorizada posterior |
| OBL-018 | Diferido | R196-018 | Obrigação 018 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita  | e confirma o resultado por leitura no GitHub |
| OBL-019 | Provisório | R196-019 | Sem provas, o estado permanece aberto; drift normativo, SHA e ordem são rejeitados, conforme os testes negativos test_reject_material_issue_drift | — |
| OBL-020 | Provisório | R196-020 | O fluxo de entrega proíbe aprovação e fechamento apenas por checkbox; issue #196 segue open, 0/7 marcados, com gate semântico vermelho apesar dos | — |
| OBL-021 | Provisório | R196-021 | As alterações normativas permanecem em auditar-issue e entregar-issue sem regras específicas de produto; Validate skills #44416696697 e testes do | — |
| OBL-022 | Provisório | R196-022 | Validate skills #44416696697 executou validadores de repositório, catálogo, referências e higiene, com testes de regressão para seções normativas | — |
| OBL-023 | Provisório | R196-023 | Os testes de reconciliação cobrem aceitação positiva, rejeição de drift, ausência de evidência, status partial, duplicidade, cerca de código e id | — |
| OBL-024 | Provisório | R196-024 | A comparação da PR com a base e os workflows Validate skills #44416696697 e Audit MCP #44416696675 são fontes técnicas verdes; handoff semântico  | — |
| OBL-025 | Provisório | R196-025 | auditar-issue/SKILL.md, auditar-issue/references/report-template.md, entregar-issue/SKILL.md e referência de reconciliação foram alterados; valid | — |

## Gates e lacunas que continuam bloqueantes

- `codebase-grounding.json`: inventário provisório de arquivos de código e de testes alterados; o binding dos resultados não aprova sozinho os oráculos.
- `CODE-GROWTH-001`: aprovado no artefato histórico de coleta da PR; revalidar no HEAD final.
- `Validate skills`, `Validate GitHub Audit MCP` e execução JUnit: só considerar `success` pelo run GitHub exato do HEAD final.
- Relatórios ainda sujeitos a produção e validação: `requirement-attack-matrix.json`, `risk-saturation.json`, `inherited-controls.json`, `audit-remediation.json`, `audit-source-result.json`, `learning-closure.json`, `audit-escape-closure.json`, `previous-audit-escape-closure.json`.
- `reviewed-closure.json` ainda possui famílias de controle `pending`; o `manifest.json` permanece `review_state=incomplete` e `artifact_sha256={}`.
- A certificação requer fonte de rejeição independente autenticada. O parecer textual de conversa anterior não foi registrado como revisão GitHub autenticada; seu ID declarado não comprova integridade nem origem. Sem essa prova, não emitir `certification-inputs.json`, não marcar critérios, não fechar issue nem executar merge.

## Próxima condição verificável

Concluir controles positivos/negativos/regressão por requisito e família, confirmar JUnit exact-SHA, produzir e validar relatórios com hashes autênticos, resolver a autenticidade da rejeição anterior e obter handoff terminal. Encaminhar o candidato para `auditar-issue` **em contexto separado**. Só então reconciliar checkboxes individuais com provas e read-back, preservando a issue aberta enquanto houver cláusulas diferidas.
