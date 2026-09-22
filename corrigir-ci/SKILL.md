---
name: corrigir-ci
description: Corrigir automaticamente falhas de CI/GitHub Actions em qualquer repositorio GitHub acessivel, para pull requests ou branches. Usar quando o usuario disser que a CI falhou, pipeline/checks estao vermelhos, GitHub Actions falhou, pedir para corrigir a CI, ou pedir para continuar corrigindo ate ficar verde. Resolver repositorio e SHA atuais, diagnosticar jobs/logs, aplicar correcoes, validar, publicar e observar os workflows ate estado terminal. Quando executada como subrotina de entregar-issue, possuir somente a CI material e devolver um envelope estruturado `next_phase=finalize-after-ci` ao controlador superior; nunca invocar entregar-issue recursivamente nem editar seus artefatos de handoff. Nunca fazer merge automaticamente.
---

# Corrigir CI

## Objetivo

Operar com `ci_mode=ci-remediation-loop` conforme `contracts/ci-ownership.json`. Possuir o ciclo completo de remediacao de CI em qualquer repositorio GitHub: observar -> diagnosticar -> corrigir -> validar -> publicar -> aguardar -> reobservar. Nao encerrar apenas porque um workflow ainda nao apareceu, esta `queued` ou esta `in_progress`.

Nao assumir nome, owner, branch, stack, comandos, workflow ou convencoes de um repositorio especifico. Descobrir esses dados no contexto e no proprio repositorio.

## Ownership de CI

`contracts/ci-ownership.json` e o contrato de autoridade. Neste modo, `corrigir-ci` e dona da observacao ate estado terminal; `pending-no-run`, `queued`, `waiting` e `in_progress` nao sao estados finais. `entregar-issue` nao deve executar simultaneamente seu modo snapshot para o mesmo material SHA.

Em entrega governada, drift do handoff continua definido pela identidade remota, mas a responsabilidade desta Skill termina em **CI material terminal**. Depois de CI verde, fechar `ci-remediation-loop` e devolver ao controlador superior um envelope v2 com `return_control_to=entregar-issue`, `next_phase=finalize-after-ci`, `ci_owner_closed=true`, identidade do material e `recovery_hint`. Em modo delegado e proibido invocar `entregar-issue` de volta; o caller existente executa refreeze/handoff.

## Separacao de controladores

- Tratar `corrigir-ci` como dona somente da remediacao de CI durante sua invocacao. Ela nunca escolhe nem troca o controlador da entrega.
- Quando chamada por `entregar-issue`, corrigir diretamente as causas `actionable-delivery` dentro desta Skill e devolver o envelope ao caller existente; nunca invocar `entregar-issue` recursivamente.
- Nunca invocar `orquestrador` nem criar dispatch Delivery V2. Uma CI de entrega V2 deve ser tratada pelo proprio controller V2 ou por uma invocacao standalone explicitamente solicitada, sem conversao de controlador.
- Em modo standalone, corrigir apenas a CI da PR/branch identificada e encerrar em `green-material` ou bloqueio real; nao sintetizar `return_control_to=entregar-issue` sem caller delegado.
- Skills especializadas podem ser usadas apenas para analise ou recortes de dominio que nao assumam ownership global; nenhuma delas pode substituir o caller ou iniciar outro fluxo de entrega.

## Invariantes

- Nunca fazer merge automaticamente.
- Nunca apagar arquivo sem autorizacao explicita do usuario ou de instrucoes vigentes do projeto/repo.
- Nunca criar commit vazio, mudar SHA artificialmente ou editar workflow apenas para retriggerar CI.
- Nao rerodar, cancelar ou aprovar workflow manualmente por padrao.
- Nao alterar secrets, variables, branch protection, required checks ou environments.
- Nao mascarar falha de infraestrutura com mudanca de codigo sem relacao causal.
- Trabalhar sempre sobre o head atual da PR/branch; reconsultar o head imediatamente antes de qualquer escrita.
- Agrupar todas as falhas irmas baratas da mesma execucao antes de editar, evitando um commit por sintoma.
- Considerar verde somente evidencia do SHA exato que permanece como head atual.
- Respeitar `AGENTS.md`, `CONTRIBUTING`, README, convencoes versionadas e instrucoes especificas do repositorio antes de editar.
- Quando a branch/PR pertencer a uma entrega governada por `entregar-issue`, tratar qualquer novo `head_sha` material apos freeze/handoff como invalidacao automatica do freeze e de `.audit/entregar-issue/handoff-ready.json`, independentemente de autoria. Antes de considerar um certificado aplicavel, executar `scripts/validate_handoff_target_binding.py` contra `repository`, PR/work item, `base_ref` e `head_ref` conhecidos; apenas `TARGET_BINDING: current-target` pode ativar `governed_handoff_observed=true`. `foreign-target` ou `unbound-or-invalid` devem ser ignorados como evidencia desta entrega e nunca ativar o latch.
- Nunca editar, copiar, corrigir ou regenerar diretamente `.audit/entregar-issue/*`; esses artefatos pertencem a `entregar-issue`.
- Em entrega governada delegada, `ci-green` apos commit material e estado de **retorno ao controlador**, nao estado terminal da entrega. Gerar/validar o envelope v2 e encerrar a propriedade de CI; nao produzir handoff e nao chamar outra Skill.
- Nunca editar, copiar, corrigir ou regenerar `.audit/entregar-issue/*`; a recertificacao terminal pertence ao caller `entregar-issue`.
- `stale-after-ci-fix` pode aparecer apenas como diagnostico no envelope. Quando a correção alterar o head material após o freeze, retornar `reason=post-ci-refreeze` junto com `next_phase=finalize-after-ci`; a Skill nao tenta resolve-lo por composicao recursiva e informa o controlador superior.

## Resolver o repositorio

Resolver a identidade sem hardcode, nesta ordem:

1. Usar repositorio/PR/branch explicitamente fornecido pelo usuario.
2. Usar URL GitHub, numero de PR, branch ou repo ja identificado no contexto da conversa.
3. Usar o repositorio ativo do projeto/conversa quando houver exatamente um candidato claro.
4. Consultar GitHub para localizar PR/branch recente e relevante quando a mensagem for apenas "CI falhou".
5. Se houver multiplos candidatos igualmente plausiveis e nenhuma evidencia permitir escolher com seguranca, pedir apenas o minimo necessario para desambiguar.

Depois de resolver, capturar pelo menos:

- `repository_full_name`;
- PR, quando existir;
- branch head;
- branch base, quando existir;
- `head_sha` atual;
- workflow/checks aplicaveis ao SHA.

## Fluxo obrigatorio

1. Resolver a identidade atual.
   - Aplicar a ordem de descoberta acima.
   - Se houver contexto anterior com PR/branch conhecido, reutilizar e apenas confirmar o head atual.
   - Nao assumir que a branch principal se chama `main`.
   - Detectar imediatamente se existe handoff candidato de `entregar-issue` e validar seu subject com `scripts/validate_handoff_target_binding.py` usando a identidade remota atual. Somente `current-target` e handoff aplicavel; nesse caso registrar `governed_handoff_observed=true`, `certified_material_head_sha` e a identidade publicada observavel. `foreign-target`/`unbound-or-invalid` nao governam esta rodada e exigem handoff fresco da `entregar-issue` se a entrega atual vier a ser governada. O latch verdadeiro nao pode voltar a `false` porque a proxima escrita veio de outro ator.

2. Descobrir as regras do repositorio.
   - Ler instrucoes versionadas relevantes antes de editar (`AGENTS.md`, `CONTRIBUTING*`, docs de desenvolvimento, scripts do package/build system e workflow falho).
   - Derivar os comandos reais de formatacao, lint, typecheck, testes e build do repositorio; nao reutilizar comandos de outro projeto.

3. Observar a CI do `head_sha`.
   - Buscar workflow runs/checks associados ao SHA.
   - Se ainda nao houver run, continuar observando; nao concluir `pending-no-run` como resultado final.
   - Se houver run `queued`, `waiting` ou `in_progress`, continuar observando ate estado terminal.
   - Entre observacoes, usar espera moderada quando o ambiente oferecer mecanismo de espera; nunca fazer hot-loop de API.

4. Quando um run terminar com falha, coletar diagnostico completo da rodada.
   - Listar todos os jobs.
   - Para cada job falho, identificar o step falho e ler os logs existentes.
   - Agrupar mensagens por causa raiz.
   - Classificar cada causa como:
     - `actionable-delivery`: corrigivel no codigo, testes, schema, config ou documentacao versionada do candidato;
     - `external-infrastructure`: runner, indisponibilidade externa, segredo ausente, rate limit, permissao ou servico fora do escopo;
     - `unrelated-preexisting`: falha comprovadamente anterior e fora do diff/entrega.

5. Remediar todas as causas `actionable-delivery` da rodada.
   - Preferir o menor patch coeso e corrigir diretamente dentro desta Skill seguindo as convencoes do repositorio.
   - Nunca invocar `entregar-issue` ou `orquestrador` para executar a remediacao; esta Skill ja possui o recorte de implementacao necessario para corrigir a causa da CI e deve preservar o caller original.
   - Usar `revisar-issue` somente se uma ambiguidade material impedir a correcao.
   - Usar `design-interface`, `fluxos-conversacionais` ou `documentacao-repositorio` apenas quando a falha exigir a especialidade correspondente, sem transferir ownership global ou criar novo fluxo de entrega.
   - Se ja existir freeze/handoff e o head remoto passar a uma identidade material nao coberta pelo certificado, registrar desde este ponto que um fast path `post-ci-refreeze` sera obrigatorio depois de a CI material ficar verde; nao importa qual ator publicou a mudanca e nao permitir resposta final antes disso.
   - Nao adotar a regra de encerrar por `pending-no-run` de outra skill: esta skill continua esperando por design.

6. Validar antes de publicar.
   - Executar checks focados que reproduzam os steps falhos.
   - Quando o ambiente permitir checkout executavel, executar tambem o gate agregado afetado antes do commit.
   - Para falha de formatacao, executar o formatador real e depois o check real; nunca inferir manualmente a saida se o binario/config do projeto estiver disponivel.
   - Para lint/typecheck/test/build, executar o comando exato ou equivalente versionado no workflow.
   - Respeitar package manager, runtime, monorepo tooling e versoes travadas pelo repositorio.
   - Se o ambiente local nao suportar o gate, registrar a limitacao sem inventar sucesso; publicar apenas quando a correcao estiver fundamentada por evidencia suficiente.

7. Publicar uma correcao material.
   - Reconsultar o head imediatamente antes da escrita.
   - Se o head mudou externamente, reconciliar o delta e nao sobrescrever trabalho novo.
   - Criar um unico commit coeso por rodada de causa raiz quando possivel.
   - Atualizar a branch existente da PR; nao abrir PR paralela sem necessidade.
   - Nao fazer merge.

8. Aguardar a nova CI automaticamente.
   - Capturar o novo `head_sha` apos a publicacao.
   - Continuar observando ate os workflows/checks aplicaveis desse SHA terminarem.
   - Nao pedir ao usuario para voltar depois, nao pedir confirmacao e nao encerrar voluntariamente apenas por estado pendente.
   - Se o host/runtime interromper inevitavelmente a execucao, retornar estado `interrupted-by-runtime`, com repo, PR/branch, SHA e ultimo estado observado. Em nova invocacao, retomar desse SHA sem repetir diagnostico/patch ja aplicado.

9. Fechar a propriedade de CI apos material verde.
   - Reconsultar o head remoto e confirmar que o SHA observado como verde ainda e o head material corrente.
   - Se a entrega foi delegada por `entregar-issue`, nao executar refreeze, nao publicar `result-only-child` e nao chamar `entregar-issue`.
   - Construir `delivery-recovery-envelope` schema 2 com `return_control_to=entregar-issue`, `next_phase=finalize-after-ci`, `ci_owner_closed=true`, `previous_frozen_sha`, `material_head_sha`, `ci_state=green` e `recovery_hint`.
   - Para mudanca de codigo executavel, usar `recovery_hint.material_change=true`, `code_growth_recheck=true` e `resume_from=hygiene`; sem mudanca material desde o freeze, usar `material_change=false` e `resume_from=handoff|freeze`.
   - Executar `scripts/validate_delivery_recovery_envelope.py` e retornar o envelope ao controlador. Esse retorno e a unica transicao permitida; nenhum callback de Skill e executado daqui.
   - Consultar `references/handoff-recertification.md` para o contrato de fronteira, nao para assumir ownership do handoff.

10. Repetir somente enquanto a CI material nao estiver terminal.
   - Se a nova CI falhar, voltar ao diagnostico e corrigir todas as causas acionaveis da rodada.
   - Se o head material mudar por uma correcao, acompanhar a CI do novo SHA.
   - Quando o SHA material estiver terminal verde, fechar ownership e devolver o envelope uma unica vez.

## Condicoes finais

### `green-material`

Declarar quando:

- a PR/branch continua apontando para o SHA material observado;
- todos os workflows/checks aplicaveis ao SHA material terminaram verdes, com skips esperados aceitos;
- nao existe job/check material falho, cancelado ou aguardando aprovacao obrigatoria;
- o envelope schema 2 foi validado;
- em modo delegado, `ci_owner_closed=true` e `next_phase=finalize-after-ci`.

`green-material` e sucesso da subrotina de CI, nao aprovacao operacional da entrega. Em contexto delegado, nao executar latch de handoff nesta Skill.

### `blocked-external`

Usar quando nao existir correcao versionada legitima para deixar o CI material verde, por exemplo segredo obrigatorio ausente, indisponibilidade persistente de servico externo ou permissao de runner. Informar repo, job, step e trecho causal do log. Nao criar commit artificial para retriggerar.

### `unrelated-preexisting`

Usar apenas com evidencia de baseline suficiente de que a falha antecede e independe do candidato. Nao corrigir fora do escopo silenciosamente.

### `interrupted-by-runtime`

Usar apenas quando o ambiente realmente impedir continuar esperando/executando a CI material. Nao chamar isso de sucesso. Fornecer a identidade exata para retomada automatica.

## Politica de espera

Consultar `references/ci-loop.md` para regras de observacao, retomada e prevencao de polling agressivo.

## Saida

Manter atualizacoes curtas durante ciclos longos. Ao final, responder com:

- status final;
- repositorio;
- PR e branch, quando aplicaveis;
- SHA verde ou bloqueado;
- causas encontradas por rodada;
- commits de remediacao;
- checks/workflows finais;
- material head final da CI;
- envelope validado (`return_control_to`, `next_phase`, `ci_owner_closed`, `previous_frozen_sha`, `material_head_sha`, `recovery_hint`);
- estado de handoff observado apenas como contexto (`not-applicable|stale-after-ci-fix|unchanged-exact-head`), sem tentar recertifica-lo;
- impedimento real, se houver.

Nao declarar "corrigido" enquanto a CI do SHA final ainda estiver pendente. Em modo delegado, nao declarar a **entrega** corrigida; declarar apenas `green-material` e devolver o envelope ao controlador `entregar-issue`, que possui o fechamento terminal.
