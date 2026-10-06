# Gate de saturacao de risco antes do handoff

## Objetivo

Impedir que uma familia **ou uma superficie material da mesma familia** seja descoberta pela primeira vez na auditoria independente.

## Familias canonicas

Classificar explicitamente toda entrega nas familias:

- `authorization`;
- `tenant-isolation`;
- `public-boundary`;
- `reference-liveness`;
- `temporal-consistency`;
- `temporal-destination`;
- `concurrency-atomicity`;
- `idempotency`;
- `rollback`;
- `historical-immutability`;
- `structural-contract`;
- `documentation`.

Cada familia deve aparecer em `.audit/entregar-issue/risk-saturation.json` como `applicable=true|false`, com motivo. Quando `documentation_consistency.status=passed` por mudanca semantica normativa, `documentation` obrigatoriamente e material, deve existir em `requirement-attack-matrix.json` com superficie `canonical-claims` (ou superficie documental mais especifica) e nao pode ser marcada `not-applicable`. Familia aplicavel exige `status=passed`, `control_ids` e `dimensions` para **todas** as superficies declaradas na `requirement-attack-matrix.json`.

Cada entrada de `dimensions` deve possuir:

- `surface`: nome estavel da superficie;
- `reason`: por que a superficie e material;
- `control_ids`: controles negativos primarios cuja `risk_family + surface` coincida exatamente;
- `status=passed` no SHA congelado.

Uma familia nao esta saturada quando apenas uma de suas superficies esta verde. Exemplo: `authorization.environment=passed` nao permite fechar `authorization` se a arquitetura tambem expuser `filesystem`, `persistent-credential-store` ou outra superficie material.
Para `structural-contract:relational-semantic-integrity`, uma suite com fixtures coerentes no consumidor nao satura a superficie: deve existir controle `REL-SEM-001` no produtor canonico com valores incompatíveis e casos irmaos de lifecycle/produtor.
 Para relatorios sujeitos a retencao, `temporal-destination:retention-expiry` nao substitui `temporal-consistency:reporting-availability-window`: e obrigatorio provar separadamente que o dado e eliminado no cutoff correto e que a consulta rotula corretamente a cobertura restante.

## Precisao da inferencia

A rederivacao deve ser fail-closed sem criar familias artificiais:

- `atomicity` do extrator nao implica sozinho `concurrency-atomicity`; exigir sinais concretos como concorrencia, serializacao, lock ou transacao concorrente. Fonte unica/canonica pertence a `structural-contract`;
- clausula que exija tenant, perfil, organizacao ou workspace `isolado`, `segregado`, sem vazamento ou equivalente ativa `tenant-isolation:tenant-scope-isolation`, mesmo que a mesma frase tambem mencione `perfil` e portanto ative `authorization`; nao permitir que `authorization` substitua isolamento. O controle negativo deve usar pelo menos dois escopos deliberadamente distintos e provar que dados do escopo irmao nao aparecem nem influenciam o resultado do escopo alvo;
- `complete/completa` isolado nao ativa `temporal-consistency:reporting-availability-window`; exigir contexto de relatorio, cobertura, disponibilidade, janela, retencao ou historico disponivel;
- alvo derivado da sessao autenticada ativa `authorization:session-target-binding`; proibicao de body/request escolher ou sobrescrever o alvo ativa `public-boundary:request-target-override`;
- catalogo/definicao canonica compartilhada ativa `structural-contract:canonical-source-consistency`;
- clausula que enumera casos obrigatorios de teste ativa `structural-contract:specified-test-matrix` e deve ser saturada caso a caso.

Superficie falsa nao compensa superficie real ausente; o gate deve preferir a semantica canonica especifica ao token isolado.

## Varredura de saturacao

Inicializar com `python <skill>/scripts/init_risk_saturation.py --attack-matrix <requirement-attack-matrix.json> --out <risk-saturation.json>`.

Antes do freeze:

1. rederivar familias a partir da especificacao, nao apenas do diff nem da propria matriz; o validador deve cruzar `requirement-closure.json` com a matriz para impedir autoclassificacao circular e recusar fechamento cujo `source_text`/flags nao coincidam com o snapshot canonico;
2. rederivar superficies a partir de requisitos, implementacao errada plausivel, entrypoints, processos, filesystem, stores persistentes, artifacts, estados e fronteiras publicas; para `relational-semantic-integrity`, incluir produtores/mutacoes que podem criar registros semanticamente incompatíveis, nao apenas o consumidor que agrega ou rotula;
3. cruzar cada `family + surface` com controles negativos primarios executados e com `inherited-controls.json`; controle herdado ativo mantem sua familia/superficie material, mesmo que a matriz corrente tente omiti-la;
4. procurar familias e superficies sem controle discriminante;
5. para cada lacuna, criar ataque antes de publicar candidato;
6. depois do primeiro finding interno, continuar a varredura barata por todos os requisitos/familias/superficies ainda nao saturados, nao apenas pela mesma causa raiz.

## Audit escapes

Quando existir `audit-escape-closure.json` com `status=passed`, cada escape deve declarar `required_attack_dimensions`. Cada item possui `risk_family`, `surface` e `dimension`. O gate de saturacao confirma que essas dimensoes existem de fato na matriz atual, inclusive quando aparecem como casos irmaos.

Para uma classe que escapou por um canal e reapareceu por outro, as dimensoes obrigatorias devem atravessar superficies. Nao aceitar fechamento de `role-secret-boundary-leak`, por exemplo, apenas com duas variacoes de `environment` quando filesystem ou credential store persistente estiverem presentes.

## Portao

Executar `scripts/validate_risk_saturation.py --attack-matrix ... --risk-saturation ... --requirement-closure ... --inherited-controls ...`. O gate rederiva as familias canonicas diretamente das obrigacoes cobertas e bloqueia quando a especificacao exige uma familia omitida pela matriz ou marcada `not-applicable`. `material_families_missing_controls` deve estar vazio, toda superficie requerida deve possuir dimensao `passed` com controle correspondente, e todas as `required_attack_dimensions` de escapes fechados devem estar cobertas. Qualquer lacuna impede handoff.


## Fontes nao circulares de materialidade

A aplicabilidade final e a uniao minima de: obrigacoes canonicas preservadas na `requirement-closure`, familias/superficies da matriz, controles herdados ativos e `documentation_consistency.status=passed`. Nao permitir que uma regeneracao da matriz reduza essa uniao. Apos rejeicao independente, `not-applicable` em controle herdado exige prova exact-head e e invalido enquanto a fonte canonica ainda exigir a familia; use `superseded` quando o mecanismo de controle mudou.
