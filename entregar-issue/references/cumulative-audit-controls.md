# Controles herdados cumulativos

## Objetivo

Garantir que cada novo candidato preserve as defesas exigidas por todas as auditorias independentes anteriores da mesma issue, PR ou familia, em vez de corrigir apenas o ultimo finding.

## Artefato

Manter `.audit/entregar-issue/inherited-controls.json` com:

- `head_sha` do candidato atual;
- `source_audits` identificando auditorias anteriores consideradas;
- `controls` com ID estavel, finding/escape de origem, `status`, `head_sha` e `subject_sha`;
- para cada controle executado: `control_type`, `procedure`, `expected`, `observed`, `evidence` e `evidence_sha256`;
- quando o controle corresponder a ataque da matriz, opcionalmente `attack_control_id` ou o trio `risk_family + surface + dimension` para vinculo verificavel;
- `retired_controls` para controles anteriormente herdados que deixaram de permanecer ativos, cada um com `id`, `disposition=superseded|not-applicable`, `reason`, `subject_sha`, `procedure`, `expected`, `observed`, `evidence` e `evidence_sha256`; `superseded` exige `replacement_control_id` ativo e `passed` no SHA atual;
- `unresolved_controls`.

Se nunca houve rejeicao independente, o arquivo ainda deve existir com listas vazias. Se houve rejeicao, todo controle preventivo/detectivo herdado deve ser executado novamente no SHA final quando ainda aplicavel.

## Execucao discriminante

Nao considerar um controle herdado `passed` apenas porque CI/suite agregada ficou verde, o arquivo nao mudou, o diff parece seguro ou o comportamento foi declarado como inalterado. O controle deve registrar uma execucao discriminante no `subject_sha` atual e observacao concreta que seria diferente sob a implementacao errada plausivel.

Rejeitar como evidencia suficiente afirmacoes como `CI green`, `workflow passed`, `no diff`, `unchanged`, `not touched` ou equivalentes. Para controles ligados a uma superficie de risco, preferir vincular o controle herdado ao ataque atual por `attack_control_id` ou `risk_family + surface + dimension`.

## Regra

Novo finding nao substitui controles antigos. Corrigir A-003 nao permite deixar de executar controles herdados de A-001/A-002. A cada remediacao, carregar o `inherited-controls.json` do handoff independente anterior e executar `scripts/validate_inherited_controls.py --previous-inherited-controls ... --previous-independent-rejection`; todo ID anterior deve continuar ativo ou aparecer em `retired_controls` com disposicao verificavel. `source_audits` tambem e monotonicamente cumulativo. Desaparecimento silencioso de controle ou auditoria bloqueia freeze e handoff. `unresolved_controls` nao vazio, controle aplicavel `not-run/failed`, evidencia sem hash, `subject_sha` stale ou execucao apenas declarativa bloqueia freeze e handoff.


## Aposentadoria contra o contrato canonico

`retired_controls.disposition=not-applicable` nao e uma forma de reduzir saturacao. Antes de aceitar a aposentadoria, rederivar `risk_family` e superficie a partir da `requirement-closure` canonica. Se a familia/superficie do controle anterior continuar exigida, bloquear `not-applicable`; manter o controle ativo ou usar `superseded` com substituto ativo, passed e executado no SHA atual.
