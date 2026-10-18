# Saturacao adversarial por equivalencia semantica

## Objetivo e disparador
Aplicar a detectores estaticos, parsers, verificadores de proveniencia e regras de governanca com escapes recorrentes. Esta etapa complementa `blocker-harvest.md` e `adversarial-control-design.md`; nao substitui o preflight do contrato ou a revisao realmente independente.

## Protocolo
1. Fixar SHA de material, baseline, contrato e arquivos de teste. Catalogar os escapes independentes anteriores com IDs estaveis e estado `resolved|still-open|regressed|not-applicable`.
2. Extrair invariantes em vez de nomes de exemplos. Para cada regra, identificar resultado esperado quando a representacao muda mas o significado nao muda (metamorfismo) e quando o dado e substituido/nao consumido.
3. Construir matriz `origem -> binding/escopo -> transformacao -> fluxo -> consumo -> fronteira` para superficies materiais. Dimensoes orientadoras:
   - origem: import ES, CommonJS, reexport, JSON por fs, runtime e fonte inerte;
   - binding: const, let, parametros, destructuring, alias local/modular, shadowing, reatribuicao;
   - transformacao: identidade direta, chamada transparente, projecao escalar/registro, `slice`, `concat`, `toSorted`, `Array.from`, spread, transformacao opaca;
   - fluxo: direto, ternario, ramos opcionais/exaustivos, loop;
   - consumo: comparacao, switch, find/some/filter/includes/indexacao e efeito decisorio;
   - fronteira: producao, fixture importada, teste isolado, UI, administrativo e exercicio.
4. Aplicar cobertura *pairwise* sobre dimensoes aplicaveis e adicionar manualmente sequencias criticas de 3 ou mais eixos; evitar explosao cartesiana. Nao declarar numero fixo de cenarios como prova de exaustividade.
5. Executar pelo menos um controle positivo e um negativo discriminante para cada superficie. Os positivos devem criar violacao real e falhar `evaluate...Gate`; negativos devem permanecer isentos de findings indevidos. Para cada mutacao, registrar `expected`, `observed`, `status`, `source_sha256`, `head_sha`, `procedure` e familia/superficie/dimensoes.
6. Fazer *mutation testing* seguro: injetar violacoes em workspace isolado/temporario, nunca em `develop` nem no branch do candidato. Um mutante critico sobrevivente e blocker se o contrato exige o bloqueio. Restaurar ambiente apos executar.
7. Parar **somente provas caras nao relacionadas** apos primeiro blocker. Continuar colheita estatica barata por outras familias materiais e casos irmaos antes do parecer; agrupar por causa raiz, sem teto de 2/3 findings.
8. Marcar cada superficie `covered|not-applicable|not-executed`, com justificativa, e declarar cobertura limitada quando houver lacunas. Nunca chamar CI verde de comprovacao de que nao existem outras evasoes.
9. Em reauditoria, reexecutar os casos anteriores mais casos irmaos relevantes no SHA novo. Se o SHA mudou, nao reutilizar aprovacao nem digest anterior.

## Oraculo nao circular
O esperado de cada caso deve derivar da ADR, issue e invariantes, nunca do retorno atual do proprio detector. Controles negativos precisam provar que a ampliacao de uma regra nao bloqueia status, UI, exercicio ou dado JSON nao consumido. Em entradas semanticamente equivalentes, resultados equivalentes sao obrigatorios; divergencia exige finding e reprodutor minimo.

## Registro de cobertura sugerido
Por linha: `requirement_id, risk_family, surface, axis_values, positive_control_id, negative_control_id, mutation_ids, expected, observed, executed, passed, head_sha, evidence_sha256, disposition`. Status ausente ou apenas teste declarado nao satura superficie. Anexar a matriz ao parecer; nao bloquear entrega apenas por casos explicitamente fora da issue.

## Exemplo de classe (Food Architecture)
Se `rows.find(row => row.name === input)` e bloquear um catalogo JSON, os equivalentes `rows.toSorted().find(...)`, `rows.concat([]).find(...)` e `Array.from(rows).find(...)` nao podem perder proveniencia por mudar a forma de percorrer o mesmo dado. Se `foodName === "pao"` e viola o gate, `const key="pao"; foodName === key` deve ter o mesmo julgamento **quando a constante imutavel e a identidade alimentar forem comprovadas**. `let key` reassigned, objeto fs sombreado e parametro administrativo sao controles negativos distintos.
