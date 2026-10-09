---
name: entregar-issue
description: "Conduzir a entrega ponta a ponta de issues em repositorios de software com um unico controlador, plano e estado: revisar readiness quando necessario, implementar codigo/testes/schemas/configuracao/documentacao, validar durante a edicao, aplicar higiene limitada ao diff, acionar especialidades condicionais, executar gates finais, congelar o candidato, acompanhar CI ate estado terminal por delegacao automatica a corrigir-ci, remediar falhas sem novo prompt e preparar auditoria independente. Usar quando o usuario informar uma issue, PR, branch ou pendencias e esperar continuidade autonoma. Nunca fazer merge nem declarar auditoria independente no mesmo contexto."
---

# Entregar Issue

## Objetivo

Produzir o menor candidato completo, rastreavel e localmente verde para uma issue. Possuir diretamente ciclo, identidade, contrato, plano, implementacao, validacoes, higiene limitada, gates, freeze, remediacao e handoff. Nao delegar etapas internas para Skills que recriem estado ou releiam o problema.

O objetivo operacional e concluir a entrega, sempre que nao houver impedimento real, em **uma unica invocacao de nivel superior**. Estado de CI `pending-no-run`, `queued`, `waiting` ou `in_progress` nunca e motivo para devolver o controle ao usuario: transferir a propriedade temporaria da CI para `corrigir-ci`, aguardar o terminal e retomar automaticamente a entrega.

A verificacao executada no mesmo contexto e interna. Somente `auditar-issue` em contexto realmente separado pode liberar aprovacao operacional.

## Modelo arquitetural

Usar uma unica camada de controle:

```text
entregar-issue
  -> revisar-issue                 somente se readiness falhar materialmente
  -> design-interface (guidance)   antes da primeira edicao de recorte visual
  -> gate de conflitos da PR       antes da primeira escrita e antes do freeze/CI
  -> implementacao interna         sempre que houver work item executavel
  -> documentacao interna por delta para alteracoes pequenas
  -> documentacao-repositorio      somente para impacto documental amplo
  -> design-interface (verify)     apos o diff visual e antes do freeze
  -> fluxos-conversacionais        somente para continuidade assincrona material
  -> gate adversarial interno
  -> corrigir-ci (CI subroutine)   apos publicacao do candidato, ate CI material terminal
  -> finalize-after-ci              retoma no controlador superior; nunca reentra em corrigir-ci por callback
  -> post-write-refreeze           somente se o SHA material mudou durante a subrotina
  -> selecionar audit transport    certified-handoff | native-github-audit
  -> result-only + handoff          somente em certified-handoff
  -> native audit-ready             somente em native-github-audit
  -> handoff/encaminhamento para auditar-issue independente
```

Este modelo e a lista completa de delegacoes: nunca invocar skill que nao apareca nele nem presumir que uma skill externa exista; etapa sem skill listada e executada internamente ou bloqueada como impedimento real.

## Carregamento progressivo

Ler sempre:

- `references/controller-execution-efficiency.md`;
- `references/composition-contract.md`;
- `references/implementation-workflow.md`;
- `references/delivery-target-binding.md`.

Ler somente quando aplicavel:

- transicao, recorrencia ou decisao: `references/controller-loop-protocol.md`;
- risco e perfil: `references/execution-profiles.md`;
- autorizacao ou persistencia: `references/persistence-authorization-gates.md`;
- resolvedor, executor, retry/fallback, adapter ou provider em runtime: `references/runtime-contract-gates.md`;
- impacto visual: `references/visual-gate.md`;
- input parser: `references/input-parser-gate.md` e `references/controller-input-parser-controls.md`;
- entrada nao confiavel: `references/implementation-untrusted-input-contract.md`;
- chamada a provider: `references/implementation-provider-call-governance.md`;
- PR aberta, publicacao, CI ou coleta remota: `references/remote-gate.md`, `references/pr-conflict-resolution.md`, `contracts/ci-ownership.json`, `contracts/github-actions-policy.md`, `references/finalize-after-ci.md`, `references/native-github-audit-contract.md` e, quando `audit_transport=certified-handoff`, `references/terminal-handoff.md`;
- correcao de handoff `result-only` em PR ja aberta ou decisao sobre PR substituta: `references/result-only-pr-recovery.md`;
- auditoria interna: `references/controller-audit-contract.md` e `references/controller-single-invocation.md`;
- controle negativo: `references/controller-adversarial-evidence.md`;
- codigo executavel tocado (criar, usar ou substituir simbolo, API, dependencia ou caminho): `references/codebase-grounding-gate.md`;
- arquivo de codigo novo ou ampliado: `references/code-growth-gate.md`;
- matriz requisito -> ataque: `references/requirement-attack-matrix.md`;
- referencias persistidas entre etapas: `references/reference-liveness-gate.md`;
- saturacao de familias de risco: `references/risk-saturation-gate.md`;
- controles herdados de auditorias anteriores: `references/cumulative-audit-controls.md`;
- evidencia/revisao/aprovacao que restringe efeitos, operacoes ou recursos posteriores: `references/evidence-effect-scope-gate.md`;
- catalogo reutilizavel de escapes: `references/audit-escape-pattern-catalog.md`;
- requisito estrutural, caminho canonico, precedencia, dependencia proibida, fonte unica ou compatibilidade semantica entre registros ligados: `references/structural-invariant-gate.md`;
- requisito ou controle quantitativo, benchmark, percentil, throughput, cardinalidade, custo ou outra medicao exact-SHA: `references/evidence-freshness-gate.md`;
- latencia, metricas por etapa, caminho critico, operacao nao essencial, lazy loading ou reducao de I/O: `references/performance-critical-path-gate.md`;
- deriva semantica documental por mudanca normativa, autorizacao/default/policy: `references/documentation-semantic-drift-gate.md`;
- melhoria de Skill: `references/controller-skill-improvement.md`;
- generalizacao de aprendizado apos rejeicao: `references/learning-generalization.md`;
- certificado de handoff independente: `references/handoff-certificate.md`;
- runtime `connector-only` ou recuperacao de certificado ausente/stale: `references/connector-only-handoff.md`;
- artefato JSON grande, limite de payload do connector ou publicacao por blobs: `references/large-artifact-transport.md`;
- finding independente contra candidato antes aprovado internamente: `references/audit-escape-closure.md`;
- calculo, relatorio, projecao ou destino de mutacao dependente de periodo/data/futuro: `references/temporal-consistency-gate.md`;
- registry/ativacao de gates: `contracts/gate-registry.json` e `references/gate-registry.md`;
- resposta final: `references/controller-result-template.md`.

Nao carregar referencias condicionais por antecipacao.

## Autoridade e invariantes

1. Possuir com exclusividade identidade, `controller_cycle`, plano, estado, work items, freeze, findings globais e decisao.
2. Calcular o plano uma vez por conjunto de inputs materiais; o `produced_diff` nao reabre a propria implementacao. Reabrir apenas por novo `work_item_fingerprint` ou mudanca material de fonte, contrato ou identidade.
3. Definir um unico `write_owner` por caminho. Skills condicionais nao recriam plano/estado nem disputam arquivos com o nucleo.
4. Nao enfraquecer requisito, risco, gate, severidade ou cobertura para concluir; requisitos estruturais sao de primeira classe.
5. Exigir por requisito comportamental evidencia positiva, controle negativo discriminante e regressao no nivel definido pelo `evidence_profile`. `standard` e o perfil padrao e usa `standard-evidence.json`; `critical` adiciona matriz de ataques, saturacao e controles herdados; `light` preserva somente closure/gates aplicaveis. Em `obligation_control_map`, permitir reutilizar o mesmo controle primario apenas entre obrigacoes semanticamente equivalentes cuja familia/superficie derivada aceite o mesmo ataque; obrigacoes heterogeneas continuam exigindo controles distintos. Clausula canonica que enumere cenarios de teste exige um `control_type=test` distinto por caso enumerado. Nenhum gate terminal de `requirement-closure.json` pode permanecer `pending`; `scope_reduction_review` e `pass_c` devem estar `passed`, e os demais fechamentos terminais devem estar `passed|not-applicable`.
6. Nao executar suite completa durante ajustes intermediarios; usar checks focados e um gate final agregado no material head.
7. Tratar GitHub Actions em `entregar-issue` como `ci_mode=delivery-snapshot` **somente ate a primeira observacao do material SHA**. Se o run nao estiver terminal verde, encerrar a propriedade `delivery-snapshot` e invocar `corrigir-ci` como **subrotina de CI** com `ci_mode=ci-remediation-loop`; a partir dessa transferencia, somente `corrigir-ci` observa/remedia o SHA material ate estado terminal. O controlador de nivel superior continua sendo `entregar-issue`. Nunca intercalar polling dos dois owners, nunca rerun/dispatch e nunca devolver CI pendente ao usuario quando a subrotina puder continuar.
7.1. `corrigir-ci` **nao pode invocar `entregar-issue` de volta** quando estiver em modo delegado. Ao atingir CI material verde, deve fechar sua propriedade e devolver exatamente um envelope validado com `return_control_to=entregar-issue`, `next_phase=finalize-after-ci`, `ci_owner_closed=true`, `material_head_sha`, `previous_frozen_sha`, `changed_files` e evidencias exact-SHA. O controlador retoma diretamente em `finalize-after-ci`.
7.2. Em `finalize-after-ci`, se `corrigir-ci` publicou novo material, ativar `material_dirty_since_freeze` e executar `post-write-refreeze`; se o SHA material permaneceu identico, reutilizar gates/freeze ainda validos. Em ambos os casos, resolver `audit_transport` no trusted anchor. Em `certified-handoff`, seguir sem redescoberta para pacote minimo do perfil -> simulacao pre-publicacao -> `result-only-child` -> leitura remota terminal -> `validate_terminal_handoff`. Em `native-github-audit`, nao criar `.audit`; revalidar identidade/CI exact-head e fechar `terminal_native_audit_ready=READY`.
7.3. Quando houver PR aberta, executar `references/pr-conflict-resolution.md` no preflight e novamente antes do gate final/primeira observacao de CI. `mergeable_state=dirty` ou merge probe Git conflitado exige resolucao na mesma PR antes de prosseguir. `blocked`, `behind` e `unstable` nao sao conflitos por si so. Toda resolucao publicada e escrita material: revalidar o novo head, refazer gates/freeze invalidados e nunca tratar a resolucao como `result-only-child`.
8. Nao chamar verificacao do mesmo contexto de independente. O estagio `internal-adversarial-gate` pode produzir no maximo `INTERNALLY_APPROVED`; auditoria independente fica fora do state graph desta Skill.
9. Publicar somente candidato material localmente verde. Em `certified-handoff`, qualquer escrita material apos freeze invalida o certificado e exige `post-write-refreeze`; somente o `result-only-child` allowlisted preserva a identidade material. Em `native-github-audit`, qualquer escrita material apos freeze invalida as evidencias exact-head e exige revalidacao equivalente, sem criar artefato `.audit`.
9.1. Tratar `recovery_scope` e `requires_refreeze` vindos de `auditar-issue` como **piso de recuperacao**, nunca como sugestao. `recovery_scope=post-write-refreeze` ou `requires_refreeze=true` proibe `handoff-only` ate existir novo freeze no head material corrente. O motivo generico `handoff-stale` nunca pode rebaixar esse piso. Antes de escolher fast path, combinar a orientacao da auditoria com identidade remota fresca via `scripts/classify_handoff_recovery.py`; prevalece sempre o escopo mais conservador.
9.2. Manter um latch conceitual `material_dirty_since_freeze`: qualquer commit/path material criado ou observado depois do freeze o ativa. O latch so pode ser limpo por gate final + novo freeze no SHA material resultante; publicar um filho `result-only` nao limpa material drift anterior. Nenhuma saida apta a auditoria e permitida enquanto o latch estiver ativo.
10. Quando `audit_transport=certified-handoff`, nenhum retorno apto a auditoria independente ocorre sem `handoff-ready.json` do material head final e `validate_terminal_handoff.py` favoravel usando **duas identidades distintas**: o `published_handoff_head_sha` produzido e um `current_head_sha` obtido por nova leitura remota depois da ultima escrita no repositorio. Se diferirem, bloquear; path material no head corrente exige `post-write-refreeze`. Aplicar `references/terminal-handoff.md` como barreira pos-escrita desse transporte e tratar essa etapa como **barreira universal pos-escrita**. Quando `audit_transport=native-github-audit`, substituir essa barreira pelo fechamento GitHub-native exact-SHA de `references/native-github-audit-contract.md`, sem `handoff-ready.json`, `result-only-child` ou `.audit/entregar-issue`.
10.1. Preservar a PR original em recuperacoes de handoff. Se o head corrente for apenas um `result-only-child` stale do mesmo material, preferir substituir esse filho na mesma branch conforme `references/result-only-pr-recovery.md`. Permitir force-update **somente** do ref entre filhos `result-only` irmaos do mesmo material, depois de prevalidacao local completa e releitura remota exata; nunca usar force para reescrever material. Abrir PR substituta apenas como ultimo recurso e aplicar `replacement_pr_budget=1` por invocacao; nunca abrir uma segunda substituta automaticamente por falha de pacote.
11. Evidencia quantitativa fecha requisito apenas com `subject_sha == material_head_sha` e `freshness_policy=exact-material-head`; mudanca material posterior torna a medicao stale. Controles ativos e escapes revalidados nao podem afirmar em `observed`/`literal_case.observed` que um SHA ancestral e o candidato/material head atual; narrativa contraditoria invalida o fechamento mesmo quando os campos estruturados apontam para o SHA correto.
12. Gates especializados permanecem nas referencias/registry: input parser, performance critical path, evidence-effect-scope, reference-liveness, temporal consistency, structural invariants e documentation semantic drift. Nao duplicar suas regras detalhadas no control plane.
13. Toda rejeicao independente deve possuir `rejection_id` estavel, aparecer explicitamente em `audit-escape-closure.json` e produzir `learning-closure.json`; `implementation-only` dispensa apenas promocao global, nunca o fechamento do escape. Nunca criar regra permanente acoplada a repositorio, produto, issue, PR, branch, SHA ou path concreto.
14. Antes de adicionar novo invariant global, tentar representa-lo em risk family/gate existente conforme `references/gate-registry.md`.
15. Antes de reutilizar qualquer `.audit/entregar-issue`, provar o vinculo semantico com o alvo atual. Quando houver `base_sha`, comparar os artefatos de identidade do head contra os mesmos paths no commit base exato; igualdade byte-a-byte + subject estrangeiro deve produzir `inherited-base-artifact`. Em connector-only, materializar os mesmos paths do base SHA e comparar bytes. `inherited-base-artifact`, `foreign-target`, `partial-current-target` ou `unbound-or-invalid` implicam `reuse_allowed=false`, reconstrucao dos artefatos correntes e novo handoff; certificado herdado de outro alvo nunca ativa `handoff-only`. Artefato estrangeiro alterado no head continua `foreign-target`. Reclassificar `artifact_reuse` sempre que `base_ref`, branch ou PR forem atualizados e novamente depois de reconstruir/publicar o pacote, para que a decisao final nunca dependa de uma classificacao feita antes da identidade terminal existir.
16. Nao fazer merge, fechar issue, alterar producao, dados, segredos ou credenciais sem autorizacao explicita.
17. Tratar criacao de nova tela, pagina, rota navegavel, dashboard ou composicao visual operada pelo usuario como impacto visual material por definicao. Para esse recorte, `design-interface` nao e opcional: executar `guidance` antes da primeira edicao visual e `internal-verification` depois da implementacao, antes do gate final. Ausencia de requisito estetico explicito nao torna design `not-applicable`.

## Estado e contratos

Quando `audit_transport=certified-handoff`, manter em `.audit/entregar-issue/`:

- `controller-context.json`;
- `source-manifest.json`;
- `specification-snapshot.json`;
- `requirement-closure.json`;
- `risk-profile.json`;
- `applicability-ledger.json`;
- `execution-plan.json`;
- `documentation-impact.json`;
- `requirement-attack-matrix.json`;
- `evidence-provenance.json` quando houver evidencia quantitativa/exact-SHA;
- `risk-saturation.json`;
- `inherited-controls.json`;
- `audit-escape-pattern-catalog.json`;
- `learning-closure.json` quando houver rejeicao independente;
- `handoff-ready.json`;
- atestacoes, freeze, historico e handoff.

Quando `audit_transport=native-github-audit`, manter estado equivalente apenas no runtime/workspace efemero do controlador e nas evidencias GitHub-native exigidas pelo contrato canonico; nao criar nem publicar `.audit/entregar-issue/` no repositorio.

Artefatos JSON canonicos do modo `certified-handoff` podem ser fisicamente `plain-json` ou `base64-shards-v1`. O conteudo logico e a autoridade: todos os leitores devem usar `scripts/audit_artifact_io.py`; nunca reduzir cobertura para caber no transporte.

Inicializar contexto uma vez por `scripts/controller_cli.py init-context`; o comando deve registrar `artifact_reuse` classificando qualquer pacote `.audit/entregar-issue` existente antes de permitir reuso. Atualizar identidade, fontes, baseline, workflows e metricas em uma unica chamada `refresh-context` quando possivel; `refresh-context` deve reclassificar o pacote contra `repository/base_ref/branch/PR` atuais mesmo quando nenhum outro campo material mudou. Depois de reconstruir/publicar um pacote que antes era `foreign-target`, executar `refresh-context` novamente e exigir `artifact_reuse.status=current-target` no modo com contexto local, ou a classificacao equivalente via `delivery_target_binding.py` em `connector-only`. Registrar `planning_runs`, `subskill_calls`, `focused_checks`, `full_suites`, `remote_collections`, `material_commits`, `handoff_commits` e reuso; timestamps e telemetria nao invalidam etapas. Gerar KPIs com `scripts/report_controller_efficiency.py` quando avaliar performance do controlador.

Usar `controller_mode=delivery-single-invocation`.

## Fluxo deterministico

### 0. Preflight unico

1. Resolver repositorio, issue, branch, PR, base, instrucoes locais e permissoes; essa resolucao e a fonte de verdade do alvo, nunca os arquivos `.audit` herdados.
1.1. Antes de executar qualquer script desta Skill, rodar `scripts/runtime_resource_preflight.py`; `FAIL` (script referenciado ausente no pacote) e impedimento real de runtime, nunca motivo para reescrever ou presumir o comportamento do script.
2. Classificar uma unica vez a capacidade de execucao como `local-git`, `connector-only` ou `artifact-bundle`. Se checkout/dependencias nao estiverem utilizaveis, nao repetir clone, instalacao ou tentativa equivalente sem evidencia nova de que o impedimento mudou.
3. Antes de reutilizar qualquer artefato existente, aplicar `references/delivery-target-binding.md`. Em checkout local, `controller_cli.py init-context` classifica automaticamente `.audit/entregar-issue` e, quando `base_sha` estiver disponivel, prova origem herdada comparando bytes via Git contra esse SHA exato. Em `connector-only`, materializar `handoff-ready.json` e `specification-snapshot.json` do head remoto quando existirem, materializar os mesmos paths do base SHA em diretorio separado e executar `scripts/delivery_target_binding.py --base-audit-dir <base>`.
4. Se o estado for `inherited-base-artifact`, `foreign-target`, `partial-current-target` ou `unbound-or-invalid`, manter `reuse_allowed=false`, ignorar o pacote anterior como evidencia e reconstruir os artefatos canonicos da entrega atual. `inherited-base-artifact` e historico neutro da base, nao finding do produto e nao evidencia de que a entrega atual produziu handoff. Isso nao bloqueia a implementacao e nao autoriza apagar historico.
5. Criar contexto, manifesto de fontes, baseline, ledger e inventario de workflows uma unica vez.
6. Capturar `observed_head_before_work` como `work_item_start_sha` imutavel antes da primeira escrita material. Nunca substituir esse SHA pela base da PR nem pelo head corrente depois da implementacao. Reutilizar descoberta somente quando os fingerprints **e** `artifact_reuse.status=current-target` permitirem; `fresh` significa trabalho novo, nao reuso.
6.1. Manter identidade canonica separada: `issue_number=controller.issue` e `pull_request_number=controller.pull_request`. Quando a entrada vier como PR, resolver a issue entregue pela relacao remota/closure/handoff; nunca usar o numero da PR como `specification-snapshot.issue`.
6.2. Se houver PR aberta, executar o primeiro `conflict_gate` de `references/pr-conflict-resolution.md` contra `head_sha` e `base_sha` remotos frescos **antes da primeira escrita material**. Se houver conflito real, resolver na mesma PR, validar a integracao e refrescar identidade/contexto antes de capturar o baseline efetivo da implementacao desta invocacao. Nao confundir `blocked`/`behind`/`unstable` com conflito.
6.3. Se a resolucao de conflitos gerar novo head antes da implementacao desta invocacao, usar esse head integrado como `observed_head_before_work`; se o conflito surgir depois de ja existir escrita material, preservar a rastreabilidade existente, marcar `material_dirty_since_freeze` e tratar a resolucao como nova escrita material que invalida descendentes.
7. Nao perguntar novamente por informacao ja disponivel na conversa, repositorio, issue ou auditoria imediatamente anterior.

### 1. Readiness e contrato

1. Derivar requisitos testaveis, criterios, caminhos e riscos. Separar explicitamente comportamento de invariantes estruturais: `must_not`, `must_reuse`, `must_be_single_source`, `must_not_depend_on`, `precedence_invariants` e `forbidden_implementation` quando presentes.
2. Invocar `revisar-issue` somente quando faltar decisao material capaz de produzir implementacoes divergentes.
3. Construir snapshot e fechamento uma vez, com `scripts/build_specification_snapshot.py` conforme `references/specification-snapshot.md` e `scripts/init_requirement_closure.py` conforme `references/requirement-closure-gate.md`. Recalcular somente por mudanca material.
4. Produzir `requirement-closure.json` com prova esperada para cada requisito antes de editar e validar que nenhum candidato extraido das fontes canonicas desapareceu do fechamento. Preservar em cada obrigacao `source_id`, `source_sha256`, `source_line`, `source_text` e `flags` exatamente como no snapshot; chave/candidate count sem o texto canonico nao e fechamento valido. Tratar todo item de lista Markdown sob secoes normativas como `Escopo/Scope`, `Requisitos/Requirements`, `Criterios de aceite/Acceptance criteria` e `Invariantes/Invariants` como candidato obrigatorio mesmo quando o verbo inicial nao estiver no vocabulario heuristico; excluir explicitamente secoes `Fora de escopo/Out of scope` e `Referencias/References`. O controle deve possuir teste transferivel que prove captura de verbos antes desconhecidos e falha de cobertura quando um item normativo for removido da closure.
5. Para cada requisito material, formular antes da implementacao uma `plausible_wrong_implementation` que passaria no caminho feliz e derivar a familia de ataque e todas as `risk_surfaces` tecnicamente acessiveis correspondentes. Se varias obrigacoes forem ligadas ao mesmo requisito, manter a atomizacao de verificacao por obrigacao; nao usar a agregacao do requisito para reduzir numero de ataques.
6. Inicializar `requirement-attack-matrix.json`; consultar `audit-escape-pattern-catalog.json` e ativar padroes anteriores cujos sinais aparecam no contrato atual, carregando `required_attack_dimensions` como piso de cobertura e ampliando-o quando a arquitetura atual expuser novas superficies. Nao aceitar a matriz como autoridade sobre a propria aplicabilidade: rederivar familias/superficies de `source_texts`, inclusive `idempotency:duplicate-processing` para retry/callback/replay/reprocessamento, `authorization:session-target-binding` quando o alvo vem da sessao autenticada, `public-boundary:request-target-override` quando body/request nao pode escolher o alvo, `tenant-isolation:tenant-scope-isolation` quando tenant/perfil/organizacao/workspace deve permanecer isolado, segregado ou sem vazamento, `structural-contract:canonical-source-consistency` para catalogo/definicao canonica compartilhada, `structural-contract:specified-test-matrix` quando a fonte enumera casos que os testes devem cobrir, `structural-contract:semantic-identity-propagation` quando o contrato contiver dois ou mais campos de identidade vizinhos e `structural-contract:relational-semantic-integrity` quando houver fonte unica/canonica, proibicao de mistura/conversao implicita ou uma dimensao material repetida em registros ligados. `authorization` nao satisfaz nem substitui `tenant-isolation`: quando ambas forem exigidas pela mesma clausula, manter as duas familias e controles discriminantes separados. Inferir `concurrency-atomicity` apenas de sinais concretos de concorrencia/serializacao/lock; a flag ampla `atomicity` ou a palavra `canônico` nao bastam. Nao inferir reporting temporal de palavras soltas como `complete/completa`: exigir contexto de cobertura, disponibilidade, janela, retencao ou relatorio.
7. Se o contrato contiver `continua valido/acessivel`, `revalidar`, `apos aprovacao`, `no momento de release/execucao` ou equivalente, ativar `reference-liveness`. Se contiver `futuro`, `passado`, `semana`, `periodo`, `vigencia` ou data de destino, ativar o gate temporal mesmo sem calculo. Se uma consulta/relatorio declarar cobertura, qualidade, `availableFrom/availableTo`, `complete|partial`, janela disponivel ou retencao, ativar `temporal-consistency:reporting-availability-window` e exigir `TEMP-COVERAGE-001`; teste de purge/retencao isolado nao comprova o rotulo de cobertura. Quando a especificacao definir tiers retidos em granularidades distintas, gerar `coverage_contract` a partir de **todas** as obrigacoes canonicas, inclusive quando retencao e reporting estiverem em requisitos diferentes; classificar cada tier `used|not-used`, exigir controle dedicado por tier usado e probe de borda nao alinhada para impedir que um teste mensal sature cobertura diaria ou vice-versa.
8. Se houver latencia, desempenho, percentis, `*_ms`, instrumentacao por etapa, benchmark, caminho critico ou remocao de operacao nao essencial, ativar `references/performance-critical-path-gate.md`; o planner deve inferir `performance` e incluir o gate declarativo `performance-critical-path`. Derivar `stage-attribution-completeness` quando houver metricas por etapa, `critical-path-necessity` quando houver otimizacao/reducao de trabalho e `benchmark-path-fidelity` quando houver benchmark/baseline/candidato ou alegacao de mesmo caminho produtivo. Inicializar e preencher `performance_contract` na matriz com entrypoint produtivo, boundary terminal, inventario exact-head de operacoes, matriz de branches e cobertura/ponte do harness. Para percentil, custo, contagem, cardinalidade, media movel, projecao, percentual/ratio ou outra metrica observada, tratar `evidence-provenance.json` exact-material-head como obrigatorio mesmo que a matriz omita `evidence_kind`.
9. Se o contrato disser que uma operacao, restricao, recurso ou mutacao deve estar relacionada a evidencia, escopo revisado/aprovado ou decisao anterior, ativar `references/evidence-effect-scope-gate.md`, declarar `authorization:evidence-effect-scope` e incluir explicitamente branches emergenciais/override/excecao entre os casos discriminantes quando existirem.
10. Se o contrato ou a implementacao pretendida alterar regra normativa de autorizacao, permissao, default, provisionamento, disponibilidade, rota, estado ou comportamento automatico, ativar `references/documentation-semantic-drift-gate.md`; registrar desde o readiness os termos/claims antigos e novos que deverao ser reconciliados no SHA final.

### 2. Plano unico

Executar `scripts/plan_execution.py` uma vez com contexto, requisitos, caminhos, plano anterior e work items; o formato do plano e `schemas/execution-plan.schema.json`.

O plano deve:

- separar fingerprints de fontes, baseline, workflows, politica, permissoes e identidade;
- detectar impacto visual a partir do contrato **e** dos caminhos planejados, sem depender do diff ja produzido; qualquer nova pagina/tela/rota navegavel ou arquivo de UI planejado cria duas chamadas de `design-interface`: `guidance` em `pre-implementation` e `internal-verification` em `post-implementation`;
- manter `implementation_scope` separado de `produced_diff`;
- atribuir `write_owner` unico por caminho;
- produzir `run`, `reuse-candidate`, `not-applicable` ou `conditional` para especialidades;
- incluir `work_item_fingerprint` em toda remediacao;
- ignorar timestamps e telemetria para invalidacao.

O diff da propria implementacao atualiza evidencia e gates descendentes, mas nao transforma automaticamente a implementacao em `run` novamente.

### 3. Implementar internamente

Seguir `references/implementation-workflow.md`.

0. Quando o plano marcar `design-interface` em `pre-implementation`, executar primeiro a chamada em `mode=guidance`, passando requisitos visuais, rotas/cenarios, caminhos planejados, design system relacionado e `input_fingerprint`. Nao iniciar a edicao visual enquanto essa orientacao nao tiver definido hierarquia, estados, interacao, estrategia responsiva, acessibilidade e componentes/tokens a reutilizar. A implementacao continua pertencendo ao `write_owner` definido pelo controlador.
1. Antes da primeira edicao material de cada work item, converter `plausible_wrong_implementation + risk_surfaces` da `requirement-attack-matrix.json` em controles focados: caminho positivo, controle negativo primario por `risk_family + surface` e regressao. Quando automatizavel, provar que o controle distingue a implementacao errada plausivel antes de considerar a superficie coberta; nao deixar o desenho do ataque para o gate final. Para `evidence-effect-scope`, usar fonte e efeito deliberadamente divergentes e provar rejeicao sem efeitos antes de aceitar o caminho coincidente. Para `semantic-identity-propagation`, usar valores deliberadamente distintos para os campos vizinhos e observar o boundary de mapeamento/persistencia em cada produtor material; mockar o adaptador sob teste nao fecha a superficie. Para `relational-semantic-integrity`, executar `REL-SEM-001`: usar valores incompatíveis em registros ligados, atravessar `create`/`update` ou produtor equivalente e provar rejeicao/transformacao explicita antes de observar aggregate/consumer; fixture coerente no consumidor nao fecha a superficie.
2. Para trabalho de desempenho/latencia, inventariar o caminho produtivo **a partir do entrypoint real usado pela aplicacao**, incluindo wrappers, lookups e resolucoes anteriores ao sub-handler: I/O e operacoes diretas/transitivas/paralelas, etapa semantica, metrica que as cobre e necessidade por ramo. Preencher `performance_contract.operations` e fazer cada `optimized_branch` classificar todas as operacoes before-terminal. Executar `PERF-STAGE-ATTR-001` e/ou `PERF-CRITICAL-WORK-001`; o primeiro deve provar atribuicao completa por etapa e o segundo zero invocacoes no ramo onde o trabalho e desnecessario. Quando houver benchmark, executar tambem `PERF-BENCH-PATH-001`: o harness deve iniciar no mesmo entrypoint produtivo ou declarar cada operacao bridged com evidencia exact-head; `sleep`, fixture ou valor ja resolvido nao contam como equivalencia silenciosa.
3. Alterar o menor conjunto coeso que entregue o comportamento ponta a ponta e executar validacoes focadas durante a edicao.
4. Fechar cada requisito com arquivos, comportamento, teste positivo, `risk_surfaces`, controle negativo primario por superficie, casos irmaos discriminantes e regressao e registrar tudo em `requirement-attack-matrix.json`. Para requisito com varias obrigacoes, preencher `obligation_control_map` cobrindo todas as obrigacoes com controles primarios distintos; para clausula que enumera cobertura de testes, preencher `test_coverage_contract` sem omitir nenhum caso e ligar cada caso a um controle `test` distinto. Para requisito estrutural, executar tambem o gate de `references/structural-invariant-gate.md`; resultado publico correto nao substitui a prova da forma de implementacao exigida.
5. Para referencias usadas em etapa posterior, executar `REF-LIVE-001` e caso irmao aplicavel; para destinos temporais, executar os controles `TEMP-PERIOD-001`/`TEMP-DEST-001` quando aplicaveis. Para reporting com retencao, preencher `coverage_contract.retained_tiers`; cada tier usado deve possuir controle de cobertura proprio no entrypoint real. Em granularidade de bucket, usar cutoff fora da borda e provar que purge, query e `availableFrom` normalizam para a mesma borda/timezone; requisitar exatamente desde a borda deve retornar `complete`.
6. Quando `produced_diff` estabilizar, executar uma unica reconciliacao pos-diff das superficies materiais reveladas por entrypoints, consumidores, runtime graph (`scripts/map_runtime_consumers.py`; `coverage.complete=false` mantem a superficie `UNKNOWN`), persistencia, fronteiras e dependencias tocadas. Cruzar somente o delta de superficies com a matriz existente; superficie nova reabre o mesmo work item e recebe controle focado antes de sair da implementacao, sem recalcular o plano inteiro.
7. Descobrir todos os erros baratos relacionados antes de devolver a rodada; depois do primeiro finding, percorrer tambem requisitos/familias ainda sem controle discriminante para colher blockers independentes baratos no mesmo ciclo.
8. Atualizar documentacao simples por delta no mesmo recorte. Quando houver mudanca semantica normativa, executar `DOC-SEMANTIC-DRIFT-001`: buscar fora do diff, classificar todas as alegacoes antigas relevantes e reabrir o work item se surgir fonte canonica concorrente.
9. Permanecer em correcao enquanto houver falha executavel, requisito sem prova, familia de risco material nao saturada, superficie pos-diff sem controle ou controle herdado nao executado. O gate final confirma cobertura; nao deve ser a primeira etapa a descobrir ataque barato derivavel do contrato ou do diff.

### 4. Higiene interna limitada

Aplicar `references/hygiene.md` somente depois da implementacao funcional e antes do gate final.

Quando o plano exigir `codebase-grounding`, fechar `codebase-grounding.json` nesta etapa e executar `scripts/validate_codebase_grounding.py` no gate final sobre o SHA congelado. Quando exigir `code-growth`, executar `scripts/check_code_growth.py` no mesmo ponto. Resultado diferente de `READY` em qualquer um bloqueia o freeze.

- Inspecionar apenas arquivos tocados e consumidores diretos.
- Corrigir somente duplicidade, codigo morto, dependencia sem uso ou complexidade introduzida/agravada pela entrega.
- Aceitar `no-change` sem chamada externa.
- Nao iniciar refatoracao ampla, reformatacao global ou melhoria opcional.
- Reexecutar apenas checks invalidados pelo safe-fix.

### 5. Especialidades condicionais

Seguir `references/domain-delegation.md`.

- `design-interface`: para qualquer impacto visual material, executar **duas fases com fingerprints distintos**: `mode=guidance`, `phase=pre-implementation`, antes da primeira edicao visual; e `mode=internal-verification`, `phase=post-implementation`, depois que o diff estabilizar e antes do gate final. Nova tela/pagina/rota navegavel e sempre impacto visual material, mesmo quando a issue nao prescreve estilo. A verificacao deve cobrir ao menos hierarquia/acao primaria, estados aplicaveis, responsividade, teclado/foco/acessibilidade e aderencia ao design system real.
- `fluxos-conversacionais`: acionar uma vez por fingerprint quando houver continuidade persistida, callbacks, filas, retry, idempotencia, expiracao, cancelamento ou concorrencia.
- `documentacao-repositorio`: acionar somente para reorganizacao ampla, ADR/runbook/API, contradicao global ou impacto documental que exceda o delta local.

Canonicalizar pedidos por `skill + requirements + paths + input_fingerprint`. Para `reuse-candidate`, verificar hash, identidade, resultado e artefato antes de pular a chamada.

### 6. Gate final e freeze

0. Quando houver PR, reconsultar base/head e executar novamente `references/pr-conflict-resolution.md`. Se a base avancou e criou conflito, resolver primeiro na mesma PR, considerar o head resultante materialmente novo e somente entao iniciar/reiniciar o gate final. Nenhum freeze e valido sobre uma PR `dirty`.
1. Executar uma unica vez o conjunto final exigido pelo perfil com `scripts/run_attested_gate.py`.
2. Exigir working tree limpa, comandos, cwd, SHA, tempos, exit code e hashes.
3. Exigir, quando houver impacto visual material, resultado valido de `design-interface` em `internal-verification` para o SHA/diff corrente; guidance pre-implementacao sozinho nao fecha o dominio visual. Executar o estagio `internal-adversarial-gate` proporcional ao risco e controles especializados aplicaveis. Para requisitos estruturais/canonicos, executar `CANON-DIVERGENCE-001` quando houver caminho especializado e canonico e `REL-SEM-001` quando houver dimensao semantica repetida em registros ligados; para qualquer semantica temporal de calculo ou destino, aplicar `references/temporal-consistency-gate.md`; para reporting retido, validar no SHA final o `coverage_contract`, um controle dedicado por tier usado e a igualdade entre borda normalizada de purge, query e payload de cobertura; para referencias entre etapas, aplicar `references/reference-liveness-gate.md`; para evidencia/revisao/aprovacao que restrinja efeitos posteriores, aplicar `references/evidence-effect-scope-gate.md` e executar `AUTH-EFFECT-SCOPE-001` inclusive em branches de excecao; para latencia/desempenho, reaplicar sobre o SHA final o `performance_contract` e os controles `PERF-STAGE-ATTR-001`, `PERF-CRITICAL-WORK-001` e, quando houver benchmark, `PERF-BENCH-PATH-001`; validar que nenhuma operacao before-terminal ficou fora de metrica, branch decision ou cobertura/ponte do harness; para remediacao de `audit_escape`, executar todos os controles herdados e casos irmaos de `references/audit-escape-closure.md`.
4. Executar `validate_specification_coverage.py`, `validate_requirement_attack_matrix.py`, `validate_risk_saturation.py --requirement-closure ... --inherited-controls ...` e `validate_inherited_controls.py --requirement-closure ...` sobre o SHA final. `validate_requirement_attack_matrix.py` deve bloquear requisito agregado sem `obligation_control_map` completo, reutilizacao do mesmo controle primario para obrigacoes distintas, controle incompatível com a familia/superficie rederivada da obrigacao e clausula explicita de cobertura de testes sem `test_coverage_contract` completo. `validate_specification_coverage.py` e `validate_handoff_readiness.py` devem reprovar qualquer fechamento terminal `pending`; `validate_inherited_controls.py` e `validate_audit_escape_lineage.py --head-sha <material>` devem reprovar narrativa que apresente SHA ancestral como atual/exact-head. Em remediacao apos rejeicao independente, obter do handoff anterior os snapshots de `inherited-controls.json` e `audit-escape-closure.json`; passar `--previous-inherited-controls` ao validador de controles, executar `validate_audit_escape_lineage.py --previous-closure ... --require-previous` e cruzar obrigatoriamente `learning-closure.json` com o ledger via `validate_independent_rejection_closure.py --learning-closure ... --closure ...`. O gate de saturacao deve rederivar familias da especificacao, nao apenas da matriz, e tratar controles herdados ativos como prova de materialidade ate supersessao/aposentadoria validada. `documentation_consistency.status=passed` tambem torna `documentation` material e exige superficie documental atacada. Quando a especificacao ou um controle for quantitativo/exact-SHA, executar tambem `validate_evidence_freshness.py` e passar `evidence-provenance.json` ao validador da matriz. Para controles herdados, exigir `subject_sha` atual, `control_type`, `procedure`, `expected`, `observed`, evidencia hasheada e, quando aplicavel, vinculo ao ataque corrente; `observed` nao pode afirmar SHA ancestral como candidato/material/exact-head atual. CI verde ou ausencia de diff nao substituem reexecucao discriminante. A matriz de risco deve explicitar inclusive familias `not-applicable` e, para cada familia aplicavel, todas as superficies materiais com controles correspondentes.
   Antes de liberar o handoff publicado, se o `result-only-child` tocar `inherited-controls.json` ou `audit-escape-closure.json`, comparar os artefatos publicados tambem contra as versoes do **material parent**. A comparacao historica externa nao substitui essa prova local de monotonicidade do filho de resultados.
5. Fazer blocker-harvest final barato: varrer todos os requisitos atômicos e familias canonicas ainda sem ataque, mesmo que um blocker anterior ja torne o candidato reprovavel. Quando houver mudanca normativa, executar `DOC-SEMANTIC-DRIFT-001` no SHA final e bloquear se `documentation_consistency` nao tiver termos antigos/novos, busca fora do diff, inventario completo ou se `documentation:canonical-claims` estiver ausente da matriz/saturacao.
6. Congelar o **material head SHA** somente depois de requisitos, documentacao, especialidades, controles de escape, controles herdados, matriz de ataques, saturacao e gates estarem favoraveis. O commit posterior que contenha somente o pacote de handoff autorizado nao muda essa identidade material.
7. Se houver finding, criar work items agrupados por causa e invalidar apenas descendentes afetados.
8. Antes do freeze, rejeitar toda evidencia `quantitative` cujo `subject_sha` seja diferente do material head final. Nao aceitar equivalencia estrutural do delta como substituto de reexecucao da medicao.

### 7. Remediacao eficiente

1. Agrupar findings relacionados pela mesma causa raiz.
2. Quando a entrada vier de auditoria estruturada imediatamente anterior, validar a identidade uma vez e converter findings com ID, severidade, causa e remediacao em work items sem redescobrir requisitos nao afetados. Preservar tambem `reason`, `recovery_scope`, `requires_refreeze`, `material_head_sha`/`certified_material_head_sha` e `current_head_sha` informados pela auditoria. Antes de qualquer fast path de handoff, executar `scripts/classify_handoff_recovery.py` com leitura remota fresca; `post-write-refreeze`/`requires_refreeze=true` e um piso que nao pode ser rebaixado por `handoff-stale` ou pela ausencia de finding funcional.
3. Executar todos os checks baratos que possam revelar erros irmaos antes de iniciar nova edicao.
4. Nao repetir comando ou mudanca sem nova hipotese, input alterado ou evidencia adicional.
5. Incrementar ciclo somente depois de verificacao que exija nova implementacao.
6. Se o mesmo fingerprint reaparecer, parar tentativa cega e executar causa raiz.
7. Antes de parecer interno favoravel, executar novamente o gate final completo sobre o SHA final. Quando a auditoria anterior registrar `failed_gate.deterministic=true`, executar antes do freeze o **mesmo comando** de `failed_gate.command` no novo material head. Nao aceitar `node --check`, teste unitario, lint parcial ou comando semanticamente vizinho como substituto do gate que falhou. Registrar em `audit-remediation.json` `closure_kind=deterministic-gate-replay`, comando original, comando reexecutado, `subject_sha`, `exit_code=0` e hash da evidencia; `scripts/validate_audit_remediation.py` deve passar antes de criar o handoff.
7.1. Quando checkout local executavel estiver disponivel, alinhar o gate final deterministico com a sequencia dos checks obrigatorios do workflow corrente para os arquivos/superficies afetados (por exemplo formatacao -> lint -> typecheck -> testes -> build quando declarados). Um passo anterior vermelho significa que passos posteriores estao `not-reached`, nunca verdes por inferencia. Em `connector-only`, nao inventar paridade local: exigir evidencia remota existente para o gate especifico antes de marcar o finding como fixed.
8. Se uma auditoria independente encontrou finding bloqueante em candidato antes aprovado internamente, classificar primeiro `targeted-remediation|systemic-remediation`. Para targeted, fechar exatamente o caso literal e superficies diretamente impactadas; para systemic, fechar a **classe do escape** com casos irmaos, teste preventivo, controle adversarial reutilizavel e fortalecimento de prevencao + deteccao. Nao promover um defeito local a sistemico apenas porque houve audit escape.
9. Produzir `audit-escape-closure.json` cumulativo para cada escape e exigir `status=passed` mais `required_attack_dimensions` cobertas no novo SHA; preservar todos os `escape_id` do fechamento anterior e bloquear qualquer remocao silenciosa; incorporar cada `escape_class`, suas superficies/dimensoes obrigatorias em `audit-escape-pattern-catalog.json` e seus controles em `inherited-controls.json` antes de novo freeze/handoff.
10. Reexecutar cumulativamente no novo SHA todos os controles herdados ainda aplicaveis de auditorias anteriores, nao apenas os findings da ultima auditoria. Um controle nao pode ser aposentado como `not-applicable` enquanto a `requirement-closure` canonica ainda exigir sua `risk_family`/superficie; nesse caso somente `superseded` por controle ativo equivalente pode remover o ID anterior. Comparar obrigatoriamente com o `inherited-controls.json` do handoff anterior: cada ID anterior deve continuar ativo ou receber em `retired_controls` uma disposicao explicita `superseded|not-applicable` com evidencia exact-head; `superseded` exige substituto ativo. Preservar tambem todos os `source_audits`. Registrar `subject_sha`, procedimento, esperado, observado e hash da evidencia; nao promover controle por inferencia de CI/diff.
11. Para toda **nova** rejeicao independente, consumir o `rejection_id` emitido pela auditoria e produzir `learning-closure.json` com `source_event.kind=independent-rejection` e o mesmo `source_event.rejection_id`; anexar a rejeicao ao fechamento aplicavel. Quando uma reauditoria declarar `same-finding-still-open` e reutilizar explicitamente o `rejection_id` anterior, tratar como continuacao do mesmo evento: atualizar a remediacao existente sem criar novo learning event, novo escape ou controle herdado duplicado. Nunca inventar ou rederivar identificador para fazer o handoff passar. Classificar `implementation-only` ou `systemic-escape`; somente o sistemico exige promocao generica com casos de transferencia e mudancas permanentes de prevencao/deteccao.
12. Quando houver alteracao permanente de Skill, executar `scripts/validate_skill_genericity.py --skill-root .`; teste numerado por issue, regra historica derivada de issue, caminho absoluto de host, identificador concreto em prosa ou host externo concreto bloqueiam o ciclo. Identificador dentro de trecho ou bloco de codigo e exemplo delimitado, nao prosa normativa, e dominio reservado de exemplo e o mecanismo correto para host ilustrativo.
13. Depois da remediacao, repetir a saturacao completa das familias afetadas e a colheita barata de blockers antes de consumir outra auditoria independente; **nao reenviar para nova auditoria** enquanto a classe de escape ou qualquer blocker aplicavel permanecer aberto. Para escape `documentation-claim-drift`, a classe so fecha depois de `DOC-SEMANTIC-DRIFT-001` encontrar e reconciliar alegacoes antigas em pelo menos duas superficies documentais sinteticas/transferiveis, sem depender do caso original. Fingerprints iguais sem nova evidencia exigem causa raiz, nao nova tentativa cega.
14. Se a remediacao criar novo material head depois de uma medicao quantitativa, marcar a medicao stale e reexecutar o protocolo no novo SHA antes do refreeze; nao reancorar o resultado antigo apenas alterando `head_sha` na matriz.

### 8. Remoto, CI autopilot e handoff

Usar `ci_mode=delivery-snapshot` somente para a primeira observacao do material SHA, transferir automaticamente a propriedade temporaria para `corrigir-ci` quando o run ainda nao estiver terminal verde e, no retorno, retomar obrigatoriamente em `finalize-after-ci`. Antes do fechamento terminal, resolver `audit_transport` conforme `references/native-github-audit-contract.md`; carregar `references/terminal-handoff.md` somente para `certified-handoff`.

1. Reconsultar o head e a base antes de escrever e executar o gate de conflitos. Se a PR estiver `dirty`, resolver conforme `references/pr-conflict-resolution.md` antes de qualquer snapshot de CI/handoff; a resolucao cria novo material head e exige gate final/freeze no SHA resultante. Depois disso, reconciliar delta externo sem force-push para restaurar SHA material antigo. Para correcao exclusiva de um `result-only-child` stale, executar `scripts/validate_result_only_pr_recovery.py` e aplicar a excecao estreita de `references/result-only-pr-recovery.md`: force-update apenas do ref da mesma PR, entre filhos irmaos do mesmo material, sem descartar qualquer commit material.
1.1. Antes de abrir PR substituta, provar que a PR original nao pode ser preservada com seguranca. Se a substituta for realmente necessaria, aplicar `replacement_pr_budget=1`: criar branch/PR uma unica vez no material head, usar o numero atribuido somente para construir o subject final e **nao escrever resultados no remoto** ate concluir a simulacao local completa do filho `result-only`.
2. Publicar uma rodada multi-arquivo atomicamente em um unico commit material quando a API permitir. Nao publicar o `result-only-child` terminal antes de conhecer o resultado da CI material, salvo quando um impedimento real de runtime exigir preservar um checkpoint nao auditavel. Antes de criar blobs por connector, aplicar o orcamento de transporte de `references/large-artifact-transport.md`: preferir perfil/artefato compacto e JSON textual; usar `base64-shards-v1` somente quando o transporte nativo falhar ou o limite objetivo do connector exigir.
3. Fazer uma unica observacao inicial do material SHA sob `delivery-snapshot`. Essa observacao e somente leitura e pode coletar run/jobs/steps/logs ja existentes; nunca fazer polling, `sleep`, rerun ou dispatch enquanto `entregar-issue` ainda for o owner.
4. Se todos os workflows/checks aplicaveis ja estiverem `completed/success`, registrar a evidencia exact-SHA e seguir para o fechamento de auditoria (`certified-handoff` ou `native-github-audit`). Se o estado for `pending-no-run`, `queued`, `in_progress`, `waiting`, `completed/failure`, `cancelled` ou outro terminal nao verde, **transferir imediatamente a propriedade de CI para `corrigir-ci` na mesma invocacao**, sem responder ao usuario. A transferencia encerra `delivery-snapshot` para esse SHA; os dois modos nunca ficam ativos simultaneamente.
5. Invocar `corrigir-ci` com envelope suficiente para retomar sem redescoberta: repository, PR/branch/base, material head, run/checks ja observados, paths/requisitos da entrega, estado de freeze/handoff existente e `return_control_to=entregar-issue`. `corrigir-ci` deve observar ate CI **material** terminal, diagnosticar toda falha da rodada, corrigir causas `actionable-delivery`, validar, publicar e continuar observando sem novo prompt. Ela nao edita `.audit/entregar-issue/*` e nao chama `entregar-issue`; encerra sua propriedade retornando o envelope v2 `next_phase=finalize-after-ci`. Falha externa/preexistente comprovada pode retornar bloqueio classificado; CI apenas pendente nao pode retornar como resultado final voluntario.
6. Ao receber envelope `ci_state=green` e `ci_owner_closed=true`, executar imediatamente `scripts/finalize_after_ci_checkpoint.py` e entrar no fast path `finalize-after-ci`. Reconsultar PR/head e comparar com o material head entregue a `corrigir-ci`:
   - mesmo material SHA: preservar gates/freeze ainda validos e continuar;
   - novo material SHA: ativar `material_dirty_since_freeze`, consumir `reason=post-ci-refreeze`, invalidar somente descendentes do delta, reexecutar gate final necessario e congelar novamente o SHA verde;
   - impedimento real (`blocked-external`, `blocked-handoff-recertification` ou `interrupted-by-runtime` real): encerrar como `bloqueado-por-impedimento-real`, com `Libera auditoria: NAO`.
7. Somente depois de existir **material head verde em CI**, resolver `audit_transport` usando o contrato canonico no trusted anchor e `scripts/classify_audit_transport.py`.
   - `native-github-audit`: seguir `references/native-github-audit-contract.md`; **nao** gerar `.audit/entregar-issue`, `handoff-ready.json` ou `result-only-child`. Reconsultar identidade remota, changed paths e checks/runs exact-head e emitir `terminal_native_audit_ready=READY` vinculado ao material head corrente.
   - `certified-handoff`: gerar o pacote neutro e `handoff-ready.json` usando `evidence_profile=standard` por padrao; promover para `critical` somente pelos sinais objetivos de `references/execution-profiles.md`, e usar `light` somente quando realmente nao houver comportamento material. Antes do builder, calcular o **issue-local diff** `work_item_start_sha..material_head_sha`, normalizar sua lista de paths e certifica-la em `scope.work_item_start_sha`, `scope.material_head_sha`, `scope.issue_changed_paths` e `scope.issue_delta_sha256`. Certificar tambem `subject.issue_number` e `subject.pull_request_number` separadamente. O diff `base_ref..PR head` e apenas contexto acumulado e nunca substitui o issue-local diff. O pacote pode usar shards somente depois de o JSON logico ter passado os gates; o sharding e transporte, nao nova evidencia. Se `artifact_reuse.status != current-target`, nenhuma existencia previa de `handoff-ready.json` satisfaz esta etapa; gerar certificado novo a partir das fontes/artefatos correntes. **Antes da primeira escrita remota do filho de resultados**, construir localmente o commit `result-only-child` exato, com parent material, blobs/manifests/shards finais e changed paths prospectivos; executar `validate_terminal_handoff.py` em modo de simulacao local usando esse SHA local como `published_head_sha=current_head_sha`, mais snapshots historicos/material-parent aplicaveis. Corrigir localmente ate `READY`. Somente entao publicar o pacote completo em filho direto `result-only-child` e validar parent + allowlist.
8. Em `certified-handoff`, guardar o SHA retornado pela publicacao como `published_handoff_head_sha` e aplicar integralmente a barreira pos-escrita de `references/terminal-handoff.md`. Em `native-github-audit`, nao existe filho de resultados: depois da ultima escrita material, fazer nova consulta remota e exigir que `current_head_sha == material_head_sha` congelado e que os checks/runs obrigatorios desse SHA continuem verdes; qualquer drift material exige revalidacao/refreeze antes de liberar auditoria.
9. Encaminhar para `auditar-issue` somente em contexto separado, CI material verde e um fechamento terminal valido para o transporte selecionado: `terminal_handoff=READY` em `certified-handoff` ou `terminal_native_audit_ready=READY` em `native-github-audit`. Confirmar esse fechamento com `scripts/validate_delivery_completion.py` (passando `terminal-handoff-proof.json` emitido por `validate_terminal_handoff.py` em `certified-handoff`); qualquer `BLOCK` impede a saida apta a auditoria. No modo certificado, manter os requisitos de `standard-evidence`/matriz/saturacao conforme perfil. Qualquer identidade stale, commit material posterior ou impedimento real encerra com `Libera auditoria: NAO`.

## Fast paths

- `finalize-after-ci`: fast path obrigatorio apos retorno de `corrigir-ci`; validar o checkpoint, proibir discovery/readiness/planejamento/suite material repetidos, executar `post-write-refreeze` somente se o material SHA mudou, resolver `audit_transport` e fechar `result-only-child` + handoff terminal apenas em `certified-handoff`; em `native-github-audit`, fechar diretamente `terminal_native_audit_ready=READY` sem `.audit`.
- `post-ci-refreeze`, `recovery_scope=post-write-refreeze`, `requires_refreeze=true` ou qualquer pos-escrita material: usar o mesmo `post-write-refreeze` de `references/terminal-handoff.md`; invalidar apenas descendentes do delta, refazer gate final/freeze no head material corrente e publicar novo result-only child. O envelope v2 de `corrigir-ci` seleciona este recorte por `next_phase=finalize-after-ci`; nao existe callback da subskill para o controlador.
- correcao exclusiva de `result-only-child` em PR aberta: antes de criar branch/PR nova, executar `scripts/validate_result_only_pr_recovery.py`. Se retornar `replace-result-only-child-in-original-pr`, prevalidar localmente o filho novo e substituir somente o ref da PR original conforme `references/result-only-pr-recovery.md`; se retornar `publish-in-original-pr`, publicar normalmente na mesma PR.
- `handoff-not-produced|handoff-stale`: executar `scripts/classify_handoff_recovery.py` com certificado, identidade remota e piso de auditoria frescos. `handoff-only` exige retorno explicito do classificador, mesmo target e nenhum refreeze pendente; `foreign-target` exige reconstrucao, e material drift exige `post-write-refreeze`.
- findings estruturados de auditoria imediatamente anterior: usar os findings como work items prontos; nao repetir discovery, readiness ou decomposicao integral da issue.
- ambiente sem checkout executavel: selecionar uma vez `connector-only` ou `artifact-bundle`; nao repetir clone/instalacao sem evidencia material nova.
- PR `dirty`/conflitada: resolver na mesma branch/PR antes de gate final/CI conforme `references/pr-conflict-resolution.md`; publicar a resolucao como material, revalidar o novo head e refazer freeze/CI descendentes.
- CI nao terminal no material head: transferir automaticamente para `corrigir-ci` como subrotina e retomar no mesmo controlador somente quando houver terminal verde ou impedimento real. O retorno verde deve cair diretamente em `finalize-after-ci`; nunca exigir novo acionamento do usuario, nunca reiniciar discovery e nunca entrar em ping-pong `entregar -> corrigir -> entregar -> corrigir`.
- documentacao/assets isolados: perfil `light`; config/schema, testes ou gerados preservam apenas os gates aplicaveis.
- finding novo nos mesmos arquivos: novo `work_item_fingerprint`; igualdade de paths nao autoriza reuso.

## Fechamento obrigatorio

Antes do resultado terminal, executar `references/delivery-obligation-completion-gate.md`.

## Saida

Declarar exatamente um estado:

- `aprovado-operacionalmente-sem-ressalvas`: somente com `external-audit.json` assinado por `auditar-issue` em contexto separado para o material head corrente e aceito por `<auditar-issue>/scripts/validate_external_audit_report.py <external-audit.json> --trusted-auditors <registro>`, com registro de auditores que o candidato nao pode alterar; parecer apenas textual nunca basta;
- `aprovado-internamente-pendente-auditoria-independente`;
- `bloqueado-por-impedimento-real`.

Nunca afirmar independencia apenas por trocar de Skill no mesmo contexto. Para qualquer saida `aprovado-internamente-pendente-auditoria-independente`, exigir CI material terminal verde e fechamento coerente com `audit_transport`: em `certified-handoff`, `artifact_reuse` sem foreign target ativo e `terminal_handoff=READY` com `repository/work_item/PR`, `material_head_sha` e `published_handoff_head_sha`; em `native-github-audit`, contrato canonico confiavel no trusted anchor, `terminal_native_audit_ready=READY`, identidade remota exact-head e nenhuma dependencia de `.audit/entregar-issue`. Nao usar CI pendente como estado final voluntario e nao usar o rotulo vago `limite-atingido-com-pendencias`; se a execucao realmente nao puder continuar, descrever o impedimento concreto em `bloqueado-por-impedimento-real` e `Libera auditoria: NAO`. Entregar requisitos fechados/abertos, arquivos, comandos, evidencias, findings agrupados, SHA congelado, estado remoto e proximo gate real.

## Contrato canonico

Os artefatos internos legados do controlador continuam usando o contrato declarado em `contracts/version.json`. Em `native-github-audit`, nenhum certificado/handoff `.audit` e emitido. Em `certified-handoff`, para o certificado/handoff consumido por `auditar-issue`, usar `contract_version=2026-08-20.3` (default de `build_handoff_certificate.py`). Nunca emitir handoff com `contract_version` diferente da exigida pelo auditor. Executar `scripts/controller_cli.py validate-contracts` e os testes focados; drift global preexistente deve ser reportado separadamente, nao mascarado por troca de numero.
