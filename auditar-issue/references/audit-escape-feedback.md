# Feedback estruturado de audit escape

## Objetivo

Converter finding independente que escapou de aprovacao interna em defesa reutilizavel, reduzindo novas auditorias usadas apenas para descobrir o proximo caso da mesma classe.

## Classificacao obrigatoria

Quando o mesmo SHA, ou candidato materialmente equivalente, havia sido `INTERNALLY_APPROVED`, registrar `audit_escape=true`, mas nao presumir que o escape e sistemico. Classificar `remediation_mode` primeiro:

- `targeted-remediation`: o finding e local e pode ser fechado por replay/regressao discriminante no proprio recorte. Preservar finding ID, causa, evidencia e gate exigido; nao exigir sibling cases, controle reutilizavel ou mudanca permanente de Skill.
- `systemic-remediation`: ha evidencia de falha generalizavel/recorrente do processo ou do controle. Somente aqui exigir `escape_class` transferivel, `prevention_gap`, `detection_gap`, `plausible_wrong_implementation`, sinais estruturais, familias de risco, sibling cases e controle reutilizavel.

Falha de gate deterministico que simplesmente nao foi reproduzido antes do freeze e `targeted-remediation` por padrao, salvo evidencia adicional de defeito sistemico no controlador.

## Varredura antes de devolver

Depois do primeiro blocker, continuar a varredura estatica barata por blockers independentes observaveis. Em `targeted-remediation`, limitar casos irmaos ao que for necessario para provar o recorte diretamente impactado. Em `systemic-remediation`, procurar ao menos dois casos irmaos quando houver dimensoes plausiveis e nao interromper no primeiro exemplo da classe.

## `escape-control.json`

Emitir uma entrada por escape:

```json
{
  "finding_id": "A-001",
  "audit_escape": true,
  "escape_class": "restart-idempotency-recovery-gap",
  "plausible_wrong_implementation": "...",
  "literal_case": {"entrypoint": "...", "procedure": "...", "expected": "...", "observed": "..."},
  "sibling_cases": [{"id": "...", "dimension": "...", "procedure": "..."}],
  "reusable_control": {"id": "RESTART-IDEM-001", "risk_family": "state-recovery", "procedure": "..."},
  "trigger_terms": ["retry", "reinicio", "lease"],
  "required_risk_families": ["idempotency", "concurrency-atomicity"],
  "prevention_target": "implementation/delivery contract",
  "detection_target": "internal adversarial gate"
}
```

O artefato e handoff de remediacao, nao evidencia de aprovacao. Exigir promocao para `audit-escape-pattern-catalog.json` e `inherited-controls.json` somente em `systemic-remediation`; finding targeted permanece local ao ledger de remediacao.

## Controles canonicos reutilizaveis

### `TEMP-ASOF-001`

Para metrica rotulada por periodo historico, criar evento dentro do periodo e evento posterior com valores diferentes. Verificar que o evento posterior nao contamina o resultado historico e que o cutoff executado coincide com o horizonte apresentado. Repetir caso irmao para periodo atual e projecao futura.

### `RESTART-IDEM-001`

Persistir operacao em estado de processamento, simular interrupcao/reinicio e expirar a lease. Repetir **o mesmo entrypoint publico**, com a **mesma chave de idempotencia**, sem GET/health-check/operacao auxiliar de recuperacao. O retry deve recuperar ou finalizar de forma controlada sem duplicar outbound/efeito. Caso irmao: nova chave concorrente; caso irmao: reinicio apos outbound mas antes da finalizacao.

Um teste que primeiro chama endpoint auxiliar de leitura e somente depois repete a operacao nao comprova retry direto.

## Regra de qualidade

O controle reutilizavel deve falhar na implementacao plausivel errada encontrada e passar na correta. Se ambas passam, o controle nao fecha o escape.
