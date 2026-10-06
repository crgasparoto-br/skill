# Preflight de certificado de handoff

> **Escopo:** este preflight e obrigatorio somente quando `audit_transport=certified-handoff`. Antes dele, resolver o transporte por `references/native-github-audit-contract.md`. Em `native-github-audit`, ausencia de `.audit/entregar-issue` nao e blocker.

## Objetivo

Evitar gastar auditoria independente em pacote sem readiness e validar corretamente o `result-only-child`.

## Regra

Antes de descoberta ampla, resolver `.audit/entregar-issue/handoff-ready.json` no head e no SHA imutavel da base. Se ambos existirem, comparar bytes/blob Git antes de atribuir o arquivo ao candidato. Depois validar o pacote corrente com `<AUDIT_SKILL_ROOT>/scripts/check_delivery_preflight.py`; no fluxo por bytes, passar `--base-certificate` quando o caminho existir na base.
O agregador deve resolver o validador de certificado pelo root instalado da Skill em `<AUDIT_SKILL_ROOT>/scripts/validate_handoff_certificate.py`; nunca procurar esse script no repositorio auditado.

Validar sempre:

- versao contratual e proveniencia da Skill produtora;
- `evidence_profile=light|standard|critical` (ausente em certificado legado => `critical`);
- hashes dos artefatos exigidos pelo perfil;
- identidade material, target semantico e politica de publicacao;
- `CODE-GROWTH-001` quando certificado como aplicavel.

Artefatos por perfil:

- `light`: `specification_snapshot` + `requirement_closure` e controles especializados explicitamente certificados;
- `standard`: acima + `standard_evidence` exact-material-head;
- `critical`: acima + `requirement_attack_matrix`, `risk_saturation`, `inherited_controls` e artefatos especializados aplicaveis;
- qualquer perfil cujo `scope.issue_changed_paths` toque codigo: `codebase_grounding` exact-material-head; a aplicabilidade e recalculada do escopo certificado e nao pode ser rebaixada pelo certificado;
- rejeicao independente anterior: sempre exigir `audit_remediation` + `audit_source_result`; usar perfil de risco real. Exigir `critical` + `audit_escape_closure` + `learning_closure` + historico somente quando `remediation_mode=systemic-remediation|mixed-remediation`.

## Artefato herdado da base

Um `handoff-ready.json` presente no head nao e automaticamente handoff da entrega corrente. Quando o mesmo caminho ja existir no SHA imutavel da base:

1. comparar o objeto do head com o objeto da base por bytes exatos ou `git_blob_sha`;
2. se forem identicos e o `subject` pertencer a outro target, classificar `inherited-base-artifact`;
3. nao executar o preflight semantico desse pacote como se tivesse sido produzido pela PR atual;
4. considerar que o handoff do target atual **nao foi produzido**: `delivery-not-ready`, `reason=handoff-not-produced`;
5. usar `recovery_scope=handoff-only` quando o material head atual permanece estavel e nao ha escrita material posterior que exija novo freeze;
6. reservar `fresh-handoff-required` para certificado estrangeiro efetivamente introduzido/alterado pela entrega corrente ou para target estrangeiro que nao seja simples estado herdado da base.

A igualdade deve ser estabelecida contra SHA imutavel da base, nunca contra branch mutavel. Nome/caminho iguais sem igualdade de bytes/blob nao comprovam heranca.

## Result-only child

Para schema v2, o modelo canonico e `base -> material M -> handoff H`. O certificado em `H` certifica `M`.

1. Ler `identity.material_head_sha=M`.
2. Obter remotamente parent e changed paths de `H`.
3. Exigir `parent(H) == M` e somente paths de `certificate_commit_policy.allowed_paths`.
4. Usar `M` como SHA das evidencias materiais e `H` como `published_handoff_head_sha`.
5. Path material, parent divergente ou target estrangeiro invalida o certificado.

A igualdade `parent(H) == M` e a `allowed_paths` sao invariantes do handoff terminal. Nao aceitar equivalencia narrativa, hash de arquivo isolado ou descricao da PR como substituto da relacao Git observada remotamente.

## Falha e recuperacao

- handoff do target atual nao produzido, inclusive quando o unico arquivo encontrado e um `inherited-base-artifact`, com material head ainda corrente: `handoff-only`;
- material head ainda corrente e falta somente pacote/filho terminal: `handoff-only`;
- houve escrita material posterior: `post-write-refreeze`, `requires_refreeze=true`;
- subject/target pertence a outra entrega: `fresh-handoff-required`.

Quando o resultado for `delivery-not-ready` por ausencia ou staleness do certificado em `delivery_origin=direct-entregar-issue`, devolver `return_control_to=entregar-issue` e distinguir o motivo: `reason=handoff-not-produced` quando o pacote nao foi publicado e `reason=handoff-stale` quando o pacote existe mas nao cobre mais a identidade corrente. Nunca usar `handoff-only` quando houver drift material; nesse caso exigir `post-write-refreeze`. Se a CI exact-SHA do `material_head_sha` corrente ja estiver terminal verde, incluir `next_phase=finalize-after-ci`; isso permite que `entregar-issue` retome diretamente o fechamento terminal, preservando o `recovery_scope` como piso de recuperacao. Para `delivery_origin=delivery-v2`, nao emitir `return_control_to=entregar-issue`; preservar ownership do controller V2. `auditar-issue` nunca deve chamar `corrigir-ci` para recertificar o mesmo material SHA.

Nao iniciar suite cara quando o certificado falhar. O certificado e indice de readiness, nao conclusao da auditoria.

## Runtime e CI

Incapacidade exclusiva do runtime de materializar/rodar o validador e `audit-runtime-limitation` (`INCONCLUSIVA`), nao finding da issue.

CI pendente nao substitui certificado: o handoff deve existir antes do retorno da entrega. Com certificado valido e CI ainda pendente, seguir normalmente para o preflight de gates e classificar o estado remoto de forma separada; sem certificado, manter `delivery-not-ready`.

## Artefatos transport-sharded

Quando uma entrada certificada declarar `artifact_transport.format=base64-shards-v1`, validar o manifesto e todas as partes via `scripts/audit_artifact_io.py`, comparar `sha256` fisico e `logical_sha256`, e somente entao executar os gates semanticos. Parte ausente/adulterada e `delivery-not-ready`; incapacidade exclusiva do runtime de obter a parte e `audit-runtime-limitation`.

## Issue-local scope

Quando o certificado declarar `scope`, obter por fonte remota o compare `scope.work_item_start_sha..identity.material_head_sha` e exigir igualdade exata com `scope.issue_changed_paths` e com `scope.issue_delta_sha256`. Separar esse conjunto do diff amplo da PR. `subject.issue_number` deve corresponder ao snapshot; `subject.pull_request_number` deve corresponder a PR auditada. PR e issue sao identidades diferentes mesmo quando a invocacao original foi feita pelo numero da PR.
