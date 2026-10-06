# Gate remoto por SHA

Observacao remota somente leitura do material SHA: snapshot inicial sob `delivery-snapshot`, transferencia para `corrigir-ci` e criterios de aplicabilidade de workflows. Politica de acoes permitidas: `contracts/github-actions-policy.md`.

## Snapshot inicial e transferencia de ownership

A coleta de `entregar-issue` e snapshot, nao monitoramento. Para cada SHA candidato, executar no maximo uma coleta inicial depois da publicacao/freeze. Ler jobs, steps, logs e artefatos pertencentes ao run retornado faz parte desse snapshot e nao e polling. Se workflow aplicavel ainda nao possuir run elegivel, registrar `pending-no-run`; se o run existir mas estiver `queued`, `in_progress`, `waiting` ou equivalente, registrar o estado observado.

Nesses casos **nao responder com pendencia remota**. Encerrar a propriedade `delivery-snapshot` e transferir imediatamente para `corrigir-ci` com `ci_mode=ci-remediation-loop` dentro da mesma invocacao de nivel superior. `entregar-issue` nao faz polling, `sleep`, backoff, rerun ou dispatch; `corrigir-ci`, agora owner exclusivo, continua observando com espera moderada ate terminal.

A transferencia tambem se aplica a `completed/failure`: o diagnostico/remediacao de CI passa para `corrigir-ci`, que agrupa causas e tenta deixar o SHA corrente ou seu sucessor material verde sem pedir novo prompt. Uma correcao material cria novo SHA candidato; ao retornar verde, `entregar-issue` executa `post-write-refreeze` antes do handoff final.

## Falha remota concluida

`completed/failure` nao e pendencia temporal. Quando um workflow aplicavel do SHA candidato terminar com falha:

1. consultar jobs do run observado;
2. identificar jobs e steps falhos;
3. ler somente os logs existentes necessarios para causa raiz;
4. agrupar erros irmaos e classificar cada causa como `actionable-delivery`, `external-infrastructure` ou `unrelated-preexisting`;
5. para `actionable-delivery`, produzir finding com workflow/run/job/step, mensagem discriminante, paths/requisitos afetados e `work_item_fingerprint`, transferir o diagnostico/remediacao para `corrigir-ci` na mesma invocacao e invalidar somente evidencias descendentes se houver novo material, sem pedir novo prompt;
6. para `external-infrastructure`, registrar `remote_gate=blocked-external` e nao alterar codigo por tentativa;
7. para `unrelated-preexisting`, vincular a baseline comprovada e nao ampliar o escopo;
8. nunca fazer rerun ou dispatch para testar a hipotese; validar a correcao localmente, executar gate final afetado e publicar novo SHA somente quando houver mudanca material.

## Base e merge preview

Exigir:

- `head_sha_before == head_sha_after == SHA congelado`;
- `base_sha_before == base_sha_after == base_sha` congelado;
- `merge_preview_sha_before == merge_preview_sha_after` e nao vazio;
- base ref igual a da PR;
- mergeabilidade resolvida e ausencia de conflito real. Tratar `mergeable_state=dirty` como conflito; `blocked`, `behind` e `unstable` nao sao conflito por si so e devem ser classificados pelo motivo real (policy/check/base desatualizada).

Mudanca da base ou do merge preview invalida o ciclo mesmo quando o head permanece igual.

## Workflows

Inventariar todos os arquivos `.github/workflows/*.yml|yaml` ja existentes. YAML malformado reprova; nunca equivale a workflow nao aplicavel. Nao criar ou alterar workflow para satisfazer este gate, gerar artefato ou obter novo run.

Interpretar somente filtros no escopo de `on.pull_request` e `on.pull_request_target`:

- `branches` e `branches-ignore` contra a branch-base da PR;
- `paths` e `paths-ignore` contra o diff congelado;
- padroes negativos na ordem do GitHub Actions.

Uma chave `paths` dentro de jobs, strategy ou matrix nao e filtro de PR.

Para cada workflow de PR:

- determinar aplicabilidade ao diff e a branch-base;
- workflow aplicavel exige o ultimo run elegivel no SHA com evento `pull_request` ou `pull_request_target`;
- exigir `completed/success`, ao menos um job, steps nao vazios e conclusoes aceitaveis;
- `workflow_dispatch` nunca substitui o run obrigatorio de PR e nao deve ser disparado pela Skill;
- workflow nao aplicavel exige justificativa e evidencia;
- se nenhum workflow for aplicavel, registrar `no_applicable_pr_workflows=true` com evidencia, sem run ficticio e sem criar workflow;
- se um run existente estiver aguardando aprovacao manual, registrar `manual-approval-pending`, nao solicitar aprovacao e nao criar substituto.

## Ordem entre CI e handoff terminal

O pacote de readiness certifica um material head que ja passou pelos gates locais **e pela CI material terminal verde**. `pending-no-run`, `queued`, `in_progress` e `waiting` nao justificam ausencia permanente de handoff; justificam somente transferir ownership para `corrigir-ci` e continuar a mesma invocacao. Publicar o `result-only-child` terminal apenas depois de CI verde evita certificar um material que ainda pode ser alterado pela propria remediacao de CI.
