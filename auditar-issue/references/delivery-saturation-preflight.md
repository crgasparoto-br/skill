# Preflight de saturacao da entrega

## Aplicabilidade

Executar este preflight **somente para `evidence_profile=critical`**. `light` e `standard` usam `references/evidence-profiles-audit.md` e nao devem ser reprovados pela ausencia deliberada destes artefatos.

## Artefatos critical

Usar como indice de readiness, nunca como conclusao:

- `requirement-attack-matrix.json`;
- `risk-saturation.json`;
- `inherited-controls.json`;
- `evidence-provenance.json` quando quantitative/exact-SHA;
- closures de rejeicao independente quando aplicaveis.

Antes de provas caras confirmar que requisitos materiais possuem ataques/controles executados, familias aplicaveis estao saturadas, controles herdados estao current-head e nenhum gate terminal permanece pendente. Falha retorna `delivery-not-saturated` sem consumir auditoria ampla.

Controles herdados ativos tornam sua familia/surface material e nao podem desaparecer silenciosamente da matriz/saturacao corrente.

## SPEC-LIST-COVERAGE-001 — cobertura independente de listas normativas

Antes de confiar em `candidate_count`, `uncovered_requirements=[]` ou na matriz de ataques, rederivar diretamente das fontes textuais certificadas todos os itens de lista Markdown em secoes normativas (`Escopo/Scope`, `Requisitos/Requirements`, `Criterios de aceite/Acceptance criteria`, `Invariantes/Invariants`). Excluir apenas secoes explicitamente nao normativas como `Fora de escopo/Out of scope` e `Referencias/References`. Comparar cada item por `source_id + source_line + source_text` com `requirement-closure.json` e bloquear `delivery-not-saturated` se qualquer item normativo desaparecer. Executar com parser proprio do auditor; nao importar nem reutilizar o extrator do produtor.
