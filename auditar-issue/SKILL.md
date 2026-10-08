---
name: auditar-issue
description: Auditar em modo somente leitura implementacoes de issues, PRs, branches ou commits, comparando contrato, codigo, dados, testes, documentacao e comportamento executado. Usar em contexto separado para auditoria independente ou em `controller_mode=delivery-single-invocation`. Executar verificacao proporcional ao risco, evitar repetir auditoria da mesma identidade e reutilizar somente evidencias brutas validas. Em controller-adversarial produzir apenas aprovacao interna provisoria; nunca corrigir codigo nem declarar independencia inexistente.
---

# Auditar Issue

## Objetivo

Tentar refutar a entrega em somente leitura. Tratar o pacote recebido como indice, nao conclusao. Produzir evidencia propria suficiente para o nivel de garantia real sem repetir trabalho quando identidade e inputs permanecem identicos.

## Validade

- `independent`: contexto separado daquele que implementou, corrigiu ou coordenou o SHA.
- `pre-audit`: separacao nao demonstrada.
- `controller-adversarial`: pre-auditoria rigorosa no controlador de chamada unica; produz no maximo aprovacao interna.

Trocar de skill no mesmo contexto nao cria independencia.
O `internal-adversarial-gate` de `entregar-issue` e somente pre-auditoria; a auditoria `independent` existe fora do state graph da entrega.

## Origem da entrega e dono da remediacao

Resolver `delivery_origin` antes de emitir qualquer opcao de continuidade:

- `direct-entregar-issue`: a entrada veio de `entregar-issue`, de `controller_mode=delivery-single-invocation` com `return_control_to=entregar-issue`, ou de handoff certificado `.audit/entregar-issue` que pertence ao target atual.
- `standalone-unknown`: a origem anterior nao foi demonstrada.

Em `standalone-unknown`, entregar os findings sem escolher controlador por conta propria.

## Padrao obrigatorio da resposta

Comecar toda resposta humana sem preambulo e com exatamente uma destas linhas:

- `# RESULTADO: APROVADA`
- `# RESULTADO: APROVADA COM RESSALVAS`
- `# RESULTADO: APROVADA INTERNAMENTE`
- `# RESULTADO: INCONCLUSIVA`
- `# RESULTADO: REPROVADA`

Nao colocar titulo, validade, resumo, contexto, saudacao ou explicacao antes dessa linha. A primeira informacao visivel deve ser o resultado.

Imediatamente abaixo dessa linha, abrir o parecer com o bloco de conclusao em destaque:

```markdown
> **Conclusao:** `[veredito]` — achados bloqueantes: `[n]` — recomendacoes opcionais: `[n]`
> **Motivo determinante:** [uma frase objetiva]
> **Libera merge/release:** [SIM | NAO]

**Validade:** [Independente | Controller-adversarial | Pre-auditoria]
```

O bloco deixa a conclusao visivel nas primeiras linhas e nao substitui o motivo determinante, a matriz, os achados nem o resultado estruturado; divergencia entre eles e defeito do parecer. Em `INCONCLUSIVA` por runtime, declarar no bloco que nao ha defeito funcional atribuido ao candidato.

Aplicar o mapeamento deterministico:

- `APROVADA`: somente auditoria `independent`, sem finding bloqueante, sem limitacao material e com todos os gates obrigatorios aprovados.
- `APROVADA COM RESSALVAS`: somente auditoria `independent`, sem finding bloqueante, mas com ressalva material nao bloqueante explicitamente demonstrada.
- `APROVADA INTERNAMENTE`: `controller-adversarial` ou pre-auditoria favoravel, sem finding bloqueante; nunca libera merge, fechamento ou release.
- `INCONCLUSIVA`: somente quando uma limitacao do runtime, ferramenta ou connector da propria auditoria impedir obter bytes exatos, executar recurso interno da Skill ou observar evidencia obrigatoria, sem evidencia de que o candidato ou a entrega causaram a limitacao. Nao converter limitacao de infraestrutura da auditoria em finding da issue.
- `REPROVADA`: qualquer finding bloqueante, requisito incorreto ou nao implementado, identidade invalidada, gate obrigatorio falho/ausente por responsabilidade do candidato ou da entrega, handoff ausente/stale/inconsistente quando `audit_transport=certified-handoff`, ou evidencia material que a entrega deveria ter produzido mas nao produziu. Em `native-github-audit`, ausencia de `.audit/entregar-issue` nao e finding por si so.

A decisao de liberacao aparece uma unica vez, no bloco de conclusao. Nao repetir a mesma informacao em outro ponto do cabecalho.

Usar `SIM` somente para `APROVADA` ou `APROVADA COM RESSALVAS` com validade realmente independente e portao de release satisfeito. Para `APROVADA INTERNAMENTE`, `INCONCLUSIVA` e `REPROVADA`, usar sempre `NAO`. Depois apresentar motivo determinante, achados e evidencias. O resultado estruturado JSON continua obedecendo aos schemas e nao deve ser inferido apenas do cabecalho humano.

## Carregamento progressivo

Ler sempre `references/evidence-rules.md` e `references/gate-preflight.md`. Ler `references/delivery-contract.md` somente quando houver handoff composto ou modo controller.

Ler somente quando aplicavel:

- controller: `references/controller-mode.md` e `references/controller-evidence-contract.md`;
- desenho de controle negativo: `references/adversarial-control-design.md`;
- finding contra candidato antes aprovado internamente ou auditorias repetidas: `references/audit-escape-feedback.md`;
- nova auditoria apos reprovação independente/remediacao: `references/reaudit-readiness.md` e validar `audit-remediation.json`;
- pacote de entrega antes de gastar auditoria ampla: `references/delivery-saturation-preflight.md`;
- perfil de evidencia do handoff: `references/evidence-profiles-audit.md`;
- selecao entre handoff certificado e auditoria GitHub-native: `references/native-github-audit-contract.md`;
- certificado obrigatorio de handoff, somente quando `audit_transport=certified-handoff`: `references/handoff-certificate-preflight.md`;
- criterio quantitativo, benchmark, percentil ou controle `evidence_kind=quantitative`: `references/quantitative-evidence-audit.md`;
- `CODE-GROWTH-001` aplicavel ou artefato `code_growth` certificado: `references/code-growth-audit.md`;
- diff com codigo executavel adicionado, referencia nova ou comportamento substituido: `references/codebase-grounding-audit.md`;
- resolucao de scripts/artefatos no runtime: `references/runtime-resource-resolution.md`;
- manifesto `base64-shards-v1`, artefato grande ou handoff transport-sharded: `references/large-artifact-consumption.md`;
- auditoria `independent` ampla: `references/audit-checklist.md` como roteiro de cobertura (item nao aplicavel exige justificativa);
- apos primeiro blocker: `references/blocker-harvest.md`;
- provider, retry/fallback, ferramenta externa ou workflow com credenciais: `references/provider-call-and-secret-audit.md`;
- `input-parser`: `references/input-parser-audit.md`;
- auditoria externa assinada: `references/external-audit-contract.md`;
- entrega: `references/report-template.md`.

## Invariantes

1. Nao modificar codigo, banco, branch, PR ou issue.
2. Nao corrigir findings durante auditoria.
3. Fixar identidade no inicio e revalidar no fim. Resolver primeiro `audit_transport` conforme `references/native-github-audit-contract.md`. Somente quando `audit_transport=certified-handoff`, antes de consumir qualquer pacote `.audit/entregar-issue`, provar o vinculo semantico com o alvo resolvido: em schema v2, `subject.repository/work_item_kind/work_item_number/pull_request/base_ref/head_ref` deve corresponder ao target; em todo schema, `specification-snapshot.repository/issue` deve confirmar o trabalho corrente. Antes de atribuir uma divergencia de target ao candidato, comparar `handoff-ready.json` do head com o mesmo caminho no SHA imutavel da base. Se o objeto for identico e o subject pertencer a outra entrega, classificar como `inherited-base-artifact`: o handoff corrente nao foi produzido (`reason=handoff-not-produced`, `recovery_scope=handoff-only` quando nao houver drift material). Somente divergencia de target que tenha origem na entrega corrente usa `fresh-handoff-required`. Para certificado schema v2, distinguir `material_head_sha` do `published_handoff_head_sha` result-only; para schema v1, ambos coincidem.
4. Nao aceitar CI verde, checklist ou teste novo como prova unica.
4.1. Para artefato transport-sharded, reconstruir bytes logicos somente por `scripts/audit_artifact_io.py` e exigir hashes de manifesto/partes + `logical_sha256`; parte ausente ou divergente bloqueia o consumo. O suporte a shards e estritamente somente leitura.
5. Nao reutilizar conclusao do implementador como evidencia.
6. Nao produzir aprovacao importavel sem contexto separado e chave previamente confiada.
7. Em modo controller, devolver o resultado ao `entregar-issue` no mesmo fluxo, sem encerrar o ciclo e nao orientar nova conversa. `auditar-issue` permanece somente leitura e nunca chama `corrigir-ci`. Quando a recuperacao for exclusivamente terminal e a CI do `material_head_sha` exato ja estiver comprovadamente verde, incluir `next_phase=finalize-after-ci` para que o controlador retome no fast path terminal sem redescoberta, reimplementacao ou novo ciclo de CI material.
8. Separar `blocking` de `recommendation`.
9. Nao repetir auditoria quando fingerprint, identidade material e artefatos auditados forem identicos; ignorar apenas timestamps de observacao. Devolver o relatorio vigente com `input_fingerprint`, `reused=true`, `reuse_source` verificavel, `changed_files=[]` e `requires_refreeze=false`.
10. Qualquer mudanca de identidade, contrato, risco, ambiente ou evidencia obrigatoria invalida o reaproveitamento.
11. Operar GitHub em somente leitura: nao disparar, reexecutar, cancelar ou aprovar workflow/environment/deployment.
12. Nao exigir criacao de workflow para fechar lacuna de evidencia e nao pedir ao usuario aprovacao manual.
13. Para identidade, CI e estado operacional corrente, preferir metadata remota e artefatos brutos atuais a descricao da PR, checklist ou narrativa da implementacao.
14. Nunca tratar teste apenas declarado no codigo como teste executado; registrar separadamente `declared`, `reached` e `passed`.
15. Finding contra candidato antes aprovado internamente continua sendo `audit_escape`, mas **nao e sistemico por definicao**. Classificar cada item como `targeted-remediation` (padrao) ou `systemic-remediation`. Usar `systemic-remediation` somente com evidencia de falha generalizavel/recorrente do controle; apenas nesse modo exigir casos irmaos, prevencao/deteccao reutilizavel e promocao de aprendizado.
16. Em reauditoria, exigir `audit-remediation.json` fechando 1:1 todos os findings e recomendacoes acionaveis da rodada anterior. Para itens targeted, reexecutar o caso corrigido e superficies diretamente impactadas sem exigir controles herdados. Para itens systemic, manter o protocolo cumulativo de controles herdados.
16.1. Toda **nova** auditoria `independent` com resultado `REPROVADA` deve emitir um `rejection_id` estavel no formato `audit-rejection:<id>`, gerado por `scripts/new_rejection_id.py`; nunca compor o identificador manualmente. Em reauditoria, se o preflight provar que o mesmo finding anterior continua aberto com fingerprint equivalente (mesmo finding ID, requisito/gate/classe e, quando houver, mesmo `failed_gate.command`), reutilizar o `rejection_id` anterior e marcar `rejection_lineage.mode=continuation`; nao criar nova rejeicao nem novo learning event. Gerar novo ID somente para finding materialmente novo ou depois de o anterior ter sido efetivamente fechado. Usar `scripts/classify_rejection_continuity.py` quando houver resultado estruturado anterior e corrente.
16.2. Para finding causado por gate deterministico executado e vermelho, registrar `failed_gate` com `name`, comando exato, `deterministic=true`, SHA/identidade observada, exit code nao zero e `evidence_sha256`. Isso permite que `entregar-issue` prove a remediacao pelo mesmo comando; nao aceitar descricao textual como substituto desse contrato.
17. Antes de uma auditoria ampla em `certified-handoff`, validar o `evidence_profile` certificado: `light` usa closure + gates aplicaveis; `standard` exige `standard-evidence.json`; `critical` exige matriz de ataques, saturacao e controles herdados. Se a closure/rederivacao revelar risco critico incompatível com perfil menor, reprovar por `delivery-not-saturated` antes de provas caras. Validar tambem `CODE-GROWTH-001` quando certificado. Em `native-github-audit`, derivar risco/perfil e gates obrigatorios do contrato canonico confiavel e das evidencias remotas exact-SHA do repositorio; nao exigir `standard-evidence.json`, matriz ou outros artefatos `.audit` salvo se o proprio contrato nativo os definir fora do root legado. Rejeicao independente anterior `targeted-remediation` preserva o perfil de risco corrente; somente `systemic-remediation|mixed-remediation` exige `critical`.
18. Depois do primeiro blocker, completar a colheita barata por todos os requisitos atomicos e familias materiais ainda nao exercitados; nao devolver um blocker por auditoria quando outros independentes sao observaveis no mesmo SHA.
19. Tratar liveness de referencias e coerencia temporal de destino como familias canonicas: validade em T1 nao prova uso seguro em T3, e data sintaticamente valida nao prova destino futuro/periodo coerente.
20. Interpretar caminhos `scripts/...`, `references/...`, `schemas/...` e `tests/...` como relativos ao pacote instalado da Skill `auditar-issue`, nunca ao repositorio auditado. Nao exigir que o repositorio versione, copie ou venda esses recursos internos.
21. Quando a Skill estiver exposta apenas por resource URI, materializar seus recursos internos necessarios em diretorio efemero antes de executar; quando o repositorio estiver apenas em connector remoto, materializar somente os artefatos de entrada necessarios preservando os bytes exatos. Nunca alterar o repositorio para viabilizar a auditoria.
22. Se o runtime/connector impedir a materializacao exata ou a execucao de recurso interno da Skill apos tentativas razoaveis, classificar `audit-runtime-limitation`: resultado humano `INCONCLUSIVA`, `Libera merge/release: NAO`, `findings=[]` para essa causa, `requires_refreeze=false` salvo mudanca real de identidade. Nao usar `delivery-not-ready`, `red-candidate-caused`, `missing` ou `not-reached` para uma incapacidade exclusiva do ambiente do auditor. Nao propor commit, issue corretiva, workflow ou mudanca no produto para corrigir infraestrutura da auditoria.

## Fluxo

### 0. Preflight de readiness e reauditoria

Antes de qualquer auditoria ampla de uma entrega preparada por `entregar-issue`, resolver primeiro `audit_transport` conforme `references/native-github-audit-contract.md`. Para PR, o contrato que autoriza `native-github-audit` deve ser lido do `base_sha` imutavel; uma regra introduzida apenas pelo proprio candidato nunca pode se autoisentar. Materializar o manifesto e executar `<AUDIT_SKILL_ROOT>/scripts/classify_audit_transport.py`.

Se o classificador devolver `native-github-audit`, **nao exigir nem procurar como pre-requisito** `.audit/entregar-issue/handoff-ready.json`. Congelar diretamente a identidade remota atual (`repository`, work item/issue, PR quando houver, `base_ref/base_sha`, `head_ref/current_head_sha`, merge preview quando aplicavel), changed paths, risk/policy observavel e runs/checks exact-head. A ausencia de `.audit/entregar-issue` nesse modo e comportamento esperado, nao `delivery-not-ready`. Continuar com `references/gate-preflight.md` e com a auditoria proporcional ao risco; o contrato nativo remove somente o transporte legado e nao reduz independencia, cobertura ou fail-closed.

Se o classificador devolver `certified-handoff`, exigir e validar `.audit/entregar-issue/handoff-ready.json` conforme `references/handoff-certificate-preflight.md`. Resolver primeiro por fonte remota o target atual (`repository`, `work_item_kind`, `work_item_number`, PR quando houver, `base_ref`, `head_ref`) e tratar essa resolucao como autoridade sobre qualquer `.audit` herdado. Antes de validar um certificado encontrado no head como pertencente ao candidato, consultar o mesmo caminho no SHA imutavel da base e comparar bytes/blob Git. Se o certificado estrangeiro ja existia identico na base, ele e `inherited-base-artifact`, nao handoff produzido pela PR: considerar o handoff do alvo atual ausente, usar `reason=handoff-not-produced` e `recovery_scope=handoff-only` quando nenhuma escrita material posterior exigir refreeze. Quando a matriz declarar evidencia quantitativa, exigir tambem `evidence-provenance.json` e provar `subject_sha == material_head_sha`; `head_sha` reescrito na matriz nao substitui proveniencia da execucao. Suportar tanto schema v1 exact-head quanto schema v2 `result-only-child`; schema v2 exige `subject` semanticamente vinculado ao target e todo schema exige `specification-snapshot.repository/issue` coerente com o target resolvido. No schema v2, coletar parent e changed paths do head publicado antes do preflight e auditar o `material_head_sha` certificado. Certificado realmente ausente, stale, produzido pela entrega mas vinculado a target estrangeiro, com parent/path/identidade divergente ou hash inconsistente retorna `REPROVADA` por `delivery-not-ready` sem consumir descoberta ampla ou suites caras. Distinguir a recuperacao: `handoff-only` para handoff nao produzido ou quando falta somente pacote/filho terminal sem drift material; parent divergente/path material/cadeia material posterior exige `post-write-refreeze` e `requires_refreeze=true`; target estrangeiro originado na entrega corrente exige `fresh-handoff-required`.

No modo `certified-handoff`, resolver primeiro o root do pacote **da Skill `auditar-issue`** e executar `<AUDIT_SKILL_ROOT>/scripts/check_delivery_preflight.py` como portao unico de readiness, passando obrigatoriamente `--repository`, `--work-item-kind` e `--work-item-number` e, quando conhecidos, `--pull-request`, `--base-ref` e `--head-ref`; quando o mesmo caminho existir no SHA imutavel da base, materializar tambem esse `handoff-ready.json` e passar `--base-certificate` para permitir classificacao deterministica de `inherited-base-artifact`. `scripts/...` nunca significa caminho dentro do repositorio auditado. Ler `references/runtime-resource-resolution.md` antes da execucao. Materializar os artefatos `.audit/entregar-issue/` em workspace efemero quando vierem de connector remoto, preservando bytes exatos, e passar esses caminhos ao script. O agregador deve propagar automaticamente `evidence-provenance.json` certificado para o preflight de saturacao. Em reauditoria, materializar tambem os snapshots imutaveis anteriores de `audit-escape-closure.json` e `inherited-controls.json` e passa-los ao agregador via `--previous-closure` e `--previous-inherited-controls`; o `learning-closure.json` corrente deve ser resolvido do proprio certificado e encaminhado ao validador de reauditoria. Nao substituir esse portao por inspecao manual parcial dos mesmos artefatos.

Se a transferencia de bytes exatos entre connector e runtime falhar, **nao retornar `INCONCLUSIVA` antes de tentar o fallback connector-native** definido em `references/runtime-resource-resolution.md`. Quando o connector expuser commit/tree/blob imutaveis no SHA fixo e o objeto completo permanecer pesquisavel semanticamente, gerar `connector-preflight-manifest.json` com `target.repository/work_item_kind/work_item_number/pull_request/base_ref/head_ref` e `specification_snapshot.semantic.repository/issue`, alem das demais provas semanticas, e executar `<AUDIT_SKILL_ROOT>/scripts/check_connector_preflight.py`. Retornar `INCONCLUSIVA` por `audit-runtime-limitation` somente quando nem o preflight por bytes nem o fallback por snapshot Git imutavel puderem obter a evidencia obrigatoria. Isso nao e `delivery-not-ready` e nao gera finding contra a issue.
Em `certified-handoff`, CI remoto ainda `pending-no-run`, `queued`, `in_progress` ou `waiting` nunca e justificativa para ausencia do certificado: o produtor deve publicar o handoff antes de retornar depois do freeze. Com certificado valido e CI pendente, seguir para o preflight de gates e classificar o estado remoto separadamente; sem certificado, manter `delivery-not-ready` e usar `handoff-only` somente quando nenhuma evidencia de material drift existir. Se a CI exact-SHA do `material_head_sha` ja estiver terminal verde e a pendencia for apenas recertificacao/handoff, devolver tambem `next_phase=finalize-after-ci`; nao pedir nova rodada de `corrigir-ci` para o mesmo SHA material. Em `native-github-audit`, classificar CI diretamente pelo exact head remoto e nunca converter a ausencia de certificado em blocker.

Depois do certificado, antes do preflight proporcional, executar `scripts/check_normative_section_coverage.py` sobre o `specification-snapshot.json` e a `requirement-closure.json` certificados. Esse controle deve rederivar por parser proprio todos os itens de lista em secoes normativas (`Escopo/Scope`, `Requisitos/Requirements`, `Criterios de aceite/Acceptance criteria`, `Invariantes/Invariants`), ignorar secoes explicitamente nao normativas (`Fora de escopo/Out of scope`, `Referencias/References`) e bloquear qualquer item ausente da closure; nao reutilizar o extrator do produtor. Depois aplicar o preflight proporcional de `references/evidence-profiles-audit.md`. Em `standard`, executar `scripts/check_standard_evidence.py`; em `critical`, aplicar `references/delivery-saturation-preflight.md`; em `light`, nao exigir artefatos pesados ausentes por design. Todos esses artefatos sao indice, nao evidencia conclusiva.

Quando houver auditoria independente anterior reprovada para a mesma issue/PR/familia, aplicar primeiro `references/reaudit-readiness.md`. Para `targeted-remediation`, validar 1:1 o ledger e reexecutar apenas o caso literal/superficies diretamente impactadas; se houver `failed_gate`, exigir exact failed gate replay e, se ausente ou ainda vermelho, retornar imediatamente `REPROVADA` por `remediation-incomplete`/`same-finding-still-open`, reutilizando a rejeicao anterior e sem consumir provas caras. Para `systemic-remediation`, alem disso recuperar snapshots imutaveis anteriores de escape/controles, exigir lineage cumulativa, aprendizado e controles herdados. Nunca exigir a maquinaria sistemica para um finding targeted apenas porque ele escapou de aprovacao interna.

### 1. Identidade e fontes

1. Registrar repositorio, `issue_number` e `pull_request_number` separadamente, PR, branch, base, `work_item_start_sha`, `material_head_sha`, `published_handoff_head_sha`, merge previews aplicaveis, contexto, rotas, estados e viewports. Quando a entrada for `PR #N`, resolver a issue entregue pela relacao remota/closure/handoff antes do preflight; nunca definir `specification-snapshot.issue=N` apenas porque N e o numero da PR. Em schema v1, material e published head coincidem.
1.1. Manter tres deltas distintos: `pr_wide_diff=base_ref..published/material head` para contexto, `issue_local_diff=work_item_start_sha..material_head_sha` para atribuicao da entrega e `result_only_diff=material_head_sha..published_handoff_head_sha` para validar o handoff. Paths presentes apenas no `pr_wide_diff` sao `inherited-pr-delta`: contexto historico, nunca autoria automatica da issue corrente.
2. Consultar a fonte remota antes das validacoes em modo somente leitura; nao gerar novo run.
3. Em `independent`, refazer descoberta e criar manifesto proprio.
4. Em `controller-adversarial`, usar `source-manifest.json` apenas como indice, verificar completude e hashes, e rederivar requisitos independentemente. Um handoff compacto e esperado: nao exigir do produtor narrativas ou ataques que pertencem a rederivacao da auditoria fora do `evidence_profile` certificado.
5. Produzir `requirements-rederivation.json` e comparar com o snapshot.

### 2. Preflight de gates

1. Consultar runs/statuses existentes para o head e merge preview congelados antes de provas caras.
2. Obter `changed_files` antes de atribuir origem a falhas.
3. Classificar cada gate obrigatorio conforme `references/gate-preflight.md`, distinguindo `red-candidate-caused` de falha herdada/infra.
4. Para suites sequenciais, produzir matriz `declared/reached/passed`; teste posterior a um abort nao conta como executado.
5. Se houver gate obrigatorio `red-candidate-caused`, `missing` ou materialmente `not-reached` por responsabilidade demonstrada do candidato/entrega, entrar em `blocker-bounded`: o parecer ja nao pode aprovar a identidade atual, cancelar provas caras nao relacionadas e continuar somente a varredura barata necessaria para encontrar blockers adicionais, agrupar causa raiz, verificar fronteiras criticas tocadas pelo diff e reduzir a remediacao.
6. Se houver `audit-runtime-limitation`, nao entrar em `blocker-bounded`; encerrar como `INCONCLUSIVA`, registrar a limitacao e nao atribuir falha ao candidato/entrega.
7. Reutilizar job verde oficial na identidade exata apenas para o escopo que ele realmente executou; abrir harness/script para entender cobertura, nao para rerodar sem necessidade.

### 3. Mapear risco e implementacao

Comparar o `issue_local_diff` contra o material SHA para atribuir implementacao; usar `pr_wide_diff` apenas para contexto, integracao e deteccao de dependencia herdada. Expandir somente para entrypoints, consumidores, persistencia, autorizacao, integracoes, UI, legado, configuracao e documentacao relacionados aos requisitos ou familias de risco. Arquivo ausente do issue-local diff nao pode gerar finding `fora do escopo` apenas por aparecer no PR-wide diff; para virar finding, demonstrar dependencia/regressao causada pela entrega corrente. Rederivar independentemente as familias canonicas, incluindo `reference-liveness` quando IDs/snapshots atravessarem etapas e `temporal-destination` quando datas escolherem destino/vigencia.

Para entrada nao confiavel, mapear `transporte -> body parser -> helper -> validador -> hash/identidade -> parser -> persistencia` e toda transformacao da representacao bruta.

### 4. Evidencias

Para cada requisito comportamental, exigir evidencia positiva, controle negativo discriminante e regressao. Para alteracao apenas documental, usar busca de contradicoes, links, exemplos e comandos como controles apropriados.

Executar `documentacao-repositorio`, `design-interface` e `fluxos-conversacionais` somente quando aplicaveis e no mesmo modo de validade. Reutilizar atestacoes deterministicas apenas se SHA, comando, ambiente, hash de stdout/stderr e escopo coincidirem; nao repetir a suite oficial apenas para obter nova atestacao. Refazer somente a verificacao adversarial propria.

### 5. Validar e adversarializar

1. Respeitar o resultado do preflight. Se `blocker-bounded=true`, nao iniciar provas caras nao relacionadas; fazer apenas fechamento estatico barato, controles discriminantes necessarios e varredura de blockers correlatos. Se nao houver blocker determinante, seguir com revisao estatica do diff, fechamento por requisito e controles discriminantes baratos antes das provas caras.
2. Reutilizar gates oficiais atestados validos; executar novamente somente comando cujo escopo, ambiente ou artefato nao cubra a pergunta de auditoria.
3. Formular uma implementacao plausivel e errada que poderia passar no caminho feliz.
4. Em integracoes com provider, expandir helpers transitivos ate o SDK e comparar chamadas outbound reais com as tentativas contabilizadas pelo executor.
5. Executar dados discriminantes e registrar `coverage-matrix.json`.
6. Nao exigir a mesma suite duas vezes no mesmo fingerprint; executar uma vez os gates necessarios e uma passagem adversarial separada. Ao encontrar blocker, cancelar somente provas caras nao relacionadas e aplicar `references/blocker-harvest.md`: concluir a varredura estatica/controles baratos por todos os requisitos atomicos e familias materiais ainda abertas, inclusive de causas diferentes, para devolver o conjunto coeso de achados no mesmo ciclo.
7. Para `input-parser`, exigir inventario integral, matriz modo x invariante x familia de campo e cobertura `accepted_modes x consumed_fields x field_scope_placements`.
8. Testar valor bruto na fronteira publica, limite exato, excesso, padding, encoding, precedencia de erro e ausencia de efeitos.
9. Executar `IP-RAW-001`, `IP-MODE-001`, `IP-SCOPE-001`, `IP-INACTIVE-001` e `IP-EFFECT-001` quando aplicavel.
10. Quando qualquer regra normativa mudar — estado, rota, nome, arquitetura, autorizacao/role/permissao/capability, allow/deny, default/preset, seed/provisionamento/trigger, disponibilidade ou comportamento automatico — fazer varredura documental global por alegacoes antigas e novas. Linguagem normativa antiga sem marcador historico/compatibilidade e `documentation-claim-drift` bloqueante, mesmo com CI documental verde.
10.1. Quando calculos, respostas ou destinos de mutacao dependerem de periodo, `as-of`, data corrente, vigencia, semana, agenda ou projecao, atacar explicitamente passado, atual e futuro com cutoffs divergentes e campos temporais concorrentes. Quando houver periodo + data concreta, testar combinacao contraditoria; quando o contrato exigir destino futuro, `planned` no passado nao basta.
10.2. Quando referencias persistidas em uma etapa forem usadas em etapa posterior, atacar explicitamente referencia removida e referencia que manteve ID mas mudou elegibilidade/tenant/versao entre T1 e T3; validacao apenas na criacao nao comprova o gate definitivo.
11. Para fronteira publica persistente, enviar identificadores malformados por papeis irmaos e injetar erro bruto com marcadores sensiveis; verificar codigo, mensagem, shape, `correlationId` e ausencia de efeitos, nao apenas o status.
12. Para formulario com retry, idempotencia ou duplo envio, exigir execucao em navegador real do fluxo e da falha; regex no source e CI visual generico nao comprovam o requisito.

### 6. Classificar

Requisitos: `Implementado`, `Parcial`, `Nao implementado`, `Incorreto`, `Nao verificavel` ou `Fora do escopo`.

Achados: `Bloqueador`, `Alto`, `Medio` ou `Baixo`, sempre ligados a requisito e impacto. Todo finding deve emitir `remediation_mode=targeted-remediation|systemic-remediation`. Recomendacoes devem possuir ID estavel, `actionable=true|false` e `remediation_mode`; itens acionaveis devem ser consumidos pelo dono de remediacao correspondente a `delivery_origin`, sem troca automatica de controlador.

Parecer independente: `Aprovado`, `Aprovado com ressalvas`, `Inconclusivo` ou `Reprovado`. Usar `Inconclusivo` apenas para limitacao externa ao candidato/entrega.

No mesmo contexto: `Pre-auditoria com achados` ou `Pre-auditoria sem achados materiais`. Em controller, mapear favoravel para `internally-approved`, nunca para aprovacao operacional.

### 7. Entregar

1. Reconsultar identidade e estado remoto relevante em modo somente leitura; nao disparar ou aprovar workflow. Em result-only child, confirmar novamente parent + allowlist e que o material head certificado nao mudou.
2. Invalidar o parecer se head, base, merge preview ou input material mudar.
3. Produzir relatorio humano com o resultado na primeira linha, conforme `references/report-template.md`. Em `independent` + `REPROVADA`, gerar um novo `rejection_id` somente para rejeicao nova; em `same-finding-still-open`, recuperar e reutilizar o ID anterior, preservando finding ID e `rejection_lineage.mode=continuation`. Incluir tambem o estado dos gates e a matriz `declared/reached/passed` quando houver suite abortada ou `blocker-bounded`. Em `certified-handoff` de origem `direct-entregar-issue`, para `delivery-not-ready` causado apenas por certificado ausente/stale, incluir `return_control_to=entregar-issue`, `reason=handoff-not-produced|handoff-stale` e o `recovery_scope` derivado da identidade: `handoff-only` para material head estavel, `post-write-refreeze` com `requires_refreeze=true` para drift material, ou `fresh-handoff-required` para target estrangeiro; sem sugerir mudanca funcional. Quando a CI exact-SHA do material corrente ja estiver terminal verde, incluir ainda `next_phase=finalize-after-ci`. Em `INCONCLUSIVA` por runtime, emitir resultado estruturado com `status=blocked`, `findings=[]` para a causa de infraestrutura, `limitations` descrevendo `audit-runtime-limitation`, `skip_reason` objetivo, `requires_refreeze=false` salvo mudanca real de identidade, `input_fingerprint` e `reused=false`. Entregar todos os achados baratos identificados na rodada e todas as recomendacoes acionaveis em forma estruturada, com IDs unicos e `remediation_mode`, agrupaveis por causa mas sem omitir itens. Nao devolver um blocker por ciclo quando outro item independente e barato ja e observavel no mesmo SHA. Para cada `audit_escape`, produzir tambem `escape-control.json` conforme `references/audit-escape-feedback.md`, com caso literal, casos irmaos, controle reutilizavel e alvos de prevencao/deteccao. Usar `skip_reason` em qualquer no-op ou incompatibilidade contratual.
4. Em controller, produzir `controller-audit-report.json`, validar com `scripts/validate_controller_audit_result.py`, usar `mode=controller-adversarial` e `data.controller_disposition=internally-approved` quando favoravel. Nunca usar `approved-operationally`.
5. Em auditoria realmente independente, gerar e assinar `external-audit.json` somente depois da ultima reconsulta.
6. Quando o resultado humano for `REPROVADA` e existir remediacao executavel, encerrar o relatorio com no maximo uma opcao de continuidade, escolhida por `delivery_origin`: para `direct-entregar-issue`, usar `@Entregar Issue implementar pendencias desta auditoria`; para `standalone-unknown`, nao escolher controlador e apenas entregar os findings estruturados. `auditar-issue` permanece somente leitura e nunca corrige os achados. Aplicar a mesma regra de origem para `delivery-not-ready`, `delivery-not-saturated` e `remediation-incomplete`. Nao exibir opcao em `APROVADA`, `APROVADA COM RESSALVAS`, `APROVADA INTERNAMENTE` ou `INCONCLUSIVA`, nem quando a unica pendencia for infraestrutura exclusiva do auditor.

## Pacote neutro e escapes

Rejeitar pacote independente com conclusoes ou narrativa do implementador. Aceitar fontes, identidade, diff, codigo, testes, manifests e evidencias brutas.

Finding bloqueante independente no mesmo SHA aprovado internamente e `audit_escape`: registrar parecer anterior, exigir causa raiz, melhoria de Skill, teste preventivo e controle adversarial reutilizavel, e devolver `remediation-required`. O feedback reutilizavel deve descrever classe e controle genericos; identificadores concretos permanecem apenas na evidencia local do finding.

## Limitacoes

Marcar `Nao verificavel` quando ambiente, acesso, dados ou ferramenta indispensavel impedir prova. Nao preencher lacuna com suposicao. Nao fazer alteracao remota sem autorizacao.

## Versão contratual e portão de release

Emitir `contract_version=2026-08-20.3`. Em `controller-adversarial` ou `isolated-within-run`, exigir `approval_scope=internal-only`, `release_gate_satisfied=false` e `controller_disposition=internally-approved|remediation-required`. Somente `mode=independent` pode usar `approval_scope=independent-release-gate`.
