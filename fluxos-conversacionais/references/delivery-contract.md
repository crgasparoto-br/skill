# Contrato com o Entregar Issue

Receber modo, contexto, requisitos de continuidade, produtores, entrypoints, caminhos, perfil, registro documental e fingerprint. Nao repetir descoberta geral.

Centralizar produtores equivalentes, selecionar cenarios por risco e usar pairwise quando o mesmo contrato cobre canais/variantes. Retornar JSON conforme `schemas/subskill-result.schema.json` com maquina de estados, produtores, persistencia, classes/casos, fingerprint e resultados discriminantes.

## Envelope e reutilizacao

Emitir sempre `input_fingerprint` e `reused`. Execucao nova usa `reused=false` e nao inclui `reuse_source`. Reutilizacao usa `reused=true` somente com `reuse_source.result_path`, SHA-256 e fingerprint conferidos, identidade material vigente, `changed_files=[]` e `requires_refreeze=false`. Status `not-applicable`, `no-change` ou `contract-mismatch` exige `skip_reason` objetivo.

## Escrita e retomada do controlador

Quando `mode=implementation` produzir `changed_files`, emitir `controller_hints.material_write=true`. Alteracao de codigo executavel exige `code_growth_recheck=true`, `invalidate_stages` contendo `hygiene` e `resume_from=hygiene`. A Skill nao cria nem edita `stage-checkpoints.json`; `entregar-issue` aplica a invalidacao e executa `CODE-GROWTH-001` sobre o delta final.

## Versao

Aceitar e emitir somente `contract_version=2026-08-20.3`. Retornar `contract-mismatch` antes de executar trabalho quando a versao recebida diferir.
