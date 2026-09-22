# Gate de freshness e proveniencia de evidencia

## Objetivo

Impedir que uma medicao executada em um SHA anterior seja promovida por inferencia para o material head final. Evidencia quantitativa e observacao empirica do candidato medido, nao propriedade herdavel por descricao de diff.

## Aplicabilidade

Aplicar quando qualquer requisito, controle ou criterio de aceite depende de valor medido: latencia, percentil, throughput, consumo, tamanho, cardinalidade, custo, duracao, plano de consulta, contagem de chamadas ou outra metrica quantitativa.

## Tipos de evidencia

Classificar controles quando a proveniencia importar:

- `behavioral`: comportamento observado por teste/cenario;
- `structural`: propriedade derivada de codigo, grafo, schema ou configuracao;
- `quantitative`: medicao numerica produzida por execucao;
- `documentation`: contradicao, exemplo, link ou comando documental.

A ausencia de `evidence_kind` nao desativa este gate quando a propria especificacao contem sinais quantitativos. `validate_requirement_attack_matrix.py` rederiva essa aplicabilidade de `source_texts` e exige `positive_control` quantitativo com proveniencia. Ao usar `quantitative`, aplicar obrigatoriamente este gate.

## Manifesto normalizado

Produzir `.audit/entregar-issue/evidence-provenance.json` com `schema_version=1`, `material_head_sha` e uma entrada por evidencia ativa. Cada entrada deve registrar no minimo:

- `evidence_id` estavel;
- `kind`;
- `path` relativo ao repositorio;
- `sha256`;
- `subject_sha`: SHA realmente executado ou medido;
- `freshness_policy`;
- `producer`;
- `status=passed`.

Para `quantitative`, exigir `freshness_policy=exact-material-head` e `subject_sha == material_head_sha`. O `head_sha` declarado na matriz nao substitui o `subject_sha` da proveniencia.

## Mudanca material e result-only child

Qualquer commit material posterior ao `subject_sha` invalida evidencia quantitativa exact-SHA, mesmo quando o delta pareca incapaz de afetar a metrica. Analise estrutural do delta pode reduzir quais testes funcionais precisam repetir, mas nao pode promover percentis, tempos ou contagens observados em outro SHA.

O filho `result-only-child` autorizado nao muda o material head. Evidencia quantitativa permanece valida quando mede o `material_head_sha` certificado e o filho altera somente caminhos allowlisted de resultado.

## Refreeze

No `post-write-refreeze`, classificar evidencias por dependencia. Se existir evidencia `quantitative` cujo `subject_sha` difira do novo material head:

1. marcar a evidencia stale;
2. reexecutar o mesmo protocolo/coorte no novo material head;
3. gerar novo resultado bruto e atualizar `evidence-provenance.json`;
4. reexecutar `validate_evidence_freshness.py` e a matriz de ataques;
5. somente depois refazer freeze/handoff.

Nao aceitar como substituto afirmacoes como `nenhum novo await`, `mesmo numero de chamadas`, `delta apenas de telemetria` ou equivalente. Essas afirmacoes sao evidencias estruturais, nao medicoes quantitativas.

## Portao

Executar:

`python scripts/validate_evidence_freshness.py --evidence-provenance <arquivo> --material-head-sha <sha>`

Quando a matriz contiver controle `evidence_kind=quantitative`, executar tambem `validate_requirement_attack_matrix.py` com `--evidence-provenance`. Falha de proveniencia impede `INTERNALLY_APPROVED`, freeze e handoff independente.
