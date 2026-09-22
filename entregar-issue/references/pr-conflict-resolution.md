# Gate de conflitos da PR

## Objetivo

Garantir que uma entrega com PR aberta nao siga para gate final, CI ou handoff enquanto a branch estiver em conflito real com a base corrente. Detectar conflito cedo, resolver na mesma PR quando houver capacidade segura de escrita e revalidar todo descendente invalidado pela integracao.

## Classificacao

Usar a PR remota e, quando disponivel, uma prova Git local contra os SHAs exatos de head e base.

Classificar como `conflicted` somente com evidencia de conflito de merge, por exemplo:

- `mergeable_state=dirty` no payload atual da PR; ou
- merge probe local deterministico entre `base_sha` e `head_sha` que reporte paths em conflito.

Nao confundir conflito com outros estados remotos:

- `blocked`: protecao, aprovacao, policy ou check pendente/falho; nao e conflito por si so;
- `behind`: branch desatualizada, mas potencialmente mergeavel;
- `unstable`: checks nao verdes, nao conflito por si so;
- `unknown`/`mergeable=null`: mergeabilidade ainda nao resolvida; reconsultar uma vez ou usar merge probe local antes de concluir.

`mergeable=false` sem causa discriminada nao autoriza resolver arquivos no escuro. Confirmar `dirty` ou conflito pelo Git.

## Momento do gate

Executar duas vezes quando houver PR:

1. no preflight, antes da primeira escrita material da invocacao;
2. novamente imediatamente antes do gate final/freeze ou da primeira observacao de CI, usando base/head remotos frescos.

Se a base mudar depois do primeiro gate, invalidar a observacao anterior e reclassificar.

## Resolucao

Quando `conflicted`:

1. congelar `head_sha`, `base_sha`, branch head e `base_ref` atuais;
2. obter as duas versoes e o ancestral comum sem escrever na base;
3. atualizar a branch da PR incorporando a base atual e resolver cada path conflitado semanticamente;
4. nunca usar resolucao global `ours`/`theirs` sem inspecao do requisito e dos consumidores afetados;
5. preservar mudancas funcionais da issue e mudancas legitimas que chegaram pela base;
6. executar checks focados nos paths conflitados e seus consumidores diretos;
7. publicar a resolucao na **mesma branch/PR**;
8. reconsultar a PR e exigir ausencia de `dirty` ou conflito no merge probe;
9. tratar o novo head como escrita material: ativar `material_dirty_since_freeze`, invalidar gates/freeze/CI descendentes e refazer o gate final no SHA resultante.

Preferir merge normal da base na branch da PR quando isso evita reescrita de historia. Nao fazer merge da PR na base. Nao usar force-push por padrao. Se a unica estrategia disponivel exigir reescrever historia compartilhada ou descartar commits nao pertencentes ao controlador, bloquear em vez de forcar.

## Capacidade por runtime

### `local-git`

Usar fetch dos refs exatos e merge/rebase em workspace local conforme a politica do repositorio. Para branch compartilhada, preferir merge commit normal da base na branch da PR. Resolver conflitos, validar e fazer push normal.

### `connector-only`

Usar apenas operacoes do connector que preservem a mesma PR e permitam incorporar a base sem descartar commits. Se o connector nao permitir criar a integracao necessaria com seguranca, retornar impedimento real `conflict-resolution-capability-unavailable`; nao simular resolucao alterando apenas os arquivos conflitantes sem atualizar a ancestralidade Git.

## Estado e rastreabilidade

Registrar no estado do controlador:

- `conflict_gate.status=clean|conflicted|resolved|unresolved`;
- `observed_head_sha` e `observed_base_sha`;
- `detection_source=github|git-probe|both`;
- paths conflitados quando conhecidos;
- estrategia aplicada (`merge-base-into-head`, `rebase-head-onto-base` ou equivalente permitido);
- commit/SHA produzido pela resolucao;
- checks focados executados;
- reconsulta remota final.

Uma resolucao de conflito nunca conta como handoff `result-only`: ela e material e exige novo freeze e nova CI do SHA resultante.
