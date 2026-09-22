# Gate remoto por SHA

## Coleta

Usar `collect_remote_gate.py` em modo somente leitura. O script deve consultar o GitHub por `gh api` ou REST autenticada, guardar payloads brutos paginados, timestamps, hash do proprio coletor e hashes dos payloads. Campos derivados de estado remoto nao devem ser preenchidos manualmente. `--fixture-dir` existe somente para testes e snapshots com `source=fixture` nao podem aprovar um gate real. Nao disparar, reexecutar, cancelar ou aprovar workflow durante a coleta.

Coletar e reconstruir:

- PR antes e depois: head, base, estado, mergeabilidade e merge preview;
- todos os runs do SHA antes e depois;
- jobs e steps de cada workflow aplicavel;
- artefatos de todos os runs bem-sucedidos do SHA e seus ZIPs;
- handoff rastreavel da issue na PR.

Depois das validacoes locais, `validate_internal_gate.py` deve consultar novamente o GitHub. Essa reconsulta seleciona novamente o ultimo run elegivel por workflow, inspeciona jobs, steps, inventario e conteudo dos artefatos e o handoff. Novo run falho, pendente, substituto ou divergente invalida o resultado.

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

## Proveniencia reconstruivel

Cada payload bruto deve registrar label conhecida, endpoint exato, caminho, hash e horario. O validador deve reconstruir PR, runs, jobs, handoff e artefatos a partir desses arquivos e comparar com o snapshot. Declarar `source=gh-api` ou guardar `{}` nao comprova coleta.

## Base e merge preview

Exigir:

- `head_sha_before == head_sha_after == SHA congelado`;
- `base_sha_before == base_sha_after == metadata.base_sha`;
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

## Artefatos remotos

Coletar artefatos produzidos por runs existentes como evidencia adicional. Nao criar ou alterar workflow apenas para publicar artefato.

Artefato remoto e obrigatorio somente quando o perfil declarar explicitamente `audit_packet_published=true`; nesse caso, exigir kind `audit-manifest`. Evidencias visual, de persistencia, migration e documentacao devem ser produzidas e atestadas localmente e podem ser complementadas por artefatos remotos ja existentes.

Cada artefato considerado deve pertencer a run concluido com sucesso no SHA final e possuir digest GitHub. O run pode usar outro evento somente quando o artefato nao estiver substituindo workflow obrigatorio de PR.

O ZIP deve conter exatamente um `orquestrador-artifact.json`, `schema_version: 2`, com:

- kind, `head_sha`, run ID, artifact ID, gerador e timestamp;
- checks estruturados com IDs e claims;
- resultados internos nao vazios;
- caminho, SHA-256, tamanho, comando, exit codes, media type e IDs dos checks de cada resultado;
- ligacao bidirecional entre checks e resultados.

O coletor reabre o ZIP e recalcula tudo. Nome, heuristica, texto autodeclarado ou `--artifact-kind` nunca atribuem significado.


## Ordem entre CI e handoff terminal

O pacote de readiness certifica um material head que ja passou pelos gates locais **e pela CI material terminal verde**. `pending-no-run`, `queued`, `in_progress` e `waiting` nao justificam ausencia permanente de handoff; justificam somente transferir ownership para `corrigir-ci` e continuar a mesma invocacao. Publicar o `result-only-child` terminal apenas depois de CI verde evita certificar um material que ainda pode ser alterado pela propria remediacao de CI.
