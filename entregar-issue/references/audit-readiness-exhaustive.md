# Completude da entrega antes de auditoria independente

## Objetivo

Reduzir a repeticao de ciclos em que cada auditoria encontra apenas alguns blockers.
Reconciliar antes do freeze todos os achados anteriores, requisitos canonicos,
riscos derivados e familias materiais, sem fingir que a implementacao e auditora
independente de si propria.

## Protocolo de entrega

1. Congelar issue, requisitos atomicos, changed paths planejados, SHA base e
   lista autenticada de todos os findings e recomendacoes acionaveis de
   comentarios/reviews anteriores (nao apenas da ultima auditoria).
2. Reconciliar requisitos e superficies de requirement-closure.json,
   requirement-attack-matrix.json, risk-saturation.json, diff e consumidores
   efetivos. Recomputar aplicabilidade e buscar superficies omitidas ou nao
   declaradas. Nao reduzir risco por silencio na matriz ou remocao de uma flag.
3. Fechar em ledger 1:1 todos os findings anteriores no material head; executar
   os testes adversariais do caso literal e dos casos irmaos impactados.
   Dar especial atencao a escapes de regra, alteracao de escopo e falsos positivos.
4. Depois de qualquer primeiro blocker, continuar todos os controles baratos
   das outras familias de risco; agrupar por causa raiz sem teto de achados.
   Uma falha nao transforma os demais testes baratos em desnecessarios.
5. Exigir provas brutas (comando, saida/efeito, SHA, hashes, ambiente, resultado),
   e distinguir declarado, executado e aprovado. Nao forjar evidencia
   apenas preenchendo expected/observed/status no JSON do produtor.
6. Executar os validadores preexistentes de fechamento, matriz, saturacao,
   baseline e gates obrigatorios sobre o HEAD; nenhum deles pode ser ignorado
   por CI de outro projeto ou por um teste isolado. Recongelar apos escrita.
7. Entregar ao auditor em contexto separado os paths e SHAs como indice.
   O auditor deve fazer uma descoberta propria e executar o portao de
   completude da Skill auditar-issue, disponibilizado apenas no pacote do
   auditor independente. Nao afirmar independencia do implementador.

## Resultado esperado

Entrega pronta significa que todo requisito e superficie aplicavel conhecido
foi submetido a um controle ou possui razao comprovavel de inaplicabilidade;
todos os findings historicos sao explicitamente fechados ou abertos; e nao
restou teste barato para a auditoria seguinte descobrir pela primeira vez.
Auditoria independente continua necessaria e pode encontrar defeitos novos;
essa expectativa nao substitui sua capacidade de refutar o candidato.
