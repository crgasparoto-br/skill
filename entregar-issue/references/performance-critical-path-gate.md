# Gate de desempenho, instrumentacao e caminho critico

## Objetivo

Impedir que uma entrega de latencia/desempenho seja aprovada apenas porque um benchmark final melhorou. A entrega deve provar simultaneamente que:

- o caminho produtivo medido foi inventariado a partir do entrypoint real;
- as metricas por etapa representam todo o trabalho material daquela etapa ate o boundary terminal;
- operacoes caras nao consumidas foram removidas ou condicionadas no ramo em que sao desnecessarias;
- o benchmark nao pula wrappers ou operacoes produtivas relevantes sem uma ponte equivalente, explicita e testada.

## Ativacao

Ativar quando o contrato, diff ou finding mencionar latencia, desempenho/performance, `total_ms`, `db_ms`, `context_ms`, `llm_ms`, `persist_ms`, p50/p90/p95, percentil, benchmark, throughput, caminho critico, operacao nao essencial, trabalho desnecessario, lazy loading ou reducao de I/O.

O planner deve inferir o sinal `performance`; `contracts/gate-registry.json` deve ativar `performance-critical-path` automaticamente. Nao depender de lembranca manual do operador.

Na `requirement-attack-matrix.json`, usar `structural-contract` e declarar, quando aplicavel:

- `stage-attribution-completeness`: uma metrica de etapa pode medir apenas um sub-ramo e omitir operacoes diretas, transitivas ou paralelas da mesma classe;
- `critical-path-necessity`: um helper pode devolver apenas o dado necessario e ainda executar I/O/trabalho caro cujo resultado nao e consumido pelo ramo atual;
- `benchmark-path-fidelity`: o harness pode chamar um sub-entrypoint, simular um wrapper com `sleep` ou injetar um valor ja resolvido e, assim, omitir trabalho que continua no caminho produtivo real.

Benchmark/exact-SHA continua usando tambem `benchmark-execution` e `evidence-freshness` quando aplicaveis. Melhora quantitativa nao substitui os controles estruturais acima.

## Contrato estruturado obrigatorio

Para qualquer requisito com uma das superficies de performance, preencher `performance_contract` no item correspondente da matriz. O validador deve bloquear placeholders e inventario vazio.

Estrutura minima:

```json
{
  "performance_contract": {
    "production_entrypoint": "path/to/file#symbol",
    "terminal_boundary": "path/to/file#terminalSymbol",
    "inventory_evidence": {
      "status": "passed",
      "head_sha": "<material-head>",
      "procedure": "Trace direct, transitive and parallel operations from the production entrypoint to the terminal boundary.",
      "observed": "The inventory lists every material before-terminal operation and its source.",
      "evidence": "evidence/performance-inventory.txt",
      "evidence_sha256": "<sha256>"
    },
    "operations": [
      {
        "id": "user-profile-read",
        "source": "server/path.ts#loadUserProfile",
        "stage": "db",
        "metric": "db_ms",
        "before_terminal": true,
        "required_for_contract": true
      }
    ],
    "optimized_branches": [
      {
        "id": "generic-question",
        "operations": [
          {
            "operation_id": "optional-history-read",
            "needed": false,
            "expected_invocations": 0,
            "observed_invocations": 0,
            "status": "passed"
          }
        ]
      }
    ],
    "benchmark": {
      "mode": "production-direct",
      "production_entrypoint": "path/to/file#symbol",
      "harness_entrypoint": "path/to/file#symbol",
      "covered_operation_ids": ["user-profile-read"],
      "bridged_operation_ids": [],
      "omitted_operation_ids": []
    }
  }
}
```

`stage` aceita `db`, `context`, `llm`, `persist`, `delivery`, `network`, `cpu` ou `other`. Para operacoes before-terminal classificadas como `db`, `context`, `llm` ou `persist`, o campo `metric` deve ser respectivamente `db_ms`, `context_ms`, `llm_ms` ou `persist_ms`.

## Inventario do caminho produtivo

Antes da primeira edicao e novamente apos o `produced_diff` estabilizar:

1. partir do entrypoint produtivo real da coorte medida, incluindo wrappers anteriores ao sub-handler otimizado;
2. enumerar operacoes diretas, transitivas e paralelas que podem executar antes da resposta/commit terminal;
3. incluir resolucoes preparatorias que consultem I/O, como lookup de usuario, tenant, timezone, entitlement, configuracao ou referencia, mesmo quando entregam valor pronto ao sub-handler;
4. classificar cada operacao material como banco, montagem de contexto, provider/IA, persistencia, delivery/rede, CPU ou outra etapa relevante;
5. registrar `source`, metrica que cobre a operacao e se ela e obrigatoria para o contrato;
6. registrar evidencia exact-head do inventario.

Nao aceitar inventario baseado apenas no nome da funcao superior. Ler consumidores e dependencias transitivas suficientes para localizar I/O real. Um `sleep`, fixture ou double que representa uma etapa nao prova que o harness atravessa a mesma semantica produtiva dessa etapa.

## Cobertura completa de metricas por etapa

Uma metrica de etapa e valida somente quando sua fronteira cobre **todas** as operacoes daquela etapa que executam no ramo medido, ou quando as excecoes possuem metrica separada explicitamente documentada.

Exemplos genericos:

- `db_ms` nao pode medir somente loaders de contexto se lookup de usuario, timezone, entitlement ou outra query anterior tambem pertence ao mesmo fluxo medido;
- `db_ms` nao pode medir somente `loadPrimaryData()` se um ramo paralelo de historico/contexto tambem executa queries antes do provider;
- `context_ms` pode englobar wall-clock de montagem, mas isso nao transforma queries internas em trabalho nao atribuivel a banco quando o contrato exige `db_ms` separado;
- uma operacao de persistencia executada apos o timer de `persist_ms` invalida a cobertura mesmo se estiver contida em `total_ms`;
- spans sobrepostos sao permitidos quando a semantica e declarada; apresentar metricas sobrepostas como particoes exclusivas e proibido.

### Controle minimo `PERF-STAGE-ATTR-001`

Usar teste, trace, contador de chamadas ou procedimento reproduzivel que confronte **todo `performance_contract.operations`** com as fronteiras de medicao. O controle deve falhar para uma implementacao que adiciona ou mantem uma segunda operacao da mesma etapa fora do timer/span.

Casos irmaos recomendados:

- operacao anterior ao sub-handler, como lookup/resolucao preparatoria;
- operacao transitiva em helper diferente;
- operacao em ramo paralelo (`Promise.all`, task/future equivalente);
- falha/timeout que encerra uma etapa por caminho diferente do sucesso.

## Necessidade do trabalho no caminho critico

Para cada ramo usado para justificar a otimizacao:

1. listar no `optimized_branches` **todas** as operacoes before-terminal do inventario;
2. marcar `needed=true|false` por operacao naquele ramo;
3. para operacao `needed=false` e `required_for_contract=false`, provar `expected_invocations=0` e `observed_invocations=0`;
4. executar ramo irmao em que a mesma fonte seja necessaria quando aplicavel;
5. preservar trabalho obrigatorio mesmo quando ele custa latencia.

Nao basta reduzir objetos enviados ao consumidor. Se um helper ainda consulta historico, snapshot, memoria, agregados ou qualquer outra fonte descartada depois, o trabalho continua no caminho critico.

### Controle minimo `PERF-CRITICAL-WORK-001`

Em um ramo onde determinada fonte nao e necessaria, provar por contador/spy/trace que a operacao cara possui **zero invocacoes**. O validador deve rejeitar ramo que omita uma operacao before-terminal do inventario, pois omissao da matriz de branch mascara exatamente a classe de escape que este gate deve detectar.

## Fidelidade do benchmark ao caminho produtivo

Quando houver benchmark, baseline/candidato ou alegacao de "mesmo caminho produtivo", exigir `benchmark-path-fidelity` e `PERF-BENCH-PATH-001`.

O bloco `benchmark` deve usar um dos modos:

- `production-direct`: `harness_entrypoint == production_entrypoint`; nenhum `bridged_operation_id` e permitido;
- `bridged`: o harness inicia abaixo do entrypoint produtivo, mas toda operacao before-terminal nao atravessada diretamente deve aparecer em `bridged_operation_ids` e possuir `bridge_evidence` exact-head que prove equivalencia de ordem, falha e custo semantico relevante.

Em ambos os modos:

- todo operation ID before-terminal deve estar em `covered_operation_ids` ou `bridged_operation_ids`;
- `omitted_operation_ids` deve ficar vazio;
- injetar valor ja resolvido no sub-handler nao equivale a executar a resolucao produtiva que o produz;
- substituir uma query por `sleep` preserva atraso, mas nao prova cobertura da semantica produtiva, de erro, cache, retry ou atribuicao de etapa.

### Controle minimo `PERF-BENCH-PATH-001`

Comparar o inventario produtivo com o caminho realmente exercitado pelo harness. O teste deve falhar quando um wrapper, lookup, resolucao ou outra operacao before-terminal existe em producao e nao aparece como coberta nem como ponte explicitamente provada.

## Gates de desempenho com escopo

Quando o requisito de desempenho for tenant-scoped, por particao, por usuario, por status ou por qualquer outro filtro de isolamento:

- medir a cardinalidade do mesmo escopo consultado; total global, linhas de outros tenants ou categorias excluidas nao podem compor o denominador de aprovacao;
- inserir ruido deliberado fora do escopo e provar que esse ruido nao altera o resultado do gate;
- registrar tamanho da pagina, candidatos do escopo alvo, linhas observadas no plano e limite proporcional permitido;
- exigir controle negativo que reproduza leitura integral ou quase integral do escopo alvo e falhe mesmo quando o banco inteiro for muito maior;
- preferir o plano da consulta real ou uma consulta estruturalmente identica, incluindo filtro, ordenacao, desempate e limite;
- rejeitar verificadores que comparem linhas lidas no tenant alvo com contagem global do banco.

## Evidencia adversarial

Os controles dessas superficies devem declarar:

- a implementacao errada plausivel concreta;
- operacao/helper/transicao que escaparia;
- procedimento reproduzivel;
- resultado esperado verificavel;
- resultado observado concreto (contagem, operacoes inventariadas, span/timer, evento, estado ou outra observacao objetiva);
- evidencia hasheada no material head.

Descricoes como `Run exact-head control`, `Contract holds`, `Observed pass`, `Silent contract break` ou equivalentes nao sao evidencia e devem bloquear o handoff.

## Portao

Bloquear freeze/handoff quando ocorrer qualquer um destes casos:

- `performance_contract` ausente, incompleto ou sem evidencia exact-head do inventario;
- operacao material do caminho produtivo sem classificacao de etapa;
- operacao `db|context|llm|persist` before-terminal sem atribuicao a metrica correspondente;
- metrica de etapa que cobre apenas subconjunto silencioso das operacoes da etapa;
- ramo otimizado que omite operacao do inventario ou mantem I/O nao consumido sem justificativa contratual;
- controle de ausencia baseado apenas em benchmark agregado, sem observacao de chamadas/operacoes;
- benchmark que pula entrypoint/wrapper produtivo sem declarar e provar cada ponte;
- operacao produtiva marcada em `omitted_operation_ids` ou fora de `covered_operation_ids + bridged_operation_ids`;
- controle adversarial generico, tautologico ou sem resultado reproduzivel.
