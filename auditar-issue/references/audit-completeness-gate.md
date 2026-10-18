# Portao de completude da auditoria independente

## Objetivo

Impedir auditorias em series nas quais cada rodada publica dois ou tres achados
enquanto outros blockers baratos do mesmo HEAD permanecem nao examinados.
O contrato vale para qualquer repositorio, dominio, linguagem ou interface de teste.

Aplicar tambem `references/audit-checklist.md` como roteiro de descoberta.

## Ordem obrigatoria

1. Resolver identidade remota e transporte da auditoria; concluir os preflights
   de readiness sem classificar limitacao de infraestrutura como defeito do candidato.
2. **Antes de executar provas**, construir um inventario independente de cada
   obrigacao atomica, superficie material, familia de risco, fronteira e custo.
   Rederivar da issue, referencias normativas, diff, entrypoints, consumidores,
   caminhos transitivos, testes e todas as revisoes anteriores. Nao copiar a
   matriz do implementador: ela apenas ajuda a localizar fontes.
3. Congelar as fontes brutas, paths e hashes (issue/specification e diff
   obrigatorios). Registrar o procedimento de descoberta e os changed paths.
   Resolver historico por comentarios/reviews autenticados, mesmo que o autor
   diga que todos os findings foram resolvidos.
4. Conferir cada changed path com o snapshot JSON imutavel do GitHub (base_sha,
   head_sha, changed_paths[]), e registrar changed_path_reviews[] com evidencia
   e ligacao as superficies; arquivo inteiro nao pode desaparecer da auditoria.
5. Executar primeiro controles baratos de **todas** as familias materiais
   independentes. Um blocker limita apenas experimentos caros nao relacionados.
   Variar casos irmaos, transformacoes, escopos e controles benignos aplicaveis.
5. Marcar cada requisito/superficie como covered, not-applicable (com evidencia
   independente de inaplicabilidade) ou not-executed. Nenhuma superficie barata
   permanece not-executed, inclusive quando o veredito ja e REPROVADA.
   Verificacoes caras podem ficar not-executed somente quando existe blocker
   comprovado, com motivo preciso e cobertura rotulada limited.
6. Preservar todo finding historico por ID com resolved, still-open, regressed
   ou not-applicable. Achados novos mantem ID estavel, requisito, superficie,
   causa raiz, classificacao e prova. Agrupar por causa sem limitar contagem.
7. Revalidar SHA/base, cobertura e ledger antes do parecer. O JSON de inventario
   independente nao e um atestado de ausencia de bugs: casos nao previstos
   continuam possiveis; nao prometer exaustividade de comportamentos arbitrarios.

## Gate executavel

Materializar os dois arquivos separados fora do repositorio sob auditoria:

- inventory.json: schema_version 1, identity (repository, base_sha, head_sha),
  discovery (mode=independent-rederivation, procedure, changed_paths),
  sources[] (id, kind=specification|diff|contract, evidence_path, evidence_sha256),
  requirements[] (id, source_id), surfaces[] (id, requirement_id, risk_family,
  boundary, cost=cheap|expensive), previous_findings[] (id, source_url).
- report.json: mesma identity/schema_version, verdict, coverage
  comprehensive|limited, discovery_closed=true, changed_path_reviews[], requirements[] e surfaces[]
  (id, status, reason quando exigida, evidence_path/evidence_sha256 quando
  executado ou declarado inaplicavel), previous_findings[] (id, disposition,
  reason, evidence), findings[] (id, requirement_id, surface_id, root_cause,
  disposition, evidence), blocking_ids[].

Paths das provas sao relativos ao --root; hashes SHA-256 abrangem bytes originais.
O script confere integridade, identidade, correspondencia exata dos IDs,
disposicoes historicas, trabalhos baratos pendentes e consistencia do veredito.

\`\`\`sh
python <AUDIT_SKILL_ROOT>/scripts/validate_audit_completeness.py \
  --inventory <ephemeral>/inventory.json \
  --report-json <ephemeral>/report.json \
  --root <ephemeral> --head-sha "$MATERIAL_HEAD_SHA"
\`\`\`

Executar **antes** de validar e publicar o parecer com
\`validate_verdict_header.py\`. Falha do gate impede declarar que a
auditoria foi concluida; corrigir inventario/execucao do proprio auditor,
nao alterar o candidato para que sua propria auditoria seja executavel.
Se o runtime impedir a execucao, aplicar audit-runtime-limitation e
INCONCLUSIVA, nao forcar REPROVADA do produto.

## Ressalva de independencia

O validador e deterministico, mas nao pode descobrir por si so uma superficie
que o auditor omitiu das **duas** entradas, nem provar que uma evidencia
verdadeira foi executada a partir apenas de JSON. A responsabilidade de
rederivar inventario por fontes oficiais, reproduzir provas e fiscalizar
inaplicabilidades permanece do auditor em contexto separado. Em reauditoria,
revalidar as familias afetadas, findings anteriores e qualquer novo risco;
reutilizar apenas provas que continuam validas no HEAD congelado.
