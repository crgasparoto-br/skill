# Estudo de caso nao normativo: Issue #1300 (Food Intelligence V2)

## Finalidade e escopo

Este registro preserva exemplos que motivaram o protocolo de saturacao semantica aplicado em `auditar-issue` e `entregar-issue`. Refere-se especificamente a Issue #1300 e a PR #1324 em `crgasparoto-br/controle_calorias`. **Nao** define gates universais, nao cria obrigacoes para outros projetos e nao substitui requisitos da issue, ADRs ou auditoria independente.

## Familia historica de ataques

- Proveniencia de catalogo JSON: quando `rows.find(row => row.name === input)` deve ser bloqueado pelo gate, formas semanticamente equivalentes como `rows.toSorted().find(...)`, `rows.concat([]).find(...)` e `Array.from(rows).find(...)` tambem devem preservar o veredito, **se** origem e consumo decisorio forem comprovados.
- Comparacao e alias imutavel: se `foodName === "pao"` viola o contrato especifico, `const key = "pao"; foodName === key` nao pode escapar somente pelo alias, desde que a imutabilidade e a identidade alimentar sejam demonstradas.
- Controles negativos: reatribuicao de `let key`, objeto `fs` sombreado, lista de dados carregada mas nao consumida, codigo administrativo e ramo fora do escopo nao devem gerar findings sem nexo com a regra.
- F41/F42: IDs de findings historicos da Issue #1300. Sua correcao e replay pertencem ao alvo original e nao sao tarefas obrigatorias em outras issues.

## Criterio de reutilizacao

Usar este documento apenas como exemplo ou regressao historica quando o trabalho corrente apresentar superficies semanticamente comparaveis e houver um contrato proprio que justifique os testes. Em qualquer outro caso, derivar os controles a partir do codigo, issue e riscos do projeto corrente. Nao carregar este estudo de caso automaticamente nas duas Skills.

## Protocolo universal correspondente

As instrucoes gerais permanecem nas referencias de `auditar-issue` e `entregar-issue` chamadas `semantic-mutation-saturation.md`. O registro historico nao altera nem amplia seu escopo normativo.
