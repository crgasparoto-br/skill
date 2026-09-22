# Loop de observacao de CI

## Proposito

Garantir que `corrigir-ci` permaneça dono do ciclo remoto ate um estado terminal comprovado em qualquer repositorio GitHub, sem gerar carga desnecessaria ou commits artificiais.

## Identidade

A unidade de observacao e sempre `(repository_full_name, PR/branch, head_sha)`. Qualquer mudanca de head invalida o estado remoto anterior e inicia uma nova rodada de observacao.

Nunca carregar identidade de outro repositorio apenas porque ele foi usado em uma execucao anterior da skill.

## Cadencia

- Preferir intervalos moderados entre observacoes quando houver mecanismo de espera no ambiente.
- Como referencia, usar aproximadamente 15-30 segundos para jobs curtos e 30-60 segundos para suites longas.
- Nunca consultar continuamente sem intervalo apenas para acelerar o resultado.
- Ler jobs/logs repetidamente somente quando o run ou attempt mudou; enquanto apenas o status temporal muda, uma consulta de estado e suficiente.
- Nao encerrar voluntariamente por `queued`, `waiting`, `in_progress` ou ausencia momentanea de run.

## Run inexistente

Um push pode preceder a criacao do run. Quando nao houver run para o SHA:

1. confirmar que o SHA ainda e o head;
2. aguardar;
3. consultar novamente;
4. continuar ate o run aparecer ou surgir um impedimento real de trigger.

Nao criar commit vazio para provocar um novo run.

## Run em andamento

Para `queued`, `waiting` ou `in_progress`, aguardar e reconsultar. Nao produzir conclusao final intermediaria.

## Run terminal

- `success`: verificar os demais workflows/checks aplicaveis ao mesmo SHA antes de declarar `green`.
- `failure`: coletar jobs e logs da tentativa concluida e reabrir remediacao.
- `cancelled`: tratar como nao verde; investigar se ha causa acionavel ou externa antes de decidir.
- `action_required`/aprovacao: nao aprovar automaticamente; classificar como bloqueio operacional quando for requisito real.

## Multiplos workflows

Um SHA pode disparar mais de um workflow. Nao declarar `green` ao observar apenas o primeiro sucesso.

1. Inventariar workflows/checks aplicaveis ao SHA.
2. Aguardar todos os obrigatorios/aplicaveis chegarem a estado terminal.
3. Se qualquer um falhar, diagnosticar a rodada completa antes de editar.
4. Se um workflow novo aparecer enquanto outros ja terminaram, inclui-lo na mesma avaliacao do SHA.

## Retomada

Se a execucao for interrompida pelo host:

1. reabrir o repositorio e PR/branch corretos;
2. ler o head atual;
3. se for o mesmo SHA, continuar observando sem repetir o patch anterior;
4. se o SHA mudou, diagnosticar apenas o delta remoto novo.

A retomada e stateless: o GitHub e a fonte de verdade para repo, head, runs, jobs e logs.


## Integracao com freeze/handoff de entrega

Quando `corrigir-ci` atuar sobre uma PR/branch governada por `entregar-issue`, a unidade de identidade inclui o vinculo entre `head_sha` e o certificado observado, mas isso nao transfere ownership do handoff.

- Ao atingir CI verde material, reconsultar o head e fechar a propriedade de CI.
- CI verde do novo SHA comprova somente os checks daquele SHA; nao libera auditoria por si só e deve proibir encaminhamento a `auditar-issue` ate que `entregar-issue` refaça o refreeze e o handoff terminal.
- Produzir envelope schema 2 com `next_phase=finalize-after-ci` e `ci_owner_closed=true`.
- `entregar-issue` e o unico owner autorizado a revalidar artefatos dependentes, refazer freeze e gerar novo `handoff-ready.json`.
- Nunca invocar `entregar-issue` de dentro da subrotina; devolver ao caller existente.
- Consultar `handoff-recertification.md` para a fronteira de ownership.

Esse protocolo evita que uma correcao de CI tecnicamente correta produza uma divergencia de identidade entre o candidato verde e o pacote de auditoria.

## Uso de skills compostas

Skills de implementacao podem corrigir uma causa acionavel, mas nao devem possuir o loop remoto. Depois do patch/validacao/publicacao, retornar o controle a `corrigir-ci` para aguardar o novo workflow e decidir o proximo ciclo.

Skills compostas nunca podem impor um repositorio padrao a `corrigir-ci`; a identidade resolvida por esta skill prevalece.
