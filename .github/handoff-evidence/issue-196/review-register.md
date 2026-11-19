# Registro de revisão semântica — issue #196 / PR #197

> **Estado:** revisão técnica do implementador, **NÃO** certificado, **NÃO** parecer independente. A análise de oráculos não é substituída por nomes de testes ou contagem JUnit. Nenhum critério da issue foi marcado. **Não liberar merge/auditoria.**

## Identidade e fontes verificáveis

- Issue primária: https://github.com/crgasparoto-br/skill/issues/196 (hash do corpo capturado pela CI: `232097d8148a4b137f4f12b72ee7757066be5352aa037963ab71d86c46a41e0a`).
- PR: https://github.com/crgasparoto-br/skill/pull/197; branch `feat/issue-196-audit-checklist-closure`; base `develop`, SHA `71217ab40be73f64180f253816d7b5214cb23100`.
- Último HEAD técnico conferido antes deste registro: `ed2e0ad65536698b073024a2aa0c07d414a06700`, com [Validate skills](https://github.com/crgasparoto-br/skill/actions/runs/44512089720) e [GitHub Audit MCP](https://github.com/crgasparoto-br/skill/actions/runs/44512089700) aprovados; a gravação deste registro cria novo HEAD e requer CI nova.
- Material JUnit anterior (não reutilizar no HEAD novo sem reconciliação): [artifact #14523713567](https://github.com/crgasparoto-br/skill/actions/runs/44512090031/artifacts/14523713567), digest `sha256:4329d1c460969ca3176e7b9f68c3ae993e248cae24b60cac1c66f8b53a2774ec`, **3.289 testes**.
- Rejeição anterior: [comentário de remediação #6994291840](https://github.com/crgasparoto-br/skill/pull/197#issuecomment-6994291840) descreve A-001 e A-002 para SHA `fc304f252ff4ec7d2bb7234946c8bac94ff65796`; o ID `audit-rejection:40f45186-90c5-43e0-97c5-9ed337fa0876` consta na conversa, porém **não há atestação autenticada** do parecer no GitHub. É lacuna de confiança, não aprovação presumida.

## Matriz completa da especificação original

O texto da coluna **Fonte literal** foi extraído diretamente do corpo da issue #196; a disposição e o racional abaixo são os registrados no dossiê de implementação. `covered` indica somente cobertura proposta pelo implementador; `deferred` exige evento posterior com a issue aberta. Para os testes, os nomes são **vínculos declarados no manifesto**, nunca certificação de oráculo.

### OBL-001 — R196-001

**Fonte literal:** Padronizar a auditoria de implementações para validar todos os critérios de aceite da issue e reconciliar seus checkboxes no GitHub somente após comprovação objetiva, preservando a independência da auditoria.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** A finalidade da issue foi convertida em contrato nas Skills e no parser offline; test_mark_verified_unmark_failed_and_preserve_other_sections verifica marcação individual, e testes negativos impedem aprovação sem evidência. O efeito remoto posterior permanece fase separada.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_mark_verified_unmark_failed_and_preserve_other_sections` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_missing_or_untrusted_decisions` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reopen_checked_criteria_without_verified_evidence` — conferir execução e asserções no JUnit exact-SHA.

### OBL-002 — R196-002

**Fonte literal:** As Skills já exigem fechamento por requisito e auditoria somente leitura, mas não estabelecem um procedimento explícito, seguro e rastreável para marcar critérios de aceite comprovadamente atendidos na própria issue. A atualização deve pertencer a um executor autorizado, nunca ao auditor independente.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** O contrato histórico foi fechado em auditar-issue (somente leitura) e entregar-issue (escrita autorizada) com ponto de integração explícito; testes catalog_governance asseguram a separação de roteamento e de capacidade.

**Teste positive:** `tests.test_catalog_governance::test_router_routes_implementation_pendencies_to_delivery` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_catalog_governance::test_router_blocks_delivery_without_write_capability` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_catalog_governance::test_router_preserves_distinct_or_ambiguous_workflows` — conferir execução e asserções no JUnit exact-SHA.

### OBL-003 — R196-003

**Fonte literal:** Rederivar e examinar cada critério de aceite, incluindo itens inicialmente marcados ou desmarcados, e relacioná-los a provas no SHA auditado.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** A seção auditar-issue/references/report-template.md exige matriz por critério com origem, texto e checkbox observado; tests/test_issue_templates.py cobre reconhecimento da seção normativa. Cobertura de implementação, não atestado independente.

**Teste positive:** `tests.test_issue_templates::test_configured_normative_sections_match_independent_audit_parser` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_issue_templates::test_non_normative_heading_does_not_satisfy_a_normative_section` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_issue_templates::test_shipped_issue_templates_are_valid` — conferir execução e asserções no JUnit exact-SHA.

### OBL-004 — R196-004

**Fonte literal:** Verificar também testes, CI, regressões, segurança, arquitetura, documentação e demais gates aplicáveis, justificando não aplicabilidades.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** A revisão de implementação foi incorporada ao modelo auditar-issue/references/report-template.md e ao checklist de auditoria, incluindo CI, testes, segurança, arquitetura, regressão e não aplicabilidades. tests/test_audit_completeness_gate.py exige completude.

**Teste positive:** `tests.test_audit_completeness_gate::test_complete_audit_can_publish` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_audit_completeness_gate::test_missing_requirement_or_surface_is_blocked` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_audit_completeness_gate::test_entrypoint_requires_completeness_gate` — conferir execução e asserções no JUnit exact-SHA.

### OBL-005 — R196-005

**Fonte literal:** Registrar a decisão por critério e uma ação de checklist proposta, separada do veredito global.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** O modelo auditar-issue/references/report-template.md separa decisão e ação do veredito global; tests/test_audit_completeness_gate.py mantém os critérios de completude antes de publicar parecer.

**Teste positive:** `tests.test_audit_completeness_gate::test_complete_audit_can_publish` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_audit_completeness_gate::test_false_approval_and_false_completeness_are_blocked` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_audit_completeness_gate::test_entrypoint_requires_completeness_gate` — conferir execução e asserções no JUnit exact-SHA.

### OBL-006 — R196-006

**Fonte literal:** Reconciliar o checklist no GitHub em fase de escrita autorizada pós-auditoria, preservando texto e metadados não relacionados.

**Disposição do implementador:** `deferred` (fase posterior à auditoria; não executar antecipadamente).

**Racional documentado:** Obrigação 006 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita GitHub de checklist. Este dossiê não declara o efeito remoto como concluído.

**Vínculo JUnit:** não declarado; a obrigação permanece diferida até evento autenticado.

**Justificativa do diferimento:** Reconciliar o checklist no GitHub em fase de escrita autorizada pós-auditoria, preservando texto e metadados não relacionados. — fonte `SRC-ISSUE-196`, hash `232097d8148a4b137f4f12b72ee7757066be5352aa037963ab71d86c46a41e0a`; parent issue permanece aberta: `true`.

### OBL-007 — R196-007

**Fonte literal:** O parecer deve identificar cada item da seção normativa de critérios de aceite por origem, texto, status inicial e evidência observada.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** auditar-issue/references/report-template.md estabelece matriz por posição, texto da origem, checkbox, evidência e ação; tests/test_issue_templates.py distingue seção normativa e cabeçalhos inertes. A execução independente real é etapa separada.

**Teste positive:** `tests.test_issue_templates::test_configured_normative_sections_match_independent_audit_parser` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_issue_templates::test_non_normative_heading_does_not_satisfy_a_normative_section` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_issue_templates::test_shipped_issue_templates_are_valid` — conferir execução e asserções no JUnit exact-SHA.

### OBL-008 — R196-008

**Fonte literal:** Cada critério deve receber decisão verificável e status de reconciliação; checkbox marcado não constitui prova.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** O parser offline exige decisão explícita para cada critério, evidências para status decisivos e estado inicial, e reabre checkbox sem prova. Testes de rejeição e regressão executam os fluxos relevantes do código.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_mark_verified_unmark_failed_and_preserve_other_sections` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_missing_or_untrusted_decisions` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reopen_checked_criteria_without_verified_evidence` — conferir execução e asserções no JUnit exact-SHA.

### OBL-009 — R196-009

**Fonte literal:** A fase pós-auditoria autorizada deve marcar somente os critérios comprovados na identidade aplicável e confirmar o resultado por nova leitura da issue.

**Disposição do implementador:** `deferred` (fase posterior à auditoria; não executar antecipadamente).

**Racional documentado:** Obrigação 009 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita GitHub de checklist. Este dossiê não declara o efeito remoto como concluído.

**Vínculo JUnit:** não declarado; a obrigação permanece diferida até evento autenticado.

**Justificativa do diferimento:** 3. A fase pós-auditoria autorizada deve marcar somente os critérios comprovados na identidade aplicável e confirmar o resultado por nova leitura da issue. — fonte `SRC-ISSUE-196`, hash `232097d8148a4b137f4f12b72ee7757066be5352aa037963ab71d86c46a41e0a`; parent issue permanece aberta: `true`.

### OBL-010 — R196-010

**Fonte literal:** Itens inconclusivos, sem evidência, parciais ou reprovados permanecem abertos, mesmo com outros itens verificados.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** Os casos test_reopen_checked_criteria_without_verified_evidence e test_mark_verified_unmark_failed_and_preserve_other_sections comprovam o comportamento fail-closed e o tratamento parcial.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_mark_verified_unmark_failed_and_preserve_other_sections` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_missing_or_untrusted_decisions` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reopen_checked_criteria_without_verified_evidence` — conferir execução e asserções no JUnit exact-SHA.

### OBL-011 — R196-011

**Fonte literal:** Alterações concorrentes de conteúdo ou identidade devem impedir atualização ambígua, sem reescrever requisitos.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** O parser rejeita drift material, divergência de texto, posição e SHA; testes test_reject_material_issue_drift e test_reject_stale_sha_and_identity_swap executaram no SHA do artifact #14480097174.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_idempotence_and_checkbox_only_concurrent_updates` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_material_issue_drift[changed0]` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_stale_sha_and_identity_swap` — conferir execução e asserções no JUnit exact-SHA.

### OBL-012 — R196-012

**Fonte literal:** Atualização de checklist não concede aprovação de auditoria, merge ou fechamento e não elimina revalidação de evidências afetadas.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** O código só produz proposta offline e a Skill mantém CI/auditoria como gates separados; test_solo_attestation_is_allowed_without_claiming_independence e cenários negativos preservam a fronteira.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_solo_attestation_is_allowed_without_claiming_independence` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_missing_or_untrusted_decisions` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reopen_checked_criteria_without_verified_evidence` — conferir execução e asserções no JUnit exact-SHA.

### OBL-013 — R196-013

**Fonte literal:** Preferir os fluxos e Skills existentes, sem nova Skill nem duplicação de fontes normativas.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** AGENTS.md e as Skills existentes foram estendidos sem criar nova Skill; Validate skills #44416696697 aprovou catálogo e referências, com testes de roteamento e reuse.

**Teste positive:** `tests.test_catalog_governance::test_catalog_is_valid_and_matches_skill_metadata` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_catalog_governance::test_router_fails_closed_on_ambiguous_or_unknown_request` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_catalog_governance::test_runtime_skill_allowlist_matches_catalog` — conferir execução e asserções no JUnit exact-SHA.

### OBL-014 — R196-014

**Fonte literal:** Preservar a operação somente leitura de auditar-issue e o ownership de escrita de entregar-issue.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** auditar-issue/SKILL.md mantém modo somente leitura, enquanto entregar-issue/references/issue-checklist-reconciliation.md define write ownership; testes de roteamento bloqueiam escrita sem capacidade.

**Teste positive:** `tests.test_catalog_governance::test_router_routes_implementation_pendencies_to_delivery` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_catalog_governance::test_router_blocks_delivery_without_write_capability` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_catalog_governance::test_router_blocks_pending_implementation_without_write_capability` — conferir execução e asserções no JUnit exact-SHA.

### OBL-015 — R196-015

**Fonte literal:** [ ] O parecer apresenta cada critério de aceite individualmente com evidência exata, decisão e estado do checkbox.

**Disposição do implementador:** `deferred` (fase posterior à auditoria; não executar antecipadamente).

**Racional documentado:** Obrigação 015 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita GitHub de checklist. Este dossiê não declara o efeito remoto como concluído.

**Vínculo JUnit:** não declarado; a obrigação permanece diferida até evento autenticado.

**Justificativa do diferimento:** [ ] O parecer apresenta cada critério de aceite individualmente com evidência exata, decisão e estado do checkbox. — fonte `SRC-ISSUE-196`, hash `232097d8148a4b137f4f12b72ee7757066be5352aa037963ab71d86c46a41e0a`; parent issue permanece aberta: `true`.

### OBL-016 — R196-016

**Fonte literal:** [ ] A auditoria cobre e registra todas as verificações de implementação aplicáveis, não apenas os checkboxes ou a CI verde.

**Disposição do implementador:** `deferred` (fase posterior à auditoria; não executar antecipadamente).

**Racional documentado:** Obrigação 016 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita GitHub de checklist. Este dossiê não declara o efeito remoto como concluído.

**Vínculo JUnit:** não declarado; a obrigação permanece diferida até evento autenticado.

**Justificativa do diferimento:** [ ] A auditoria cobre e registra todas as verificações de implementação aplicáveis, não apenas os checkboxes ou a CI verde. — fonte `SRC-ISSUE-196`, hash `232097d8148a4b137f4f12b72ee7757066be5352aa037963ab71d86c46a41e0a`; parent issue permanece aberta: `true`.

### OBL-017 — R196-017

**Fonte literal:** [ ] O auditor independente não modifica a issue; a atualização ocorre em etapa autorizada posterior.

**Disposição do implementador:** `deferred` (fase posterior à auditoria; não executar antecipadamente).

**Racional documentado:** Obrigação 017 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita GitHub de checklist. Este dossiê não declara o efeito remoto como concluído.

**Teste positive:** `tests.test_catalog_governance::test_router_routes_implementation_pendencies_to_delivery` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_catalog_governance::test_router_blocks_delivery_without_write_capability` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_catalog_governance::test_router_blocks_pending_implementation_without_write_capability` — conferir execução e asserções no JUnit exact-SHA.

**Justificativa do diferimento:** a atualização ocorre em etapa autorizada posterior — fonte `SRC-ISSUE-196`, hash `232097d8148a4b137f4f12b72ee7757066be5352aa037963ab71d86c46a41e0a`; parent issue permanece aberta: `true`.

**Recorte pré-handoff:** [ ] O auditor independente não modifica a issue; O trecho pré-handoff está implementado em auditar-issue/SKILL.md (somente leitura) e entregar-issue/SKILL.md (escrita autorizada) e foi conferido pelo roteamento fail-closed.

### OBL-018 — R196-018

**Fonte literal:** [ ] A reconciliação marca apenas critérios comprovados, é idempotente e confirma o resultado por leitura no GitHub.

**Disposição do implementador:** `deferred` (fase posterior à auditoria; não executar antecipadamente).

**Racional documentado:** Obrigação 018 vinculada à fase posterior à auditoria: a issue #196 permanece aberta, não houve parecer independentemente autenticado nem escrita GitHub de checklist. Este dossiê não declara o efeito remoto como concluído.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_idempotence_and_checkbox_only_concurrent_updates` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_missing_or_untrusted_decisions` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reopen_checked_criteria_without_verified_evidence` — conferir execução e asserções no JUnit exact-SHA.

**Justificativa do diferimento:** e confirma o resultado por leitura no GitHub — fonte `SRC-ISSUE-196`, hash `232097d8148a4b137f4f12b72ee7757066be5352aa037963ab71d86c46a41e0a`; parent issue permanece aberta: `true`.

**Recorte pré-handoff:** [ ] A reconciliação marca apenas critérios comprovados, é idempotente; O trecho pré-handoff está implementado em reconcile_issue_checkboxes.py, que decide por evidência, impede alteração indevida e é idempotente; os testes de idempotência e rejeição executaram no SHA.

### OBL-019 — R196-019

**Fonte literal:** [ ] Critérios sem prova permanecem pendentes; divergência material da issue ou do SHA bloqueia marcação automática.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** Sem provas, o estado permanece aberto; drift normativo, SHA e ordem são rejeitados, conforme os testes negativos test_reject_material_issue_drift e test_reject_stale_sha_and_identity_swap.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_mark_verified_unmark_failed_and_preserve_other_sections` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_stale_sha_and_identity_swap` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reopen_checked_criteria_without_verified_evidence` — conferir execução e asserções no JUnit exact-SHA.

### OBL-020 — R196-020

**Fonte literal:** [ ] A conclusão global da issue depende dos gates e da auditoria independente, nunca apenas do checklist.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** O fluxo de entrega proíbe aprovação e fechamento apenas por checkbox; issue #196 segue open, 0/7 marcados, com gate semântico vermelho apesar dos testes verdes.

**Teste positive:** `tests.test_audit_completeness_gate::test_no_unreported_blocker_and_no_premature_closure` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_audit_completeness_gate::test_false_approval_and_false_completeness_are_blocked` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_audit_completeness_gate::test_complete_audit_can_publish` — conferir execução e asserções no JUnit exact-SHA.

### OBL-021 — R196-021

**Fonte literal:** [ ] A documentação normativa permanece genérica, coerente com as Skills e validada pelos checks aplicáveis.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** As alterações normativas permanecem em auditar-issue e entregar-issue sem regras específicas de produto; Validate skills #44416696697 e testes do catálogo estão verdes.

**Teste positive:** `tests.test_catalog_governance::test_documentation_references_are_current` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_catalog_governance::test_contract_validator_detects_generated_copy_drift` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_catalog_governance::test_catalog_documentation_is_generated_and_current` — conferir execução e asserções no JUnit exact-SHA.

### OBL-022 — R196-022

**Fonte literal:** Validar instruções e referências cruzadas com os validadores canônicos.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** Validate skills #44416696697 executou validadores de repositório, catálogo, referências e higiene, com testes de regressão para seções normativas.

**Teste positive:** `tests.test_issue_templates::test_shipped_issue_templates_are_valid` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_issue_templates::test_missing_required_template_blocks` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_issue_templates::test_configured_normative_sections_match_producer_parser` — conferir execução e asserções no JUnit exact-SHA.

### OBL-023 — R196-023

**Fonte literal:** Cobrir decisões positivas, negativas e idempotência na reconciliação, evitando conclusões autoafirmadas.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** Os testes de reconciliação cobrem aceitação positiva, rejeição de drift, ausência de evidência, status partial, duplicidade, cerca de código e idempotência no SHA corrente.

**Teste positive:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_mark_verified_unmark_failed_and_preserve_other_sections` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_reject_material_issue_drift[changed0]` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `entregar-issue.tests.test_issue_checklist_reconciliation::test_idempotence_and_checkbox_only_concurrent_updates` — conferir execução e asserções no JUnit exact-SHA.

### OBL-024 — R196-024

**Fonte literal:** Conferir CI e integridade do diff na PR de implementação.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** A comparação da PR com a base e os workflows Validate skills #44416696697 e Audit MCP #44416696675 são fontes técnicas verdes; handoff semântico separado ainda está bloqueado.

**Teste positive:** `tests.test_audit_completeness_gate::test_complete_audit_can_publish` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_audit_completeness_gate::test_changed_path_is_not_silently_skipped` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_audit_completeness_gate::test_diff_source_is_not_self_reported` — conferir execução e asserções no JUnit exact-SHA.

### OBL-025 — R196-025

**Fonte literal:** Atualizar as instruções canônicas de auditar-issue, o modelo de parecer e o controlador de conclusão em entregar-issue; atualizar política global apenas se necessário.

**Disposição do implementador:** `covered` (provisória, pendente de revisão independente).

**Racional documentado:** auditar-issue/SKILL.md, auditar-issue/references/report-template.md, entregar-issue/SKILL.md e referência de reconciliação foram alterados; validação documental e catálogo verdes.

**Teste positive:** `tests.test_catalog_governance::test_documentation_references_are_current` — conferir execução e asserções no JUnit exact-SHA.

**Teste negative:** `tests.test_catalog_governance::test_contract_validator_detects_generated_copy_drift` — conferir execução e asserções no JUnit exact-SHA.

**Teste regression:** `tests.test_catalog_governance::test_catalog_documentation_is_generated_and_current` — conferir execução e asserções no JUnit exact-SHA.

## Controles e relatórios pendentes

**Contagem:** 19 coberturas provisórias, 6 obrigações diferidas e **zero aprovação semântica autenticada**. Total rederivado: 25/25. Critérios de aceite da issue: 0/7 marcados.

| Família canônica | Estado atual | Impedimento factual |
|---|---|---|
| `domain_inventories` | `pending-empty` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |
| `observable_assertions` | `pending-empty` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |
| `structural_invariant_closures` | `pending` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |
| `read_model_closures` | `pending` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |
| `canonical_source_consistency` | `pending` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |
| `documentation_consistency` | `pending` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |
| `scope_reduction_review` | `pending` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |
| `pass_c` | `pending` | Revisão independente das evidências e controles de fronteira, SHA, integridade documental e read-back não concluída |

**Relatórios exigidos ainda ausentes no HEAD anterior (inventário oficial do artifact #14523713567):** `audit-escape-closure.json`, `audit-remediation.json`, `audit-source-result.json`, `inherited-controls.json`, `learning-closure.json`, `previous-audit-escape-closure.json`, `requirement-attack-matrix.json`, `risk-saturation.json`.

**Bloqueador autenticado:** `certification-inputs.json absent: semantic closures have not been supplied` no [run #44512090031](https://github.com/crgasparoto-br/skill/actions/runs/44512090031). Sem origem auditora autenticada não é permitido fabricar `audit-source-result.json`, hashes de relatório ou estados `passed` para liberar CI. `manifest.review_state=incomplete` permanece intencionalmente inalterado.

## Próximo gate permitido

Obter prova autenticada da rejeição anterior (ou confirmação independente e verificável de seu enquadramento) e executar revisão semântica discriminante no SHA final. Completar os relatórios críticos, seus hashes e os controles por requisito, validar o certificado no GitHub Actions e então encaminhar a auditoria independente em contexto separado. Só após o parecer aceito a fase autorizada poderá reconciliar checkboxes por read-back e decidir o encerramento da issue.
