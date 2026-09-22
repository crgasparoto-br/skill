# Recuperacao de handoff preservando a PR original

## Objetivo

Evitar churn de pull requests quando uma rejeicao ou falha terminal afeta somente o `result-only-child`. A identidade publica da entrega deve permanecer na PR original sempre que nenhum commit material precise ser descartado.

## Regra de precedencia

Preservar a PR original e sua branch antes de considerar uma PR substituta.

Usar uma atualizacao forçada do ref **somente** como excecao estreita para trocar um `result-only-child` stale por outro `result-only-child` irmao, nunca para reescrever material. A excecao e valida apenas quando todas as condicoes abaixo forem provadas:

1. a PR original continua aberta, nao mergeada e a branch continua gravavel;
2. o head remoto corrente `H_old` foi relido imediatamente antes da troca e continua sendo exatamente o head esperado;
3. `parent(H_old) == material_head_sha`;
4. o diff `material_head_sha..H_old` contem somente paths autorizados pelo certificado corrente e inclui `handoff-ready.json`;
5. o candidato local `H_new` tem o mesmo `material_head_sha` e `parent(H_new) == material_head_sha`;
6. o diff prospectivo `material_head_sha..H_new` contem somente paths autorizados pelo certificado novo e inclui `handoff-ready.json`;
7. subject de repositorio, issue, PR, base e branch permanece semanticamente identico;
8. o pacote novo passou todos os validadores aplicaveis, inclusive lineage historica/material-parent, shards e hashes;
9. executar `validate_terminal_handoff.py` **antes da escrita remota**, usando um commit local sintetico/exato para `H_new` como `published_head_sha` e `current_head_sha`; somente `READY` autoriza a troca;
10. nenhuma escrita material, commit externo ou divergencia desconhecida apareceu desde a leitura de `H_old`.

Executar `scripts/validate_result_only_pr_recovery.py` para provar as condicoes estruturais antes da troca do ref.

Quando essas condicoes forem satisfeitas, atualizar a branch da mesma PR de `H_old` para `H_new` com force apenas no ref. Essa operacao e uma substituicao de evidencia terminal: nenhum commit material pode ser removido, alterado ou escondido.

Depois da troca:

- fazer nova leitura remota independente;
- exigir `current_head_sha == H_new`;
- confirmar novamente `parent(H_new) == material_head_sha` e paths allowlisted;
- executar `validate_terminal_handoff.py` com a identidade remota fresca;
- somente entao liberar auditoria independente.

## Quando force continua proibido

Nao usar a excecao se o head corrente contiver qualquer path material, se o parent nao for o material certificado, se a PR tiver recebido commit externo, se o material head mudou, se a branch estiver protegida contra a operacao ou se a identidade do target divergir. Nesses casos, usar o fluxo normal na **mesma PR**: reconciliar o material corrente, refazer gates/freeze e publicar um novo filho direto quando a topologia permitir.

Nunca usar force para restaurar um SHA material antigo, apagar correcao funcional, esconder commit de terceiro ou contornar `post-write-refreeze`.

## PR substituta como ultimo recurso

Abrir PR substituta somente quando a PR original estiver fechada/mergeada, a branch original estiver indisponivel ou nao gravavel, ou o provider nao oferecer uma forma segura de restaurar o filho direto sem descartar material.

Aplicar `replacement_pr_budget=1` por invocacao. Antes de abrir a substituta, materializar o material head e todos os snapshots historicos necessarios. Depois que o provider atribuir o numero da nova PR, **nao publicar nenhum commit de resultados ainda**:

1. gerar localmente o pacote final com o subject exato da nova PR;
2. validar hashes, manifests/shards, lineage cumulativa e controles herdados;
3. construir localmente o commit `result-only-child` exato, filho direto do material;
4. simular o terminal guard com esse commit local;
5. corrigir qualquer falha localmente e repetir a simulacao sem escrever no remoto;
6. somente depois de `READY`, publicar uma unica rodada atomica de resultados e mover a branch uma vez.

Se a publicacao da substituta revelar uma falha de pacote que deveria ter sido detectada pela simulacao, corrigir a causa e, quando a excecao estreita acima for aplicavel, substituir o filho de resultados **na mesma PR substituta**. Nao abrir uma segunda PR substituta automaticamente. Se a mesma PR nao puder ser preservada com seguranca, bloquear com `Libera auditoria: NAO` e reportar o impedimento real.
