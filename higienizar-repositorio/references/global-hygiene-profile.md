# Perfil de higienização global
Método, limites de precisão e forma de tratar cada achado da varredura global.
## Quando ler este arquivo
Ler antes de interpretar um relatório de varredura, antes de declarar exceção na política e sempre que a varredura acusar a entrega em curso. O control plane dá o fluxo; este arquivo dá o critério.
## Índice
- [Escopo do perfil](#escopo-do-perfil)
- [Precisão declarada por classe](#precisão-declarada-por-classe)
- [Contrato da política](#contrato-da-política)
- [Exceção aceita](#exceção-aceita)
- [Linha de base e catraca](#linha-de-base-e-catraca)
- [Cobertura e arquivo não analisado](#cobertura-e-arquivo-não-analisado)
- [Work items](#work-items)
- [Fronteira com a higiene do diff](#fronteira-com-a-higiene-do-diff)
- [Quando a varredura acusa a própria entrega](#quando-a-varredura-acusa-a-própria-entrega)
- [Antipadrões](#antipadrões)

## Escopo do perfil
O perfil mede quatro dívidas estruturais sobre a árvore inteira: duplicação, código morto, dependência sem uso e complexidade. Ele não mede estilo, formato, erro estático, cobertura de teste, acoplamento de arquitetura nem qualidade de interface. Nada disso é lacuna acidental: cada ausência tem ferramenta própria no repositório, e sobrepor instrumentos produz duas verdades concorrentes.

A varredura é determinística e offline. Duas execuções sobre a mesma árvore com a mesma política produzem o mesmo relatório, byte a byte, porque não há carimbo de tempo, caminho absoluto nem dependência da ordem do sistema de arquivos. A ordem dos achados é a ordem ordenada da classe e do caminho.

## Precisão declarada por classe
Precisão não é detalhe de implementação: é contrato. Uma classe que acusa errado custa mais caro que uma classe ausente, porque produz trabalho falso e destrói a confiança no relatório. Por isso cada classe prefere não acusar a acusar errado, e declara o que não vê.

| Classe | Vê | Não vê |
| --- | --- | --- |
| `duplication` | Corpo de função normalizado por AST, idêntico entre arquivos, acima do tamanho mínimo | Duplicação entre linguagens, bloco interno de função, equivalência semântica entre corpos diferentes |
| `dead-module` | Módulo sem importador e sem invocação declarada, contando import absoluto e relativo | Referência montada em tempo de execução por nome fora de arquivo texto, plugin carregado por convenção de diretório |
| `dead-symbol` | Função, classe e atribuição simples de nível de módulo sem nenhuma ocorrência do nome na árvore | Uso por `getattr`, por nome montado ou por registro dinâmico; atributo de classe, variável local e nome reexportado por import |
| `unused-dependency` | Requisito declarado que nenhum módulo do escopo importa | Import indireto por caminho condicional, dependência de dependência |
| `complexity` | Complexidade ciclomática do próprio corpo da função acima do teto | Complexidade cognitiva, tamanho de arquivo, acoplamento entre módulos, ramo de função aninhada |

Consequência prática: `dead-symbol` trata **qualquer** ocorrência do nome como referência, porque uma citação em documentação ou em literal de string já indica que alguém depende daquele nome. `dead-module` aceita citação em qualquer arquivo texto da árvore como invocação declarada, pela mesma razão.

Duas precisões valem para a normalização e para a medida, porque errar para mais custa mais caro que não acusar:

- `duplication` apaga nome de variável, de parâmetro e de função chamada, além do literal de documentação. Operador, constante e nome de atributo permanecem: somar não é subtrair, `upper` não é `lower`, e tratar os dois como cópia produziria dívida inexistente.
- `complexity` mede só o corpo da própria função. Função aninhada é unidade própria, medida por si, e gestão de recurso com `with` não cria caminho independente, então não conta como ramo.

## Contrato da política
A política `config/hygiene-policy.json` é a única fonte de limiar, exceção e linha de base. Alterar limiar exige alterar a política, e a alteração fica visível na revisão.

- `scope`: sufixos incluídos, diretórios excluídos e caminhos excluídos. Excluir diretório de teste ou de fixture é decisão declarada, não otimização.
- `scope.exclude_paths`: lista de objetos `{path, reason}`. Excluir um arquivo coberto exige motivo escrito e aparece no relatório em `excluded`; exclusão sem arquivo correspondente reprova, e escopo que não analisa nenhum arquivo reprova, porque nenhum dos dois é árvore limpa.
- `classes.<nome>.state`: `gated` ou `reported`.
- `classes.<nome>.limits`: o que a classe não vê, em texto. Campo obrigatório: classe sem limite declarado reivindica completude, e isso reprova.
- `classes.duplication.min_body_lines`, `classes.complexity.max_complexity`: limiares. São campos obrigatórios: limiar que sai da política não cai em valor padrão escondido no código, ele reprova.
- `classes.unused-dependency.import_name_map`: nome de distribuição para nome de import, quando diferem.
- `classes.unused-dependency.tool_dependencies`: dependência executada como ferramenta, e não importada. `pytest`, `ruff` e `pip-audit` são desse tipo.
- `classes.dead-module.entry_points`: módulo alcançado por convenção, e não por import ou citação.
- `classes.complexity.baseline_history`: história da linha de base, em lista de `{value, reason}`. Ver a seção de linha de base e catraca.

## Exceção aceita
Dívida que não será corrigida agora precisa estar declarada, com o motivo escrito, na lista `accepted` da política. A identidade da exceção é derivada do conteúdo material — classe, caminho, símbolo e, onde existe, o valor medido — e não do número de linha, para que a exceção sobreviva a edição acima dela e morra quando o achado muda de forma: exceção aprovada para uma função de complexidade 3 não vale para a mesma função com complexidade 6.

Exceção órfã reprova. Quando a dívida deixa de existir, a exceção precisa sair na mesma entrega; quando a dívida muda de forma, a identidade muda e a exceção precisa ser reescrita. A regra é intencional: exceção que permanece depois da correção é ruído que esconde o que já foi resolvido.

Justificativa de preenchimento reprova. O validador confere forma — extensão mínima, número de palavras e variedade do texto —, e o motivo precisa explicar por que a correção não entra agora e o que a destrava. O gate confere a forma porque forma é verificável por máquina; o mérito do motivo é da revisão independente, e o gate não finge julgar isso.

Classe medida contra linha de base não aceita exceção item a item. A dívida dela é agregada, e aceitar um item esconderia exatamente a contagem que a linha de base existe para medir: o caminho para conviver com ela é ajustar a linha de base com motivo declarado, não apagar a ocorrência.

## Linha de base e catraca
Classe `reported` existe para dívida estrutural pré-existente, como complexidade, que não se resolve declarando item a item. A política declara a contagem da linha de base, e o validador exige que a contagem medida seja **exatamente** igual a ela:

- contagem acima da linha de base é dívida nova e reprova;
- contagem abaixo é linha de base folgada e também reprova, porque deixa de medir o que já foi corrigido.

Reduzir a linha de base registra progresso de forma verificável. Aumentar exige entrada nova na história declarada, com motivo escrito, e a linha de base corrente precisa ser o último valor dessa história:

```json
"baseline_history": [
  {"value": 47, "reason": "Medição inicial da árvore na entrada do perfil."},
  {"value": 49, "reason": "Dívida nova aceita por decisão declarada, com work item aberto."}
]
```

A história é a forma verificável de catraca sem depender do histórico do Git, que o clone raso do CI não garante. O que ela não prova é que ninguém reescreveu a história inteira; o que ela garante é que crescer deixou de ser um número solto e passou a exigir um motivo escrito, visível na revisão.

## Cobertura e arquivo não analisado
Arquivo que o escopo inclui e a varredura não conseguiu analisar aparece em `not_analyzed`, com causa: erro de sintaxe, arquivo ilegível, link simbólico quebrado, caminho que não é arquivo regular, caminho que resolve para fora da raiz. O validador reprova enquanto o caminho não estiver corrigido ou declarado em `not_analyzed_allowed`, com justificativa — e reprova também no sentido inverso: permissão declarada que não corresponde a nenhum arquivo não analisado é exceção órfã.

A validação é somente leitura sobre a árvore varrida, inclusive na conferência do contrato do relatório, que acontece em memória. Validar não escreve, não altera e não remove arquivo na raiz analisada, e por isso a varredura pode rodar em árvore somente leitura.

A regra existe porque cobertura que encolhe em silêncio é indistinguível de aprovação. Um arquivo que sai do conjunto analisado sem aparecer no relatório faz o número melhorar sem que a árvore melhore.

## Work items
A varredura produz um work item por classe com achado, não um por achado. A classe é a unidade de decisão: corrigir, aceitar com justificativa ou rebaixar o limiar. Dezenas de ocorrências da mesma dívida viram uma linha cada dentro de um work item, e não dezenas de issues.

O corpo sai na forma canônica lida pelos extratores de requisito, com uma linha por item nas seções normativas. O artefato não abre issue: abrir issue é ação externa com efeito para terceiros, e a decisão de abrir, priorizar e executar é do ciclo de entrega.

## Fronteira com a higiene do diff
`entregar-issue/references/hygiene.md` continua sendo a higiene da entrega: arquivo tocado, consumidor direto, símbolo substituído. Esta skill mede a árvore inteira, sob demanda, e não substitui nenhum gate do ciclo.

Os três instrumentos convivem sem sobreposição:

| Instrumento | Alcance | Quando roda |
| --- | --- | --- |
| Higiene do diff (`GROUND-DEAD-001`, `CODE-GROWTH-001`) | Arquivos tocados pela entrega | Em toda entrega |
| Gate de lint e análise estática | Estilo, formato, erro estático | Em toda entrega |
| Perfil de higiene global | Árvore inteira, quatro classes estruturais | Sob demanda |

## Quando a varredura acusa a própria entrega
Achado novo na entrega em curso é bloqueante, não ruído. A ordem de tratamento é: corrigir quando for correto corrigir; declarar exceção com justificativa quando a correção exigir entrega própria; emitir work item nos dois casos.

Achado novo em código que a entrega escreveu e sobre o qual ela tem autoridade é o caso mais forte, porque o custo de corrigir é o menor possível e a alternativa é registrar dívida que nasceu agora.

## Antipadrões
- Absorver achado novo aumentando a linha de base, ou declarando exceção sem motivo escrito.
- Rebaixar limiar para o achado desaparecer: o teto existe para medir, e rebaixá-lo muda o que se mede sem mudar o que existe.
- Tratar `not_analyzed` como limpo, ou encolher o escopo de varredura para o relatório ficar bom.
- Usar o relatório para afirmar ausência de dívida onde a classe declara limite de precisão.
- Corrigir código morto sem conferir uso dinâmico, trocando dívida por regressão.
- Ler o relatório sem antes conferir a política: número sem limite declarado não significa nada.