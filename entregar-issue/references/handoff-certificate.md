# Certificado de handoff independente

## Quando ler este arquivo

Ler quando for produzir ou consumir o certificado de handoff independente, inclusive drift pós-freeze e runtime connector-only.

## Índice

- [Objetivo](#objetivo)
- [Regra](#regra)
- [Preflight contra pacote herdado](#preflight-contra-pacote-herdado)
- [Vinculo semantico do alvo](#vinculo-semantico-do-alvo)
- [Identidade material e commit de resultados](#identidade-material-e-commit-de-resultados)
- [Proveniencia](#proveniencia)
- [Regra de consumo](#regra-de-consumo)
- [Runtime connector-only](#runtime-connector-only)
- [Drift pos-freeze e remediacao de CI](#drift-pos-freeze-e-remediacao-de-ci)
- [Gate pre-publicacao do produtor](#gate-pre-publicacao-do-produtor)
- [Gate terminal do produtor](#gate-terminal-do-produtor)
- [Transporte de artefatos grandes](#transporte-de-artefatos-grandes)

## Objetivo

Impedir que uma auditoria independente seja consumida para descobrir ausencia de artefatos de readiness que a entrega ja consegue verificar de forma deterministica, sem criar autorreferencia entre o certificado versionado e o SHA do commit que o contem.

## Regra

Nenhum handoff para auditoria independente existe sem `.audit/entregar-issue/handoff-ready.json` valido para o candidato material.

O certificado deve ser produzido por `scripts/build_handoff_certificate.py` somente depois de:

- cobertura integral da especificacao validada contra as fontes canonicas;
- requirement closure valida;
- requirement attack matrix completa;
- risk saturation completa;
- inherited controls completos no SHA material final;
- audit escape closure completa quando houver rejeicao independente anterior;
- learning closure completa quando houver rejeicao independente anterior;
- identidade material final congelada;
- `codebase-grounding.json` com `validate_codebase_grounding.py` em `READY` quando o escopo local da issue tocar codigo; passar `--codebase-grounding` ao builder, que bloqueia a ausencia ou o SHA stale e registra `controls.codebase_grounding.applicable`;
- relatorio `CODE-GROWTH-001` em `passed` no mesmo caso, passado ao builder com `--code-growth`.

## Preflight contra pacote herdado

Antes do builder, executar `scripts/delivery_target_binding.py` ou usar `artifact_reuse` do controller context. Se o pacote existente for de outro alvo, ele nao e entrada valida do builder nem candidato a `handoff-only`; reconstruir os artefatos atuais e emitir certificado novo. Esse preflight cobre explicitamente branches que herdam `.audit/entregar-issue` da base sem tocar nesses arquivos durante a implementacao material. Quando `base_sha` estiver disponivel, provar a heranca por igualdade de bytes contra o commit base exato; em connector-only, materializar os mesmos paths da base e usar `--base-audit-dir`. Um artefato estrangeiro alterado no head continua `foreign-target`.

## Vinculo semantico do alvo

O certificado deve provar nao apenas a identidade Git, mas tambem **qual entrega** ele representa. `build_handoff_certificate.py` grava `subject.issue_number` e `subject.pull_request_number` separadamente, alem dos aliases de compatibilidade `work_item_kind/work_item_number/pull_request`, `base_ref` e `head_ref`. `specification-snapshot.issue` deve sempre corresponder a `subject.issue_number`, inclusive quando a invocacao foi `PR #N`; o numero da PR nunca substitui o numero da issue.

O certificado deve ainda conter `scope.work_item_start_sha`, `scope.material_head_sha`, `scope.issue_changed_paths` e `scope.issue_delta_sha256`, calculados sobre o delta da issue. Essa fronteira separa alteracoes produzidas pela entrega corrente de alteracoes historicas acumuladas na PR.

O gate terminal deve repetir a verificacao contra o subject da invocacao e contra o snapshot certificado. Isso impede que um pacote `.audit/entregar-issue` herdado da base ou de outra PR seja aceito apenas porque seus hashes internos continuam consistentes.

## Identidade material e commit de resultados

O certificado schema v2 usa `identity.material_head_sha` como identidade do codigo/testes/docs auditados. `identity.head_sha` permanece apenas como alias de compatibilidade para esse mesmo SHA material.

Quando o certificado for persistido no repositorio, publicar o pacote em um **filho direto somente de resultados** do material head. O certificado declara:

```json
{
  "schema_version": 2,
  "identity": {
    "material_head_sha": "<M>",
    "head_sha": "<M>",
    "base_sha": "<B>",
    "material_merge_preview_sha": "<MP-M>"
  },
  "certificate_commit_policy": {
    "mode": "result-only-child",
    "allowed_paths": [".audit/entregar-issue/..."]
  }
}
```

O SHA do filho de handoff `H` nao aparece dentro do certificado. O auditor aceita `H` somente se comprovar que:

- `parent(H) == M`;
- o diff `M..H` contem apenas `allowed_paths`;
- nenhum arquivo material do produto mudou;
- os artefatos certificados continuam hasheados e vinculados a `M`.

Isso evita a impossibilidade de fazer um arquivo versionado certificar o proprio SHA do commit que o contem.

## Proveniencia

O certificado deve registrar hashes dos artefatos, identidade material do candidato, versao contratual, hash da Skill produtora e hashes dos validadores usados. Alteracao de qualquer input material invalida o certificado.

## Regra de consumo

`auditar-issue` deve validar o certificado antes de iniciar descoberta ampla ou suites caras. Certificado ausente, stale ou inconsistente implica `delivery-not-ready`, nao uma nova auditoria ampla.

Em `result-only-child`, o auditor deve validar parent e changed paths do head publicado antes de usar o material head certificado para saturation, inherited controls e reauditoria.

## Runtime connector-only

Ausencia de checkout local nao autoriza omitir o certificado. Seguir `references/connector-only-handoff.md`: materializar os bytes necessarios em workspace efemero, executar os validadores da Skill, gerar o certificado e publicar um unico commit de resultados. Se isso for impossivel por limite real do connector, bloquear o handoff internamente e nao consumir auditoria independente.

## Drift pos-freeze e remediacao de CI

Mudanca **material** posterior ao freeze torna o certificado anterior historico/stale, inclusive remediacao por `corrigir-ci`, formatacao, documentacao, teste ou mudanca colateral fora da allowlist de resultados.

Quando `corrigir-ci` alterar o head material depois de um handoff:

1. `corrigir-ci` nao pode editar ou regenerar `.audit/entregar-issue/*`;
2. deve retornar controle com `reason=post-ci-refreeze`, SHA material congelado anterior e head atual;
3. `entregar-issue` deve comparar o delta e invalidar somente evidencias dependentes, mas sempre refazer a identidade material congelada;
4. executar novamente validadores afetados no novo material head;
5. gerar e validar novo `handoff-ready.json` para o novo material head;
6. publicar novo result-only child;
7. somente entao permitir novo consumo por `auditar-issue`.

Um commit que seja comprovadamente o result-only child autorizado nao e drift material e nao exige refazer os gates de produto vinculados ao parent material.


## Gate pre-publicacao do produtor

Antes de mover o ref remoto para um filho de resultados, gerar o certificado final e montar localmente o commit/arvore exatos, inclusive manifests/shards. Executar `validate_terminal_handoff.py` contra esse filho local sintetico com `published_head_sha == current_head_sha`, parent igual ao material e changed paths prospectivos. A simulacao deve usar os mesmos snapshots historicos e do material parent exigidos no guard real. Falha local nao autoriza publicacao parcial nem abertura de outra PR: corrigir o pacote localmente e repetir a simulacao.

Quando a correcao for exclusivamente de um handoff stale na mesma PR, executar tambem `validate_result_only_pr_recovery.py`; somente um resultado que preserve o mesmo material e exclua paths materiais pode autorizar a troca estreita do ref entre filhos irmaos.

## Gate terminal do produtor

Gerar o certificado localmente nao basta. Em reauditoria apos rejeicao independente, o builder e o terminal guard devem receber os snapshots imutaveis anteriores de `inherited-controls.json` e `audit-escape-closure.json` e reexecutar a validacao semantica cumulativa sobre os artefatos publicados finais. O certificado nao pode ser emitido quando `learning-closure.json` identificar uma rejeicao independente cujo `rejection_id` ou `finding_ids` nao estejam explicitamente fechados em `audit-escape-closure.json`. Antes de retornar ao usuario, `entregar-issue` deve guardar o SHA do result-only child como `published_handoff_head_sha`, fazer uma **nova** leitura remota depois da ultima escrita e passar tambem `current_head_sha`, parent e changed paths a `scripts/validate_terminal_handoff.py`; se o head tiver movido, passar ainda o compare completo `published_handoff_head_sha..current_head_sha` para provar todo o delta posterior ao handoff. O gate exige `current_head_sha == published_handoff_head_sha` e falha quando subject/snapshot pertencem a outro alvo, quando o handoff publicado ainda e o material head, quando o filho nao tem o material head como parent, quando `handoff-ready.json` nao faz parte do commit de resultados, quando existe path fora da allowlist ou quando qualquer commit posterior moveu o head. Se a observacao corrente trouxer path material, a recuperacao obrigatoria e `post-write-refreeze`. CI pendente nao relaxa esse gate, mas adia a publicacao terminal do certificado: transferir ownership para `corrigir-ci`, obter CI material verde e somente entao publicar/validar o handoff.


## Transporte de artefatos grandes

O certificado schema v2 pode registrar `artifact_transport.version=1`. Cada entrada de `artifacts` deve manter `sha256` do arquivo fisico e `logical_sha256`/`logical_size` do JSON reconstruido. Para `base64-shards-v1`, registrar tambem compression, sizes, decoded hash e parts; todas as parts entram automaticamente em `certificate_commit_policy.allowed_paths`. Em reauditoria, certificar tambem `audit-remediation.json` e `audit-source-result.json`.
