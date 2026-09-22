# Finalize after CI

## Objetivo

Fechar a entrega depois que `corrigir-ci` devolve CI material terminal, sem redescoberta e sem composicao circular. `entregar-issue` e o unico controlador terminal.

## Entrada obrigatoria

Consumir um envelope v2 validado contendo `return_control_to=entregar-issue`, `next_phase=finalize-after-ci`, `ci_owner_closed=true`, `ci_state=green`, `previous_frozen_sha`, `material_head_sha`, `recovery_hint.changed_files` e `recovery_hint.resume_from`.

Executar `scripts/finalize_after_ci_checkpoint.py --input <envelope>` antes de qualquer outro trabalho terminal.

## Fast path fechado

Depois de aceitar o checkpoint:

1. reconsultar somente identidade remota corrente (PR/head/base/merge preview);
2. se `material_head_sha` mudou desde o freeze, executar `post-write-refreeze` apenas nos descendentes invalidados pelo delta;
3. se o SHA material nao mudou, reutilizar gate final, freeze, closure, matriz/saturacao e evidencias exact-SHA ainda validas;
4. atualizar apenas os artefatos de entrega exigidos pelo perfil/remediacao e que dependem do novo SHA/finding;
5. construir localmente o `result-only-child` prospectivo e executar a simulacao terminal;
6. publicar um unico filho direto do material head contendo somente paths allowlisted;
7. fazer nova leitura remota depois da ultima escrita e executar `validate_terminal_handoff.py`;
8. se workflows forem disparados exclusivamente pelo filho result-only, observar somente esses workflows em modo observe-only; uma falha que nao toca material retorna ao pacote de handoff, nunca a discovery/implementacao.

## Proibicoes

Enquanto repository/PR/base/material_head/finding permanecerem iguais:

- nao reler integralmente issue, docs ou diff;
- nao recalcular readiness, plano, requisito closure ou risk profile;
- nao executar novamente a suite material ja verde;
- nao chamar `corrigir-ci` para recertificar o mesmo material;
- nao usar `blocked-handoff-recertification` por budget, comprimento da conversa ou simples troca de ownership;
- nao devolver o controle ao usuario entre CI verde e handoff terminal quando o runtime ainda permite executar os passos.

## Retomada

Se a invocacao for interrompida depois de CI material verde, persistir/consumir o checkpoint e retomar em `finalize-after-ci`. A palavra do usuario `Finalizar` deve selecionar este fast path quando a identidade material continuar igual; ela nunca reinicia implementacao ou CI material.

Regra anti-ping-pong: depois de aceitar o checkpoint, a sequencia `entregar -> corrigir -> entregar -> corrigir` e proibida para o mesmo material SHA.
