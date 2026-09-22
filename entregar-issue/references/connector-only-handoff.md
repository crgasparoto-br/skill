# Handoff em runtime connector-only

> **Escopo:** este protocolo aplica-se somente a `audit_transport=certified-handoff`. `native-github-audit` nao materializa nem publica `.audit/entregar-issue`.

## Objetivo

Garantir que ausencia de checkout Git local nao termine uma entrega funcional sem pacote de readiness. O handoff e responsabilidade de `entregar-issue` e deve ser produzido mesmo quando o repositorio so estiver acessivel por connector.

## Regra principal

`connector-only` muda a forma de obter e publicar bytes; nao relaxa coverage, saturation, inherited controls nem certificado.

Quando o candidato material estiver pronto, congelar o material e fazer a observacao inicial de CI. Se o CI estiver `pending-no-run`, `queued`, `in_progress`, `waiting` ou falhar, transferir a propriedade para `corrigir-ci` usando os mesmos connectors e continuar a invocacao. **Somente depois de CI material terminal verde**:

1. confirmar/congelar o **material head SHA verde** antes de qualquer arquivo de handoff;
2. obter por connector os bytes exatos das fontes/evidencias necessarias que ainda nao estejam no workspace do controlador;
3. materializar em diretorio efemero somente o pacote `.audit/entregar-issue` e os inputs necessarios aos validadores, sem alterar o checkout do produto;
4. gerar/atualizar `specification-snapshot.json`, `requirement-closure.json`, `requirement-attack-matrix.json`, `risk-saturation.json`, `inherited-controls.json` e closures aplicaveis com `head_sha` igual ao material head;
5. executar os validadores da propria Skill nesse workspace;
6. depois de os JSONs logicos estarem verdes, executar `scripts/pack_large_audit_artifact.py` para cada artefato acima do threshold de transporte; nunca compactar antes dos gates para esconder ou alterar conteudo;
7. gerar `handoff-ready.json` por `build_handoff_certificate.py`, ainda vinculado ao material head; o builder deve registrar hash fisico + logico e incluir manifesto/partes na allowlist;
8. publicar manifesto, partes e demais arquivos de handoff em **um unico commit filho somente de resultados**;
9. verificar que o parent desse commit e o material head e que o diff do filho contem apenas caminhos autorizados por `certificate_commit_policy.allowed_paths`;
10. registrar separadamente `material_head_sha` e `published_handoff_head_sha`; nunca reclassificar o commit de resultados como nova mudanca material;
11. depois da ultima escrita no repositorio, reconsultar o head remoto em uma chamada nova e registrar `current_head_sha`, parent e changed paths. Se `current_head_sha != published_handoff_head_sha`, consultar tambem o compare completo entre ambos e passar todos os paths via `--post-handoff-changed-path`. Executar `scripts/validate_terminal_handoff.py` passando `published_handoff_head_sha` e `current_head_sha` separadamente; nunca reutilizar a resposta da publicacao como leitura terminal; se o filho alterar `inherited-controls.json` ou `audit-escape-closure.json`, buscar essas mesmas paths no `material_head_sha`, materializar snapshots locais imutaveis e passa-los como `--material-parent-inherited-controls`/`--material-parent-audit-escape-closure`;
12. somente entao encaminhar a entrega a `auditar-issue`.

## Resultado-only child

Um certificado versionado no proprio repositorio nao pode conter o SHA do commit que o contem sem criar autorreferencia criptografica. Portanto o modelo canonico e:

```text
base ---- material M ---- handoff H
                    \\__ codigo/testes/docs congelados
                               \\__ somente .audit/entregar-issue/*
```

O certificado em `H` certifica `M`. O auditor valida que:

- `H` e filho direto de `M`;
- nenhuma alteracao de produto existe em `M..H`;
- todos os caminhos de `M..H` estao na allowlist do certificado;
- attack matrix, saturation e inherited controls continuam vinculados a `M`;
- para artefato `base64-shards-v1`, manifesto e todas as partes pertencem ao mesmo `H`, estao allowlisted e reconstroem exatamente o `logical_sha256` certificado.

CI/evidencia de produto vinculada a `M` permanece valida para o comportamento material. Checks exigidos pela politica de merge no head publicado `H` continuam sendo observados separadamente como estado remoto, sem converter `H` em novo material head.

## Substituicao de pacote herdado

Se a base trouxer `.audit/entregar-issue` de outra issue/SHA:

- tratar o pacote como historico/stale;
- nao reutilizar hashes ou conclusoes;
- nao publicar uma entrega que apenas remova o pacote antigo;
- substituir o pacote atomica e completamente pelo pacote da entrega atual no commit result-only child;
- se ainda nao houver evidencia suficiente para gerar o novo pacote, manter o handoff como pendencia interna e **nao chamar `auditar-issue`**.

## Falhas do connector

Se o connector nao permitir obter bytes exatos, executar os validadores locais ou publicar um commit de resultados:

- registrar `handoff-publication-blocked` como impedimento real da entrega;
- nao chamar auditoria independente;
- nao declarar `aprovado-internamente-pendente-auditoria-independente` como se o handoff estivesse consumivel;
- preservar o material head sem editar codigo por tentativa.

## Recuperacao apos auditoria prematura

Quando `auditar-issue` retornar `delivery-not-ready` com `return_control_to=entregar-issue` e `reason=handoff-not-produced|handoff-stale`, sem finding funcional, **nao inferir `handoff-only` apenas pelo motivo textual**.

Aplicar esta precedencia:

1. preservar `recovery_scope` e `requires_refreeze` da auditoria; `post-write-refreeze` ou `requires_refreeze=true` sao piso obrigatorio;
2. fazer leitura remota fresca do head/parent/paths e materializar o certificado corrente;
3. executar `scripts/classify_handoff_recovery.py`, passando o piso da auditoria quando existir;
4. se o resultado for `post-write-refreeze`, refazer gates dependentes do delta, gate final e freeze no head material corrente antes de reconstruir o pacote;
5. somente se o resultado for `handoff-only`, nao reabrir implementacao nem redescobrir requisitos: reconstruir/validar o pacote, publicar o result-only child e reenviar a identidade composta;
6. se o resultado for `fresh-handoff-required`, reconstruir o pacote corrente sem reutilizar artefatos estrangeiros.

A sequencia `material M -> handoff H -> commit material P` nunca e `handoff-only`, mesmo que a auditoria resuma a causa como `handoff-stale`. Um commit material de teste, documentacao ou formatacao apos H ativa `post-write-refreeze`.


## CI pendente aciona autopilot

Connector-only nao pode usar ausencia ou pendencia de workflow como atalho para terminar nem como motivo para devolver o controle ao usuario. Registrar o snapshot inicial, encerrar `delivery-snapshot` e invocar `corrigir-ci` com `ci-remediation-loop` usando o connector ate terminal. Se a remediacao publicar novo material, executar `post-write-refreeze`; depois de verde, publicar e validar o `result-only-child`. Se o connector impedir continuar a observacao ou a publicacao/verificacao do handoff, classificar o impedimento concreto e nao chamar auditoria.
