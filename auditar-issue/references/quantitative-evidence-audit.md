# Auditoria de evidencia quantitativa exact-SHA

## Objetivo

Detectar evidencia quantitativa stale mesmo quando o pacote de entrega reancora controles ao SHA candidato. O auditor deve verificar o SHA realmente medido, nao apenas o `head_sha` declarado pela matriz.

## Aplicabilidade

Aplicar quando qualquer controle da matriz usar `evidence_kind=quantitative` ou quando um criterio de aceite depender de percentil, latencia, throughput, cardinalidade, custo, duracao, contagem ou outra metrica executada.

## Preflight

Exigir `.audit/entregar-issue/evidence-provenance.json` no handoff. Para cada controle quantitativo:

- `evidence_id` deve existir no manifesto;
- `kind` deve ser `quantitative`;
- `status` deve ser `passed`;
- `freshness_policy` deve ser `exact-material-head`;
- `subject_sha` deve ser exatamente o `material_head_sha` auditado;
- caminho e SHA-256 da evidencia devem coincidir com o controle e com o artefato certificado.

Se qualquer item falhar, classificar `REPROVADA` por evidencia quantitativa stale/inconsistente antes de consumir suites caras.

## Regra de independencia

Nao aceitar como substituto uma justificativa estrutural de que commits posteriores nao adicionaram `await`, I/O, chamadas externas ou mudancas de caminho critico. Isso pode orientar impacto, mas nao converte uma medicao de SHA ancestral em observacao do candidato final.

Um `result-only-child` valido nao altera o material head: a medicao permanece valida se `subject_sha` for o material head certificado.
