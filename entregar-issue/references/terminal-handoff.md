# Handoff terminal e reconciliacao pos-escrita

> **Escopo:** este protocolo aplica-se somente quando `audit_transport=certified-handoff`. Para repositorios com contrato canonico confiavel `native-github-audit`, usar `references/native-github-audit-contract.md` e nao publicar `.audit/entregar-issue`.

## Quando ler este arquivo

Ler quando houver PR aberta, publicação, CI ou coleta remota com `audit_transport=certified-handoff`.

## Índice

- [Regra central](#regra-central)
- [Vinculo com o alvo antes do fechamento](#vinculo-com-o-alvo-antes-do-fechamento)
- [Pre-publicacao e preservacao da PR](#pre-publicacao-e-preservacao-da-pr)
- [Antes de qualquer handoff independente](#antes-de-qualquer-handoff-independente)
- [Barreira universal pos-escrita](#barreira-universal-pos-escrita)
- [Precedencia da decisao de recovery](#precedencia-da-decisao-de-recovery)
- [Post-write refreeze](#post-write-refreeze)
- [Connector-only](#connector-only)
- [Pacote stale](#pacote-stale)
- [Latch contra escrita posterior ao handoff](#latch-contra-escrita-posterior-ao-handoff)

## Regra central

O `material_head_sha` e a identidade certificada. `handoff-ready.json` certifica esse material head e e publicado em um filho direto `result-only-child`; o commit de resultados nao redefine a identidade material.


## Vinculo com o alvo antes do fechamento

Antes de considerar qualquer handoff existente, aplicar `references/delivery-target-binding.md`. Um `handoff-ready.json` herdado da base ou de outra PR/issue e apenas dado historico. Se a classificacao for `inherited-base-artifact`, `foreign-target`, `partial-current-target` ou `unbound-or-invalid`, o estado terminal obrigatorio e `fresh-handoff-required`: artefatos anteriores nao satisfazem readiness e o fast path `handoff-only` fica proibido ate existir pacote corrente vinculado ao alvo atual.

O caso canonico a impedir e `base contem handoff A -> branch implementa B -> nenhum arquivo .audit muda -> produtor retorna B como pronto`. A existencia do certificado A nao conta como handoff de B; o controlador deve publicar um novo result-only child de B antes de qualquer encaminhamento a auditoria.


## Pre-publicacao e preservacao da PR

Antes da primeira escrita remota de um `result-only-child`, construir localmente a arvore/commit exatos que seriam publicados, incluindo o transporte final de manifests/shards. Executar todos os validadores semanticos e `validate_terminal_handoff.py` contra esse commit local, usando-o como `published_head_sha` e `current_head_sha`, com parent material e changed paths prospectivos. Esse `prepublication terminal simulation` deve retornar `READY`; erro de shard, hash, lineage, allowlist, subject ou artefato stale deve ser corrigido **antes** de mover qualquer ref remoto.

Quando a PR ja possuir um filho de resultados stale, carregar `references/result-only-pr-recovery.md` e executar `scripts/validate_result_only_pr_recovery.py`. Se o guard provar que o head corrente e o candidato novo sao filhos `result-only` irmaos do mesmo material e que nenhum path material sera descartado, preservar a PR original substituindo apenas o ref do filho stale depois da simulacao local `READY`. A proibicao geral de force continua valendo para material; a unica excecao e essa troca de evidencia terminal, estritamente confinada ao ref e seguida de leitura remota fresca + guard terminal real.

Nao abrir PR substituta enquanto a PR original for recuperavel por esse protocolo. Se uma substituta for inevitavel, permitir somente uma por invocacao e manter sua branch no material head ate o pacote final, ja vinculado ao numero da nova PR, passar integralmente pela simulacao pre-publicacao. Falhas locais devem ser corrigidas sem commits remotos. Nunca resolver uma falha do primeiro pacote abrindo automaticamente outra PR substituta.

## Antes de qualquer handoff independente

1. Executar validadores proporcionais ao `evidence_profile`: `light` valida specification/closure; `standard` valida specification/closure + `standard-evidence.json`; `critical` valida requirement attack matrix, risk saturation, inherited controls e evidence freshness aplicavel. Somente remediacao sistemica exige learning/escape/inherited lineage cumulativa.
2. Gerar `handoff-ready.json` somente por `scripts/build_handoff_certificate.py`, com subject coerente com repositorio, work item, PR/base/head quando aplicavel.
3. Publicar `.audit/entregar-issue` em um unico `result-only-child` cujo parent seja o material head e cujo delta contenha somente `certificate_commit_policy.allowed_paths`.
4. Registrar separadamente `published_handoff_head_sha` no momento da publicacao e, **depois da ultima escrita no repositorio**, fazer uma nova leitura remota para obter `current_head_sha`, parent e changed paths. Nao reutilizar como observacao terminal a resposta da API que criou o commit nem metadata capturada antes de uma escrita posterior. Reclassificar o pacote publicado contra `repository/work item/PR/base/head` terminais e exigir `current-target`; no modo local, `controller_cli.py refresh-context` deve atualizar `artifact_reuse`, e em `connector-only` executar `delivery_target_binding.py` sobre os bytes materializados do head remoto. Depois executar `scripts/validate_terminal_handoff.py` passando **as duas identidades** (`published_handoff_head_sha` e `current_head_sha`) imediatamente antes de uma resposta que possa liberar auditoria independente. Em reauditoria, passar `--previous-audit-escape-closure` para preservar o ledger de rejeicoes; passar tambem `--previous-inherited-controls` somente quando o perfil/remediacao exigir controles herdados (`critical` sistemico/misto). O guard deve preservar o `evidence_profile` e o `remediation_mode` certificados ao revalidar semanticamente os artefatos finais, incluindo o vinculo `learning-closure.source_event.rejection_id -> audit-escape-closure.source_audit.rejection_id`, sem promover silenciosamente `standard` para `critical`. Se o `result-only-child` alterar `inherited-controls.json` ou `audit-escape-closure.json`, materializar tambem as versoes desses arquivos no **material parent** e passar `--material-parent-inherited-controls`/`--material-parent-audit-escape-closure`. O guard deve provar monotonicidade contra o parent imediato alem do snapshot historico externo; um filho de resultados nunca pode apagar controle/escape que estava presente no candidato congelado.
5. CI `pending-no-run`, `queued`, `in_progress` ou `waiting` nao autoriza retorno nem handoff terminal: encerrar o modo `delivery-snapshot`, transferir ownership para `corrigir-ci` e continuar a mesma invocacao ate terminal. Gerar/publicar o handoff terminal somente depois de CI material verde; se `corrigir-ci` mudar o material, executar `post-write-refreeze` primeiro.

## Barreira universal pos-escrita

Se a invocacao iniciou com handoff existente ou publicou qualquer arquivo/commit, nenhum retorno pode contornar reconciliacao terminal de identidade. Registrar `last_material_write_sha`, reconsultar o remoto e provar um estado:

- `terminal-handoff-valid`: head atual e result-only child valido do material head;
- `unchanged-exact-head`: nenhum handoff anterior aplicavel e nenhuma escrita material posterior;
- bloqueio real com `Libera auditoria: NAO`.

Se `current_head != published_handoff_head_sha`, o guard terminal deve falhar mesmo que o handoff tenha sido valido em um instante anterior. Obter o compare completo `published_handoff_head_sha..current_head_sha`; nao usar apenas os paths do ultimo commit, pois uma escrita material intermediaria pode ser seguida por outro commit somente de resultados. Classificar o delta usando os changed paths do compare completo:

- somente paths allowlisted e parent correto: validar como handoff terminal, incluindo lineage delta contra o material parent para artefatos cumulativos;
- qualquer path material, inclusive teste, documentacao ou formatacao: emitir `RECOVERY: post-write-refreeze` e executar `post-write-refreeze` na mesma invocacao;
- material head estavel sem filho de resultados e pacote anterior do **mesmo target**: executar `handoff-only`; pacote `inherited-base-artifact|foreign-target` exige reconstrucao corrente antes do handoff;
- impedimento real de runtime/connector: bloquear e nao encaminhar para auditoria.

## Precedencia da decisao de recovery

Quando a entrada imediata vier de `auditar-issue`, tratar `recovery_scope`/`requires_refreeze` como um **lower bound**. A identidade remota fresca pode tornar a recuperacao mais conservadora, nunca menos:

1. `inherited-base-artifact|foreign-target|partial-current-target|unbound-or-invalid` -> `fresh-handoff-required`;
2. auditoria com `recovery_scope=post-write-refreeze` ou `requires_refreeze=true` -> no minimo `post-write-refreeze`;
3. parent diferente do material certificado ou qualquer path material no delta relevante -> `post-write-refreeze`;
4. somente material head realmente estavel e pacote do mesmo target pode resultar em `handoff-only`;
5. `handoff-stale` e apenas uma categoria de causa, nao uma decisao de recovery.

Executar `scripts/classify_handoff_recovery.py` antes de qualquer fast path. Nao limpar o estado de material drift publicando outro filho de resultados: o drift so fecha depois de gate final e novo freeze no SHA material atual.

## Post-write refreeze

Qualquer mudanca material apos freeze invalida freeze, atestacoes/evidencias dependentes e certificado anteriores. Comparar o delta material, invalidar somente descendentes realmente dependentes, reexecutar gates necessarios, refazer freeze e gerar novo result-only child. `corrigir-ci` usa este mesmo protocolo apos uma correcao material verde.

Evidencia quantitativa exact-SHA deve ser reexecutada quando o material head mudar; nao reancorar percentis, tempos, contagens ou benchmarks antigos alterando apenas metadados.

## Connector-only

Ausencia de checkout nao permite omitir o pacote. Materializar inputs e artefatos em workspace efemero, executar os validadores da Skill e publicar o result-only child pelo connector. Se o connector nao permitir os passos obrigatorios, bloquear antes de chamar `auditar-issue`.

## Pacote stale

Pacote `.audit/entregar-issue` de outra issue/PR/SHA nao conta como evidencia corrente. Reconstruir somente os artefatos exigidos pelo perfil atual e publicar um pacote vinculado ao alvo; nao repetir discovery/implementacao quando o material head estiver estavel. Artefatos historicos estrangeiros podem permanecer fora do conjunto certificado se a politica de paths permitir; a auditoria deve consumir apenas `artifacts` certificados. Nunca apagar lineage cumulativa do mesmo alvo.

## Latch contra escrita posterior ao handoff

O caso `material M -> handoff H -> commit material P` e uma regressao terminal obrigatoria. Mesmo que `H` tenha sido validado quando publicado, nenhuma resposta pode usar essa prova depois de `P`. O gate final deve receber `published_handoff_head_sha=H`, uma observacao remota fresca `current_head_sha=P` e os changed paths do compare `H..P`; a divergencia bloqueia o retorno e, se qualquer commit posterior a `H` tocar caminho fora da allowlist de resultados, exige `RECOVERY: post-write-refreeze`.

O valor `published_handoff_head_sha` e historico da publicacao; `current_head_sha` e estado remoto observado depois da ultima escrita. Nunca colapsar os dois campos em uma unica variavel ou inferir que continuam iguais sem nova leitura.
