# Eficiencia de execucao

## Quando ler este arquivo

Ler sempre: define a regra central de custo, os orçamentos de conclusão e de espera remota e a barreira terminal de handoff.

## Índice

- [Regra central](#regra-central)
- [Custos proibidos](#custos-proibidos)
- [Fingerprints](#fingerprints)
- [Validacao](#validacao)
- [Delegacao](#delegacao)
- [Orcamento de conclusao](#orcamento-de-conclusao)
- [Orcamento de espera remota](#orcamento-de-espera-remota)
- [Publicacao atomica](#publicacao-atomica)
- [Fast path de auditoria](#fast-path-de-auditoria)
- [Estabilidade do head](#estabilidade-do-head)
- [Orcamento de churn de PR](#orcamento-de-churn-de-pr)
- [Barreira terminal de handoff](#barreira-terminal-de-handoff)

## Regra central

Usar um unico controlador, plano e estado. Implementacao, documentacao por delta, higiene, gates e remediacao sao etapas internas de `entregar-issue`, nao chamadas de Skills.

## Custos proibidos

- recalcular o mesmo plano sem input material novo;
- reler integralmente issue, diff ou documentacao quando o manifesto vigente cobre a etapa;
- transformar o diff produzido em invalidacao da propria implementacao;
- executar suite completa durante ajustes intermediarios;
- criar handoff entre etapas internas;
- chamar uma especialidade para checklist simples;
- revelar um finding barato por ciclo quando erros irmaos podem ser agrupados;
- repetir clone, instalacao de dependencias ou materializacao de checkout depois que o mesmo impedimento foi comprovado e nenhuma evidencia material mudou;
- publicar uma mesma rodada multi-arquivo como uma sequencia de commits por arquivo quando a API suporta commit atomico;
- fazer polling, `sleep` ou consultas repetidas **pelo owner `entregar-issue`** esperando workflow futuro aparecer ou concluir; quando for necessario aguardar, transferir a propriedade para `corrigir-ci` em vez de devolver o controle ao usuario;
- usar o gate final ou a auditoria independente como primeira descoberta de ataque barato ou superficie material ja derivavel do contrato ou do `produced_diff`;
- em otimizacao de latencia, usar apenas benchmark agregado sem inventariar trabalho do caminho produtivo, cobertura das metricas por etapa e operacoes caras nao consumidas.

## Fingerprints

Separar:

- `implementation_scope`: caminhos planejados para a edicao;
- `produced_diff`: saida observada, usada por documentacao, dominios, higiene e gates descendentes;
- `work_item_fingerprint`: causa/remediacao que reabre implementacao;
- identidade material: head, base e merge preview;
- fontes, baseline, workflows, politica e permissoes.

Timestamps e telemetria nao invalidam trabalho.

## Validacao

Durante edicao, executar checks focados. Depois que `produced_diff` estabilizar, executar uma unica reconciliacao incremental de superficies novas contra `requirement-attack-matrix.json`; nao recalcular o plano nem reabrir requisitos estaveis. Superficie nova recebe controle focado no mesmo work item. Executar gate final completo uma vez antes do freeze e novamente somente depois de correcao material que invalide esse gate.

O gate final confirma saturacao, nao substitui o shift-left: ataque barato que estreia apenas no gate final deve voltar diretamente para implementacao antes de qualquer handoff independente.

## Delegacao

`skill_plan` contem apenas Skills externas. `internal_plan` contem implementation, documentation-delta e hygiene. Uma especialidade externa e acionada no maximo uma vez por fingerprint e recebe write ownership exclusivo.

## Orcamento de conclusao

Ao entrar em freeze, ativar `completion-first`: nenhuma nova descoberta ampla, expansao de matriz, releitura integral ou especialidade pode iniciar, exceto a delegacao necessaria a `corrigir-ci`. Reservar o restante da invocacao para `gate final -> freeze -> publicacao material -> CI autopilot -> finalize-after-ci -> post-write-refreeze se necessario -> resolver audit_transport -> fechamento terminal`. Em `certified-handoff`, o fechamento e `pacote minimo -> result-only -> leitura remota -> validate_terminal_handoff`; em `native-github-audit`, e `releitura exact-head -> terminal_native_audit_ready`, sem `.audit`. `finalize-after-ci` e checkpoint fechado: proibir discovery, readiness, replanejamento e repeticao da suite material se o SHA verde nao mudou.

Se faltar artefato exigido pelo perfil, produzir a forma minima valida antes de qualquer evidencia opcional. Para `standard`, isso significa `standard-evidence.json`, nao uma matriz critica. Para `critical`, reutilizar controles equivalentes e referencias de evidencia em vez de duplicar narrativas. Sharding, enriquecimento de relatorio e telemetria sao posteriores ao fechamento semantico e nao podem impedir a publicacao quando existe representacao menor suportada.

Depois que material head, inputs e gates permanecem identicos, uma nova invocacao em `handoff-only` nao pode repetir discovery, planejamento, suite, saturacao ou especialidades. Revalidar somente identidade, hashes dos artefatos ja fechados, alvo corrente, parent/allowlist e publicacao terminal.

## Orcamento de espera remota

Depois do freeze/publicacao material, `entregar-issue` faz no maximo **uma observacao inicial** de CI por SHA candidato. Ler jobs, steps, logs e artefatos ja existentes faz parte desse snapshot. Se o SHA nao estiver terminal verde — inclusive `pending-no-run`, `queued`, `in_progress`, `waiting` ou `completed/failure` — encerrar a propriedade `delivery-snapshot` e transferir imediatamente para `corrigir-ci` na mesma invocacao de nivel superior.

A espera longa pertence a `corrigir-ci`: ela pode reobservar com backoff moderado ate terminal, diagnosticar falhas, corrigir causas `actionable-delivery`, publicar novo material e continuar observando, sempre sem novo prompt. Essa delegacao nao e custo proibido nem polling duplicado porque os owners sao mutuamente exclusivos. `entregar-issue` nao responde ao usuario apenas porque a CI ainda esta em andamento.

Quando `corrigir-ci` devolver verde, sua propriedade termina. Validar o envelope v2 e entrar diretamente em `finalize-after-ci`. Se o material SHA mudou, executar `post-write-refreeze` e revalidar apenas descendentes invalidados; se nao mudou, reutilizar freeze/gates ainda validos. Nunca chamar `corrigir-ci` de volta como parte da recertificacao do mesmo material. Somente impedimento real de runtime/infraestrutura pode encerrar a invocacao sem CI verde. Nao usar rerun/dispatch para fabricar evidencia.

## Publicacao atomica

Quando uma rodada altera varios arquivos por GitHub API, preparar todos os blobs e uma unica tree/commit antes de mover a ref. Usar commits sequenciais somente quando houver dependencia semantica de SHA entre fases; nesse caso limitar a duas fases: commit material e commit exclusivamente de resultados/evidencia. Nunca usar commits por arquivo como mecanismo normal de edicao.

## Fast path de auditoria

Se uma auditoria imediatamente anterior ja forneceu findings estruturados e a identidade ainda e compativel, consumir esses findings como work items. Revalidar apenas o delta de identidade e os requisitos/gates afetados; nao repetir discovery, readiness ou decomposicao integral da issue.

## Estabilidade do head

Capturar o head no preflight e reconsulta-lo imediatamente antes da escrita. Mudanca externa exige reconciliacao do delta, nao force-push para restaurar SHA **material** antigo. Para um head que seja comprovadamente apenas `result-only-child` stale, a excecao estreita de `references/result-only-pr-recovery.md` pode substituir somente o ref por um filho irmao ja prevalidado, preservando todo o material. Depois da publicacao atomica, tratar o novo head como unico candidato da rodada.

## Orcamento de churn de PR

Preservar a PR original sempre que tecnicamente seguro. `replacement_pr_budget=1` e teto por invocacao, nao meta: abrir substituta somente quando a original estiver indisponivel ou irrecuperavel sem reescrever material. Uma PR substituta deve permanecer no material head enquanto o pacote e validado localmente; somente um filho de resultados integralmente prevalidado pode ser publicado. Falha de pacote nao autoriza encadear novas PRs substitutas.


## Barreira terminal de handoff

Depois de existir material head congelado e localmente pronto, nao retornar enquanto a CI material puder continuar sendo acompanhada por `corrigir-ci`. Com a CI terminal verde, todo caminho de sucesso passa pela barreira do `audit_transport`: `certified-handoff` gera certificado/result-only e valida parent/allowlist; `native-github-audit` reconsulta identidade e checks exact-head e nao publica `.audit`. Se a CI ou a barreira selecionada nao puderem ser satisfeitas por impedimento real, o resultado e bloqueio concreto e nao convite para auditoria.
