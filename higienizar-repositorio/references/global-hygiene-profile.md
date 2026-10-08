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
- [Modo direcionado](#modo-direcionado)
- [Fronteira com a higiene do diff](#fronteira-com-a-higiene-do-diff)
- [Quando a varredura acusa a própria entrega](#quando-a-varredura-acusa-a-própria-entrega)
- [Antipadrões](#antipadrões)

## Escopo do perfil
O perfil mede cinco dívidas estruturais sobre a árvore inteira: duplicação, código morto, dependência sem uso e complexidade. Ele não mede estilo, formato, erro estático, cobertura de teste, acoplamento de arquitetura nem qualidade de interface. Nada disso é lacuna acidental: cada ausência tem ferramenta própria no repositório, e sobrepor instrumentos produz duas verdades concorrentes.

A varredura é determinística e offline. Duas execuções sobre a mesma árvore com a mesma política produzem o mesmo relatório, byte a byte, porque não há carimbo de tempo, caminho absoluto nem dependência da ordem do sistema de arquivos. A ordem dos achados é a ordem ordenada da classe e do caminho.

## Precisão declarada por classe
Precisão não é detalhe de implementação: é contrato. Uma classe que acusa errado custa mais caro que uma classe ausente, porque produz trabalho falso e destrói a confiança no relatório. Por isso cada classe prefere não acusar a acusar errado, e declara o que não vê.

| Classe | Vê | Não vê |
| --- | --- | --- |
| `duplication` | Corpo de função normalizado por AST, idêntico entre funções, inclusive no mesmo arquivo, acima do tamanho mínimo, contado em instruções do corpo | Duplicação entre linguagens, bloco interno de função, equivalência semântica entre corpos diferentes, corpo com menos instruções que o limiar |
| `dead-module` | Módulo sem importador e sem invocação declarada, com import absoluto resolvido pela raiz e pelo diretório de quem importa e import relativo resolvido pelo pacote, sem alcançar além dele; citação resolvida por caminho, com o sufixo declarado terminando o nome e com `..` recusado apenas quando o caminho resolvido sai da raiz, e nome solto só quando é único no escopo medido, para que arquivo excluído não torne ambígua a citação de um nome único; diretório de teste fica fora quando a política declara `exclude_tests` e arquivo de pacote é ponto de entrada quando declara `package_init_is_entry` | Referência montada em tempo de execução por nome fora de arquivo texto, plugin carregado por convenção de diretório, citação que sai da raiz |
| `dead-symbol` | Função, classe e atribuição simples de nível de módulo sem nenhuma ocorrência do nome na árvore, contando os formatos de texto declarados em `scope.corpus_suffixes` | Uso por `getattr`, por nome montado ou por registro dinâmico; atributo de classe, variável local e nome reexportado por import; nome de protocolo declarado em `ignore_names` |
| `unused-dependency` | Requisito declarado que nenhum módulo do escopo importa, em manifest cujo nome casa com `manifest_patterns` | Import indireto por caminho condicional, dependência de dependência, manifest em diretório ou caminho excluído, `setup.cfg`, `setup.py`, `requirements.in` e arquivo de trava |
| `complexity` | Complexidade ciclomática do próprio corpo da função acima do teto | Complexidade cognitiva, tamanho de arquivo, acoplamento entre módulos, ramo de função aninhada, ramo de default de parâmetro e de decorator, e lambda |
| Identidade | Rótulo `arquivo::símbolo`, com ordem de aparição quando o nome se repete no mesmo arquivo, e identidade derivada de conteúdo material | Número de linha: mover código não muda achado nem exceção aceita |

Consequência prática: `dead-symbol` trata **qualquer** ocorrência do nome como referência, porque uma citação em documentação ou em literal de string já indica que alguém depende daquele nome. `dead-module` aceita citação em qualquer arquivo texto da árvore como invocação declarada, pela mesma razão.

Duas precisões valem para a normalização e para a medida, porque errar para mais custa mais caro que não acusar:

- `duplication` apaga nome de variável, de parâmetro, de função chamada e de definição aninhada, além do literal de documentação. Operador, constante e nome de atributo permanecem: somar não é subtrair, `upper` não é `lower`, e tratar os dois como cópia produziria dívida inexistente. Apagar menos também custa: renomear uma variável esconderia a cópia, e o achado sumiria sem que a dívida saísse.
- `complexity` mede só o corpo da própria função. Função aninhada é unidade própria, medida por si, e gestão de recurso com `with` não cria caminho independente, então não conta como ramo.
- Identificador apagado é o que liga nome: variável, parâmetro, função chamada, definição aninhada e nome capturado por padrão estrutural, como `case int(left)`. Nome de argumento nomeado permanece, porque `make(left=x)` e `make(right=x)` são chamadas diferentes, e o rótulo de definição repetida é calculado sobre todas as definições do arquivo, inclusive as que ficam abaixo do limiar.
- `dead-module` não resolve semântica dinâmica: `__all__` reatribuído, anotado ou montado em execução faz o wildcard contar como alcançado sem ser estreitado pela sombra direta, import condicional conta como alcançado, e a ligação anterior ao primeiro import do `__init__` bloqueia o submódulo.
- `dead-module` mede alcançabilidade **direta**, e não transitiva, e a sombra do atributo vale nas duas formas de `from`, relativa e absoluta, inclusive com o pacote da raiz; import que executa o submódulo não sombreia, e `from pkg import *` alcança o que o `__all__` declara: módulo alcançado apenas por outro módulo morto não entra no achado. Importador não conta como importador de si mesmo, e `from base import name` só mantém o submódulo vivo quando `base` é pacote e não define `name`.
- Identificador e caminho de arquivo seguem a gramática de Python, e não classe de caractere: marca combinante e símbolo fora do plano básico contam como nome, citação é ancorada no sufixo declarado e recolhida para trás até um caractere que não pode fazer parte de nome de arquivo, o sufixo precisa terminar o nome para que a citação valha, e tratar ASCII acusaria dívida em código correto.

## Contrato da política
A política `config/hygiene-policy.json` é a única fonte de limiar, exceção e linha de base. Alterar limiar exige alterar a política, e a alteração fica visível na revisão. Toda chave de decisão é obrigatória, e a varredura reprova política incompleta do mesmo modo que o validador: medir com default implícito produziria evidência que a política não sustenta.
Exceção sem motivo escrito e supressor declarativo sem motivo escrito, em `entry_points` e em `ignore_names`, também reprovam: cada supressor declara `name` e `reason`, porque lista de texto solto esconde nome ou caminho arbitrário sem deixar rastro auditável. O comando que produz o relatório confere o contrato antes de gravar, e por isso não publica artefato que o validador recusaria.

- `scope`: sufixos incluídos, diretórios excluídos e caminhos excluídos. Excluir diretório de teste ou de fixture é decisão declarada, não otimização. A entrada de diretório cobre a subárvore inteira e pode ser caminho composto (`evals/fixtures`), e a exclusão vale para todas as classes, inclusive a de dependência sem uso.
- `scope.exclude_paths`: lista de objetos `{path, reason}`. Excluir um arquivo coberto exige motivo escrito e aparece no relatório em `excluded`; exclusão sem arquivo correspondente reprova, e escopo que não analisa nenhum arquivo reprova, porque nenhum dos dois é árvore limpa. Import relativo só alcança irmão quando o pacote de quem importa existe: na raiz, `from . import x` exige `__init__.py` na raiz, e além do pacote o relativo não alcança módulo nenhum.

O caminho precisa ser relativo e ficar dentro da raiz: exclusão que sai da árvore aparentaria excluir algo do repositório sem excluir nada.
- `scope.corpus_suffixes`: formatos de texto conferidos na busca por citação de módulo e de símbolo. A lista fica na política porque formato fora dela não é visto, e limite de formato escondido no código produz falso positivo em classe `gated`.
- `classes.<nome>.state`: `gated` ou `reported`.
- `classes.<nome>.limits`: o que a classe não vê, em texto. Campo obrigatório: classe sem limite declarado reivindica completude, e isso reprova.
- `classes.duplication.min_body_lines`, `classes.complexity.max_complexity`: limiares. São campos obrigatórios: limiar que sai da política não cai em valor padrão escondido no código, ele reprova.
- `classes.unused-dependency.import_name_map`: nome de distribuição para nome de import, quando diferem.
- `classes.unused-dependency.tool_dependencies`: dependência executada como ferramenta, e não importada. `pytest`, `ruff` e `pip-audit` são desse tipo.
- `classes.dead-module.entry_points`: módulo alcançado por convenção, e não por import ou citação.
- `classes.dead-module.exclude_tests`: diretório de teste fora da varredura de módulo, porque teste é alcançado pelo executor e não por import do produto. A exclusão é declarada, e não fixa no código.
- `classes.dead-module.package_init_is_entry`: arquivo de pacote como ponto de entrada, porque é alcançado pelo import de quem usa o pacote, e não por citação no repositório. Também declarado, pela mesma razão.
- `classes.duplication.min_body_lines` conta instruções do corpo: instrução de várias linhas conta uma, e linha vazia, comentário, decorator, assinatura e literal de documentação não contam. O valor foi re-derivado quando a medida passou a contar instruções, para não encolher a classe em silêncio.
- Toda chave de decisão é obrigatória na política: `exclude_declared_copies`, `exclude_tests`, `package_init_is_entry`, `ignore_names`, `entry_points`, `import_name_map` e `tool_dependencies` ausentes são erro de política, e não default silencioso do código.
- `classes.dead-symbol.ignore_names`: nome de protocolo consumido pelo próprio interpretador. Também declarado, pela mesma razão: exceção escondida no código não é auditável.
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

Toda medição da linha de base registra progresso de forma verificável e exige motivo escrito, inclusive a redução: valor sem motivo não é conferível por quem audita, e a história é a evidência da medição. A linha de base corrente precisa ser o último valor dessa história:

```json
"baseline_history": [
  {"value": 47, "reason": "Medição inicial da árvore na entrada do perfil."},
  {"value": 49, "reason": "Dívida nova aceita por decisão declarada, com work item aberto."}
]
```

A história é a forma verificável de catraca sem depender do histórico do Git, que o clone raso do CI não garante. O que ela não prova é que ninguém reescreveu a história inteira; o que ela garante é que crescer deixou de ser um número solto e passou a exigir um motivo escrito, visível na revisão.

## Cobertura e arquivo não analisado
Arquivo que o escopo inclui e a varredura não conseguiu analisar aparece em `not_analyzed`, com causa: erro de sintaxe, arquivo ilegível, diretório ilegível, link simbólico quebrado, link simbólico de diretório, caminho que não é arquivo regular, caminho que resolve para fora da raiz. Manifest ilegível e alvo direcionado que não existe entram pela mesma razão, porque os dois são cobertura que encolheria em silêncio. A árvore medida é o único escopo de citação: o índice de nomes soltos é o do escopo declarado, a autocitação não conta como invocação, e link de corpus que sai da raiz entra em cobertura não analisada em vez de virar homônimo medido. O modo direcionado restringe também os manifests, e alvo que escapa da raiz deixa o escopo vazio em vez de reabrir o percurso livre; link quebrado e link em ciclo recebem o mesmo rótulo do percurso livre, e caminho de fora da raiz é publicado só pelo nome, para que cópias equivalentes produzam relatórios iguais.

A varredura percorre a árvore por conta própria: `rglob` não desce diretório sem permissão de leitura e não segue link, e as duas coisas encolheriam a cobertura sem aparecer no relatório. O percurso começa no alvo do modo direcionado, mas o rótulo da recusa é sempre relativo à raiz do repositório, e o corpus de citação é percorrido do mesmo modo: sem isso, um diretório recusado fora do alvo sumiria do relatório em modo direcionado a arquivo.
O motivo de cobertura é escrito com caminho relativo, nunca absoluto: duas cópias idênticas da mesma árvore precisam produzir o mesmo relatório, e a evidência não pode depender de onde o repositório está no disco. Pela mesma razão, `not_analyzed_allowed` exige caminho relativo canônico dentro da raiz, como a exclusão de escopo. O validador reprova enquanto o caminho não estiver corrigido ou declarado em `not_analyzed_allowed`, com justificativa — e reprova também no sentido inverso: permissão declarada que não corresponde a nenhum arquivo não analisado é exceção órfã.

A leitura de texto para citacao fica contida na raiz, e o mesmo vale para manifest: link que resolve para fora da árvore entra em `not_analyzed`, porque conteudo de fora nao pode apagar achado da arvore medida. Link quebrado em formato de texto tambem entra, porque cobertura que nao foi lida nao pode passar por arvore limpa. A validação é somente leitura sobre a árvore varrida, inclusive na conferência do contrato do relatório, que acontece em memória. Validar não escreve, não altera e não remove arquivo na raiz analisada, e por isso a varredura pode rodar em árvore somente leitura.

A regra existe porque cobertura que encolhe em silêncio é indistinguível de aprovação. Um arquivo que sai do conjunto analisado sem aparecer no relatório faz o número melhorar sem que a árvore melhore.

## Work items
A varredura produz um work item por classe com achado, não um por achado. A classe é a unidade de decisão: corrigir, aceitar com justificativa ou rebaixar o limiar. Dezenas de ocorrências da mesma dívida viram uma linha cada dentro de um work item, e não dezenas de issues.

O corpo sai na forma canônica lida pelos extratores de requisito, com uma linha por item nas seções normativas. O artefato não abre issue: abrir issue é ação externa com efeito para terceiros, e a decisão de abrir, priorizar e executar é do ciclo de entrega.

## Modo direcionado
O manifest é lido pelo formato declarado: `requirements*.txt` declara um requisito por linha, e `pyproject.toml` declara em `project.dependencies`, em `project.optional-dependencies` e nas tabelas do Poetry, com `python` fora da contagem nas duas formas porque é a versão exigida do interpretador. Formato sem leitura declarada entra em cobertura não analisada em vez de ser interpretado como lista de linhas, estrutura inválida dentro de formato declarado também é recusa visível, inclusive na hierarquia de grupos do Poetry e em tabela declarada como escalar, e arquivo de trava é reconhecido por convenção de nome, `.lock` no fim ou `.lock.` no meio, em qualquer padrão declarado. Formato sem leitura declarada é recusado em vez de interpretado como lista de linhas, e arquivo de trava fica de fora porque é gerado do próprio manifest. O conjunto de padrões de nome vem da política, em `manifest_patterns`: conjunto fixo no código seria escopo escondido, e padrão com separador de caminho mediria um diretório só sem dizer isso.
A política declara decisão por classe, e chave de outra classe não é aceita: a lista de chaves conhecidas de cada classe é a mesma tabela que exige as chaves, para que declarar e medir não divirjam. Supressor com tipo errado reprova, e diretório excluído exige caminho relativo canônico, sem `.`, `..`, barra duplicada nem barra final: forma não canônica exclui outro diretório, e escopo reduzido por declaração precisa ser visível no relatório JSON e no Markdown.


O relatório é evidência sobre a árvore e por isso não pode ser gravado dentro dela: um relatório na árvore medida entra no corpus de citação, muda a medição seguinte e pode sobrescrever arquivo coberto. O mesmo vale para o diretório de work items, pela mesma razão. A versão da política é o inteiro exato declarado, e não um valor que apenas se compara a ele: `1.0` é igual a `1` em Python e não é a versão declarada.

O gerador de work items entra pela mesma porta e vai além: confere a política, recusa varredura com buraco de cobertura e recusa relatório que não corresponde à árvore e à política atuais, inclusive quando recebido por `--report`, porque work item derivado de relatório de outra árvore descreveria dívida que já não existe.

Pela mesma razão, o comando da varredura confere a política antes de medir, recusa o que o gate recusa e só publica o relatório depois de a política passar: artefato gravado antes da reprovação circularia como evidência de uma medição que a política não sustenta.

O modo direcionado restringe o conjunto analisado: arquivos, manifests e, portanto, os achados das cinco classes. Alvo em diretório cobre a subárvore, e o manifest é lido do módulo analisado, não do corpus de citação: o corpus existe para citar, e não para decidir import. As formas `sub`, `./sub` e `sub/` são o mesmo alvo. A busca por citação continua lendo a árvore inteira, porque citação é propriedade da árvore: restringi-la ao alvo faria um nome citado fora do alvo parecer morto dentro dele, que é falso positivo em classe `gated`. O modo é para conferir um subsistema, e não para reduzir o custo de leitura.
## Fronteira com a higiene do diff
`entregar-issue/references/hygiene.md` continua sendo a higiene da entrega: arquivo tocado, consumidor direto, símbolo substituído. Esta skill mede a árvore inteira, sob demanda, e não substitui nenhum gate do ciclo.

Os três instrumentos convivem sem sobreposição:

| Instrumento | Alcance | Quando roda |
| --- | --- | --- |
| Higiene do diff (`GROUND-DEAD-001`, `CODE-GROWTH-001`) | Arquivos tocados pela entrega | Em toda entrega |
| Gate de lint e análise estática | Estilo, formato, erro estático | Em toda entrega |
| Perfil de higiene global | Árvore inteira, cinco classes estruturais | Sob demanda |

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