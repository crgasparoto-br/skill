# Matriz obrigatoria requisito -> ataque

## Objetivo

Impedir que um criterio de aceite, superficie de risco ou cenario obrigatorio chegue pela primeira vez a auditoria independente sem ter sido transformado em um controle discriminante executado no SHA final.

## Aplicabilidade

Aplicar a toda entrega com requisito comportamental, invariantes de estado, persistencia, autorizacao, referencia, data, concorrencia, historico, fronteira publica ou integracao. Documentacao isolada pode usar controles de contradicao em vez de runtime.

## Artefato

Produzir `.audit/entregar-issue/requirement-attack-matrix.json` antes do freeze. Cada requisito coberto deve possuir:

- `requirement_id` e `obligation_ids`;
- `obligation_control_map` quando `obligation_ids` tiver mais de uma entrada;
- `risk_families` derivadas da especificacao e do diff;
- `risk_surfaces`: todas as superficies materiais pelas quais a mesma familia pode falhar, cada uma com `risk_family`, `surface` e `reason`;
- `plausible_wrong_implementation`: uma implementacao errada que ainda passaria no caminho feliz;
- `positive_control` executado no SHA final;
- ao menos um `negative_control` discriminante **primario por superficie material** executado no SHA final;
- `sibling_cases` que variem pares `surface + dimension`, nao apenas valores do mesmo fixture;
- `regression_controls` executados no SHA final.
- para controles quantitativos, `evidence_kind=quantitative`, `evidence_id` e `evidence_sha256` correspondentes a uma entrada de `evidence-provenance.json`;
- quando houver cobertura de relatorio apoiada em dados retidos, `coverage_contract` com `reporting_entrypoint` e inventario de cada tier retido detectado na especificacao;
- quando a fonte enumerar explicitamente cenarios que os testes devem cobrir, `test_coverage_contract` com todos os casos extraidos e um `control_id` distinto de `control_type=test` por caso.

Requisito sem ataque ou com superficie declarada sem controle primario nao esta fechado, mesmo que exista teste nominalmente relacionado.


## Atomizacao por obrigacao

Um `requirement_id` pode agrupar mais de uma linha/obrigacao apenas para organizacao, nunca para reduzir a prova. Quando `obligation_ids` tiver mais de uma entrada:

1. preencher `obligation_control_map` com exatamente todas as obrigacoes da `requirement-closure`;
2. apontar cada obrigacao para um `primary_negative_control_id` materialmente discriminante;
3. exigir que a familia/superficie do controle seja compatível com o `source_text` daquela obrigacao quando a inferencia canonica produzir familia/superficie;
4. permitir o mesmo `primary_negative_control_id` para duas ou mais obrigacoes somente quando o mesmo ataque exercita exatamente a mesma familia/superficie e a mesma observacao prova todas elas;
5. proibir compartilhamento entre obrigacoes heterogeneas, superficies diferentes ou efeitos diferentes;
6. manter controles adicionais por superficie quando uma obrigacao exigir mais de um ataque.

A regra evita dois extremos: nao comprimir criterios heterogeneos em um teste omnibus, mas tambem nao duplicar IDs/procedimentos/evidencias quando duas linhas canonicas descrevem a mesma invariancia observavel. O validador revalida o controle compartilhado contra a familia/superficie derivada de **cada** obrigacao; se qualquer uma divergir, o compartilhamento falha.

## Clausulas explicitas de cobertura de testes

Quando a fonte contiver formulacao como `Testes cobrem A, B, C` / `Tests cover A, B, C`, extrair cada caso enumerado para `test_coverage_contract.cases`. Para cada caso:

- preservar a frase do caso derivada da fonte;
- registrar `status=passed`, evidencia e `control_id`;
- usar um controle negativo distinto com `control_type=test`;
- apontar para `structural-contract:specified-test-matrix`;
- nao aceitar CI verde, nome de suite ou um unico teste agregado como substituto dos casos enumerados.

O objetivo e provar a matriz pedida pela especificacao, inclusive variantes, estados iniciais e fronteiras HTTP/UI quando explicitamente nomeados.

## Superficies e dimensoes

Familia de risco nao e superficie. Para `authorization`, por exemplo, a mesma classe pode atravessar `environment`, `filesystem`, `persistent-credential-store`, `artifact-export`, `process-identity`, endpoint ou storage. Para cada superficie realmente exposta pela arquitetura, criar uma entrada em `risk_surfaces` e um controle negativo cujo `surface` corresponda exatamente.

Nao omitir superficie evidente para fazer o gate passar. O validador rederiva um conjunto minimo de familias e superficies diretamente de `source_texts`, alem da implementacao errada e dos procedimentos declarados. A matriz nao e fonte de verdade sobre a propria aplicabilidade. No contexto de `authorization`, sinais como `process.env`/`extraEnv`, `private key`/filesystem, `CODEX_HOME`/`auth.json`, artifact upload e mesma identidade de processo ativam respectivamente as superficies genericas correspondentes. A inferencia automatica e apenas piso de seguranca; a entrega continua responsavel por declarar outras superficies derivaveis da arquitetura.

Cada `negative_control` deve registrar:

- `id`;
- `risk_family`;
- `surface`;
- `dimension`;
- `failure_mode`;
- `plausible_wrong_implementation`;
- `control_type`: `test`, `gate`, `scenario` ou `procedure`;
- `procedure`, `expected` e `observed`;
- `evidence_path`/`evidence` e `evidence_sha256`;
- `evidence_kind` e `evidence_id` quando a prova for quantitativa/exact-SHA;
- `head_sha` e `status=passed`;
- `sibling_cases` com `id`, `surface`, `dimension` e `status`.

## Derivacao de ataques

Converter linguagem contratual em ataques, nao apenas em assercoes felizes. Exemplos:

- `continua valido`, `continua acessivel`, `revalidar`, `no momento da liberacao`, `apos aprovacao` -> `reference-liveness`;
- `futuro`, `passado`, `semana`, `periodo`, `vigencia`, `data alvo` -> `temporal-destination`;
- `coverage`, `cobertura`, `availableFrom/availableTo`, qualidade de dados, janela disponivel, retencao ou `complete|partial` **em contexto de relatorio/disponibilidade** -> `temporal-consistency:reporting-availability-window`; palavras soltas como `complete/completa` nao ativam este risco. Executar `TEMP-COVERAGE-001` cruzando a janela solicitada com o cutoff real e observar o payload de cobertura, nao apenas o job de retencao. Se a especificacao tambem definir tiers retidos, inventariar todos em `coverage_contract`; cada tier usado exige controle proprio e probe fora da borda da sua granularidade;
- `mesmo contrato`, `outro tenant`, `escopo` -> `tenant-isolation`;
- alvo/`contractId` derivado da sessao autenticada -> `authorization:session-target-binding`;
- body/request/payload proibido de escolher ou sobrescrever o alvo -> `public-boundary:request-target-override`;
- catalogo/definicao/fonte canonica compartilhada entre runtime, seed, import ou manutencao -> `structural-contract:canonical-source-consistency`;
- clausula `Testes cobrem ...` / `Tests cover ...` -> `structural-contract:specified-test-matrix` + `test_coverage_contract` caso a caso;
- `nao duplicar`, `retry`, callback/webhook, replay ou reprocessamento -> `idempotency:duplicate-processing`; concorrencia explicita adiciona `concurrency-atomicity`;
- `rollback`, `sem estado parcial` -> `rollback`;
- `historico`, `imutavel`, `nova revisao` -> `historical-immutability`;
- `nao revelar`, `404 generico`, `permissao` -> `public-boundary`/`authorization`;
- segredo ou credencial atravessando papeis -> enumerar todos os canais tecnicamente acessiveis, por exemplo ambiente, filesystem, credential store persistente, artifacts e identidade de processo.
- `relacionado a evidencia`, `operacoes afetadas`, `somente operacoes aprovadas/revisadas`, `escopo autorizado`, `efeito permitido pela decisao` ou equivalente -> `authorization:evidence-effect-scope`; executar `AUTH-EFFECT-SCOPE-001` com fonte `effect_a` versus pedido `effect_b`, e incluir branch emergencial/override/excecao como dimensao irma quando existir.
- `db_ms`, `context_ms`, `llm_ms`, `persist_ms`, instrumentacao por etapa ou equivalente -> `structural-contract:stage-attribution-completeness`; inventariar operacoes diretas, transitivas e paralelas da etapa e provar cobertura do timer/span.
- latencia, p50/p90/p95, caminho critico, operacao nao essencial, lazy loading ou reducao de I/O -> `structural-contract:critical-path-necessity`; provar zero invocacoes do trabalho caro no ramo em que seu resultado nao e consumido.
- dois ou mais campos de identidade semanticamente vizinhos, como plano/produto/versao/assinatura/beneficiario/patrocinador, -> `structural-contract:semantic-identity-propagation`; usar valores deliberadamente distintos e observar o payload/argumento persistido em cada produtor material.
- `must_be_single_source`, fonte unica/canonica de uma dimensao, `nao misturar`, `sem conversao explicita`, ou calculo cuja dimensao deve vir de registros relacionados -> `structural-contract:relational-semantic-integrity`; executar `REL-SEM-001` com valores deliberadamente incompatíveis nos registros ligados e atravessar o produtor canonico de escrita antes de observar o consumidor/agregado.

## Cobertura de retencao por tier

Quando um requisito de relatorio declarar cobertura/qualidade e a especificacao definir retencao de dados em uma ou mais granularidades, o inicializador preenche `coverage_contract.retained_tiers`. Nao apagar tiers para simplificar o gate. Para cada entrada:

- manter `tier` e `granularity` derivados da fonte canonica;
- definir `applicability=used|not-used` e justificar;
- para `used`, apontar `control_id` exclusivo de um `negative_control` em `temporal-consistency:reporting-availability-window`;
- no controle, declarar `coverage_tier` e `boundary_granularity`;
- registrar `boundary_probe` com timezone e as bordas observadas de purge, query e payload;
- em granularidade de bucket, usar cutoff propositalmente nao alinhado e requisitar desde a borda normalizada para provar que o bucket preservado e reportado como `complete`.

Dois tiers nao podem reutilizar o mesmo `control_id`. Declarar um tier `not-used` exige motivo material de por que aquele storage/aggregate nao alimenta o reporting entrypoint auditado; nao usar `not-used` apenas porque outro tier possui teste verde.

## Propagacao de identidade semantica

Para `structural-contract:semantic-identity-propagation`, nao usar fixtures em que campos vizinhos possuam o mesmo valor. O controle primario deve:

1. atribuir valores deliberadamente distintos a pelo menos dois campos de identidade presentes no contrato;
2. atravessar o produtor/entrypoint material, nao apenas um helper isolado;
3. observar o boundary de mapeamento/persistencia (argumento de repository, payload, ledger ou store equivalente);
4. comprovar que nenhum campo foi omitido, trocado ou derivado do campo vizinho;
5. repetir o ataque nos produtores materiais irmaos quando compartilham o mesmo contrato persistente.

Um teste que mocka o adaptador que deveria ser verificado nao fecha esta superficie.

## Integridade semantica relacional

Para `structural-contract:relational-semantic-integrity`, o controle primario deve atacar o estado que um caminho feliz coerente nao consegue revelar:

1. escolher dois registros/objetos ligados cuja relacao material dependa da mesma dimensao semantica ou quantidade de dominio;
2. atribuir valores deliberadamente incompatíveis entre os lados;
3. atravessar `create`/`update`/importador/backfill ou outro produtor material, em vez de injetar o estado diretamente no consumidor;
4. provar rejeicao sem efeito parcial ou uma transformacao/conversao explicita que represente cada lado corretamente;
5. observar releitura, aggregate/consumer ou boundary equivalente para comprovar que o estado invalido nao foi persistido nem reinterpretado;
6. repetir ao menos dois casos irmaos variando producer/lifecycle ou ponta da relacao.

Um teste que apenas cria dados coerentes e confirma particoes corretas nao fecha esta superficie. Tambem nao basta testar label, formatter ou `GROUP BY` se o produtor ainda aceita relacoes incompatíveis.

## Escopo evidencia -> efeito

Para a superficie `authorization:evidence-effect-scope`, o controle primario deve provar a relacao semantica entre a fonte autorizadora e o efeito especifico. Use valores divergentes; valores coincidentes nao distinguem uma implementacao que apenas verifica `fonte valida` + `efeito genericamente permitido`.

O `failure_mode`, `procedure`, `expected` e `observed` devem tornar verificavel que um efeito fora do escopo e rejeitado e nao produz mutacao. Quando `source_texts` indicar emergencia, excecao, override, bypass ou fallback, ao menos um caso irmao deve exercer esse branch.

## Qualidade minima

Um controle negativo deve responder: "esta implementacao plausivel e errada falharia aqui?". Se nao, o controle nao fecha o requisito.

Rejeitar texto de preenchimento ou tautologico que apenas satisfaca tamanho/schema. Exemplos proibidos: `Wrong shortcut keeps happy path`, `Silent contract break`, `Run exact-head control`, `Contract holds`, `Observed pass`, `works as expected`, `test passes` e equivalentes. `procedure` deve descrever uma acao reproduzivel e `observed` deve conter uma observacao concreta (contagem, estado, codigo, payload, operacao, span/timer, arquivo/hash ou outro resultado verificavel). Razoes de superficie como `Material surface` ou `Exact-head evidence passed` tambem nao explicam o risco e nao fecham cobertura.

Para familias materiais (`authorization`, `tenant-isolation`, `public-boundary`, `reference-liveness`, `temporal-destination`, `concurrency-atomicity`, `idempotency`, `rollback`, `historical-immutability`), exigir pelo menos dois `sibling_cases` com pares `surface + dimension` distintos por controle negativo. Quando houver mais de uma superficie material, a matriz deve demonstrar ataque cross-surface; duas variacoes dentro de `environment`, por exemplo, nao fecham uma classe que tambem possui `filesystem`.

## Evidencia quantitativa

Quando `source_texts` contiver criterio dependente de percentil, tempo, throughput, cardinalidade, custo, contagem, media movel, projecao, percentual/ratio ou outra metrica observada, o validador exige automaticamente evidencia quantitativa; omitir `evidence_kind` nao torna o gate inaplicavel. O `positive_control` deve ser `evidence_kind=quantitative` e referenciar proveniencia exact-SHA. Quando um controle fecha essa metrica, classificar `evidence_kind=quantitative`. O controle deve referenciar por `evidence_id` uma entrada normalizada de `evidence-provenance.json`; o `subject_sha` dessa entrada deve ser o material head final. Nao copiar apenas `head_sha` novo para o controle nem promover resultado de SHA ancestral por analise do diff. Ver `references/evidence-freshness-gate.md`.

## Portao

Executar `scripts/validate_requirement_attack_matrix.py --requirement-closure ... --attack-matrix ...`. Quando a especificacao ou um controle for quantitativo, incluir obrigatoriamente `--evidence-provenance ...`. Qualquer requisito coberto sem ataque, superficie, evidencia hasheada, regressao, caso irmao discriminante, proveniencia quantitativa fresca ou SHA correto impede `INTERNALLY_APPROVED` e handoff independente.


## Integridade da fonte antes da inferencia

A matriz nunca pode inferir risco a partir de um fechamento resumido. Antes de derivar familias, validar que cada obrigacao preserva exatamente `source_id`, `source_sha256`, `source_line`, `source_text` e `flags` do `specification-snapshot`. Remover texto de uma obrigacao para reduzir familias e falha de contrato. Quando `documentation_consistency.status=passed`, incluir `documentation` em pelo menos um requisito coberto que represente a mudanca normativa, declarar superficie documental (`canonical-claims` ou mais especifica) e executar controle negativo correspondente.
