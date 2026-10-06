# Implementacao interna

## Quando ler este arquivo

Ler sempre: define preparar, implementar, validar durante a edição e fechar por requisito.

## Índice

- [Principio](#principio)
- [Preparar](#preparar)
- [Implementar](#implementar)
- [Controles criticos preservados](#controles-criticos-preservados)
- [Reconciliar risco pelo diff](#reconciliar-risco-pelo-diff)
- [Remediar gate deterministico reprovado](#remediar-gate-deterministico-reprovado)
- [Validar durante a edicao](#validar-durante-a-edicao)
- [Fechamento por requisito](#fechamento-por-requisito)

## Principio

Executar implementacao como uma etapa interna do mesmo controlador. Consumir snapshot, fechamento, risco, caminhos, work items e write ownership sem reatomizar a issue.

## Preparar

1. Mapear cada requisito somente para as camadas necessarias.
2. Ler referencias especializadas apenas quando os sinais de risco existirem.
3. Para cada `risk_surface` ja conhecida, definir antes da primeira edicao o controle positivo, o controle negativo primario e a regressao focada que fecharao a superficie. Quando o controle for automatizavel, preferir um teste/procedimento que demonstre a falha da `plausible_wrong_implementation`, nao apenas um teste nominal do caminho feliz.
4. Registrar `input_fingerprint`, `implementation_scope`, `work_item_fingerprint` e `write_owner`.
5. Nao usar arquivos produzidos nesta rodada como novo input para reabrir a propria rodada; o diff pode apenas revelar superficies adicionais para reconciliacao pos-diff.

## Implementar

- Alterar o menor conjunto coeso de arquivos.
- Preservar arquitetura e contratos publicos, salvo mudanca explicitamente requerida.
- Implementar comportamento ponta a ponta, nao apenas o caminho feliz.
- Atualizar testes e documentacao no mesmo recorte.
- Evitar TODO permanente, mock definitivo, seed incompleto ou fallback que esconda obrigacao.
- Para persistencia, autorizacao, entrada nao confiavel, provider, retry, concorrencia ou proveniencia, aplicar as referencias especializadas.

## Controles criticos preservados

- Validar identificadores estruturados recebidos do cliente antes do primeiro adapter ou comando SQL; nao depender do cast do banco como validacao publica.
- Tratar erro inesperado de persistencia como 5xx fail-closed: resposta publica generica, `correlationId` preservado e detalhes brutos somente em log interno redigido.
- Para entrada nao confiavel, preservar a representacao bruta ate concluir validacoes de bytes, vazio, encoding, limite, hash e identidade; nao normalizar antecipadamente.
- Inventariar modos, branches e todos os campos consumidos. Construir a matriz modo x invariante x familia de campo e aplicar `accepted_modes x consumed_fields x field_scope_placements`; um campo representativo nao comprova os demais. Cobrir limite + 1, padding externo e fronteira publica com os controles `IP-RAW-001`, `IP-MODE-001`, `IP-SCOPE-001`, `IP-INACTIVE-001` e `IP-EFFECT-001`.
- Para estados com proveniencia (`confirmedBy`, `confirmedAt`, snapshot, origem ou justificativa), tratar reenvio semanticamente identico como no-op. Executar `PROV-NOOP-001`: ator A confirma, ator B reenvia o mesmo estado ao alterar outro campo e um caso irmao em que B muda realmente a decisao. Preservar a proveniencia de A no no-op e transferi-la somente na mudanca efetiva. Validar persistencia apos releitura e tambem harness de schema reduzido/legado quando houver migration, trigger ou constraint.
- Quando calculo/agregado depende de uma dimensao semanticamente repetida entre registros ligados, aplicar `REL-SEM-001` antes de validar apenas o consumidor: inventariar todos os produtores que podem criar/alterar a relacao, usar valores deliberadamente incompatíveis, atravessar o entrypoint canonico de escrita e exigir rejeicao fail-closed ou transformacao/conversao explicita. Cobrir pelo menos criacao versus atualizacao ou outro par de lifecycle/produtor. Releitura/aggregate downstream deve provar que o estado incompatível nao sobreviveu nem foi apenas relabelado.
- Quando evidencia, revisao, aprovacao ou decisao definir o escopo de uma mutacao posterior, aplicar `evidence-effect-scope-gate.md`: derivar o conjunto autorizado da fonte canonica no ponto do efeito e provar por fixture divergente que `effect_b` e rejeitado quando a fonte autoriza apenas `effect_a`. Repetir o ataque em branch emergencial, override, excecao, bypass ou fallback quando existir. Validar ausencia de linha, evento, timestamp, outbound ou estado parcial para o efeito fora do escopo.
- Garantir que uma tentativa do executor produza no maximo uma chamada outbound ao provider. Helpers transitivos nao podem executar probe, diagnostico ou recuperacao oculta.
- Para latencia/desempenho, aplicar `performance-critical-path-gate.md`: inventariar I/O/operacoes diretas, transitivas e paralelas do entrypoint produtivo, classificar a etapa semantica e confrontar cada operacao com a fronteira de `db_ms`/`context_ms`/`llm_ms`/`persist_ms`/delivery ou metrica equivalente. Uma metrica parcial nao fecha observabilidade so porque `total_ms` esta correto.
- Para otimizacao de caminho critico, mapear saidas realmente consumidas por cada ramo. Helper/context builder que executa query, serializacao ou calculo para campos descartados pelo consumidor permanece trabalho nao essencial. Provar ausencia por zero invocacoes no ramo otimizado e presenca/correcao no ramo irmao que realmente necessita do dado.
- Para alerta, incidente, pendencia ou notificacao persistente que possa ser reaberta por mudanca material de estado, nao limitar a decisao de abertura ao instante de criacao da entidade/janela. Executar `ALERT-REOPEN-001`: partir de estado + alerta ja persistidos, provocar uma escalada material de severidade/faixa e separadamente um vencimento sem resolucao, exigir exatamente um novo/reaberto evento por transicao e zero duplicatas em retries. Quando um novo horizonte temporal for criado por extensao/renovacao, seu vencimento deve possuir identidade propria e poder gerar nova reabertura sem reutilizar silenciosamente o evento do horizonte anterior.
- Quando retry, idempotencia, duplo envio, mobile ou teclado forem requisitos, executar o fluxo em navegador real; busca textual no source nao substitui a prova.

## Reconciliar risco pelo diff

Depois que o recorte funcional estabilizar e antes de encerrar a implementacao, executar uma unica reconciliacao incremental usando `produced_diff`, entrypoints e consumidores diretos:

1. procurar somente superficies materiais novas que nao eram derivaveis antes da edicao, como novo endpoint, store, processo, fallback, canal de credencial, serializer, fronteira publica ou dependencia transitiva;
2. cruzar cada superficie nova com `risk_family`, `plausible_wrong_implementation` e controles ja registrados em `requirement-attack-matrix.json`;
3. para superficie sem controle primario, manter o mesmo `work_item_fingerprint`, criar o controle focado e executa-lo antes de sair da etapa;
4. nao recalcular readiness, plano ou requisitos ja estaveis por causa do proprio diff;
5. registrar como falha de shift-left qualquer ataque barato derivavel do contrato ou do diff que apareca pela primeira vez apenas no gate final.

A reconciliacao pos-diff existe para antecipar o que a auditoria tentaria refutar, nao para executar uma segunda auditoria completa.

## Remediar gate deterministico reprovado

Quando o work item vier de auditoria/CI com um comando deterministico que falhou, tratar esse comando como parte do contrato da remediacao. Reproduzi-lo antes da edicao quando possivel e reexecuta-lo no novo material head depois da correcao. Comando de sintaxe, teste parcial ou ferramenta diferente nao fecha o finding. Persistir comando original, exit code anterior, comando reexecutado, `subject_sha`, exit code zero e hash do log em `audit-remediation.json`.

Se o workflow for sequencial e um passo anterior abortou a cadeia, marcar os passos seguintes como `not-reached`; nao declarar lint/typecheck/test/build aprovados sem execucao observada.

## Validar durante a edicao

Executar somente checks focados:

- teste unitario ou integracao diretamente relacionado;
- lint, type-check ou build parcial aplicavel;
- migration, schema ou contrato publico afetado;
- links, exemplos e comandos documentais alterados;
- navegador real apenas quando a prova exigir interacao, retry, idempotencia, teclado, responsividade ou continuidade.

Nao executar a suite completa a cada ajuste.

## Fechamento por requisito

Antes de encerrar a implementacao, registrar para cada requisito:

- comportamento implementado;
- arquivos e entrypoints;
- evidencia positiva;
- todas as `risk_surfaces` materiais conhecidas;
- controle negativo discriminante primario para cada `risk_family + surface`;
- casos irmaos que variem `surface + dimension` quando exigidos pela familia;
- regressao;
- limitacao ou pendencia real.

Antes de declarar o requisito fechado, carregar somente o checklist aplicavel:

- contrato publico, catalogo/planilha, verbos, fidelidade de testes ou fechamento campo a campo: `implementation-fechamento-contrato.md`;
- fronteira publica, mutacao condicionada, concorrencia, vigencia, permissoes, transicao terminal ou formulario com retry: `implementation-fechamento-alto-risco.md`;
- adapter, provider, politica de runtime, traducao de request ou compatibilidade legada: `implementation-fechamento-infraestrutura-runtime.md`;
- leitura/projecao publica, fonte canonica em multiplas superficies ou documentacao concorrente: `implementation-fechamento-leitura-consistencia.md`.

Nenhum requisito segue ao gate final com superficie material conhecida sem controle focado executado. Executar uma leitura final do diff e procurar erros irmaos da mesma causa. Nao devolver a rodada com apenas o primeiro erro barato descoberto.
