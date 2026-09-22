# Contrato de composicao

## Propriedade

`entregar-issue` possui identidade, ciclo, plano, estado, work items, implementacao, higiene, gates, freeze, publicacao e decisao. Nenhuma Skill composta pode recriar esses artefatos ou encerrar a entrega.

## Skills externas permitidas

- `revisar-issue`: somente para lacuna material de readiness;
- `documentacao-repositorio`: somente para impacto documental amplo;
- `design-interface`: somente para recorte visual material;
- `fluxos-conversacionais`: somente para continuidade assincrona material;
- `auditar-issue`: verificacao somente leitura; independente apenas em contexto separado.
- `corrigir-ci`: owner temporario **somente da CI material** durante a fase remota do ciclo principal. `entregar-issue` permanece o controlador de nivel superior, faz no maximo o snapshot inicial e delega observacao/remediacao quando o run nao estiver terminal verde. Em modo delegado, `corrigir-ci` nunca invoca `entregar-issue`, nunca edita `.audit/entregar-issue/*` e nunca decide handoff; ao fechar CI material devolve um unico envelope `next_phase=finalize-after-ci` ao controlador ja existente.

## Envelope

Toda delegacao recebe contrato, requisitos, caminhos, identidade, `input_fingerprint`, write ownership, `mode` e `phase`. Toda resposta inclui `contract_version`, `input_fingerprint`, `reused`, findings, validacoes, artefatos e caminhos alterados. Para `design-interface` no fluxo padrao, usar `guidance/pre-implementation` e `internal-verification/post-implementation`; nunca condensar as duas fases em uma validacao tardia. Para `corrigir-ci`, usar `mode=ci-remediation-loop`, transferir explicitamente a propriedade antes da primeira reobservacao e nao manter `delivery-snapshot` ativo em paralelo. O retorno fecha a propriedade de CI (`ci_owner_closed=true`) e devolve o fluxo ao mesmo controlador; composicao recursiva e proibida.

## Escrita

Definir um unico `write_owner` por caminho antes da chamada. Skills externas nao podem editar caminhos pertencentes ao nucleo e vice-versa. Quando a especialidade apenas verifica, usar modo somente leitura.

## Reuso

Para `reuse-candidate`, conferir fonte, hash, fingerprint, identidade, schema e artefato. Falha em qualquer verificacao converte a acao em `run`.

## Compatibilidade

Skills legadas nao participam do fluxo. O modo antigo e aceito apenas como alias de entrada; novos artefatos usam `delivery-single-invocation` e `return_control_to=entregar-issue`.


## Drift de identidade apos freeze

Qualquer Skill externa que publique um novo commit apos o freeze invalida as evidencias exact-head. Em `certified-handoff`, a unica excecao e o `result-only-child` produzido pelo proprio `entregar-issue`, filho direto do material head e restrito a `certificate_commit_policy.allowed_paths`. Em `native-github-audit`, nao existe filho de resultados; qualquer novo commit exige revalidacao do material head. O retorno ao controlador deve ocorrer antes de nova auditoria independente.

Para `corrigir-ci`, o envelope minimo de retorno e:

```json
{
  "schema_version": 2,
  "contract_version": "2026-08-20.3",
  "return_control_to": "entregar-issue",
  "next_phase": "finalize-after-ci",
  "ci_owner_closed": true,
  "reason": "post-ci-refreeze",
  "previous_frozen_sha": "<sha anterior>",
  "material_head_sha": "<sha verde atual>",
  "ci_state": "green",
  "recovery_hint": {"changed_files": [], "resume_from": "hygiene"}
}
```

`entregar-issue` valida esse envelope com `scripts/finalize_after_ci_checkpoint.py`, compara o delta, invalida somente gates e evidencias dependentes, revalida o novo material head, refaz o freeze quando necessario e resolve `audit_transport`. Em `certified-handoff`, gera novo `handoff-ready.json` e publica novo result-only child; em `native-github-audit`, nao publica `.audit` e fecha por evidencia remota exact-head. A mudanca ser apenas formatacao ou arquivo colateral fora da allowlist de resultados nao permite reutilizar certificado do material head anterior.
