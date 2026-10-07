---
name: higienizar-repositorio
description: Varrer o repositorio inteiro sob demanda em busca de duplicacao, codigo morto, dependencia sem uso e complexidade, produzindo relatorio verificavel e work items na forma canonica de issue. Usar para medir divida estrutural que a higiene limitada ao diff da entrega nao alcanca, para auditar o estado de higienizacao de um repositorio legado e para abrir trabalho de limpeza com evidencia. Nao implementa correcao, nao abre issue e nao tem autoridade de merge.
---
# Higienizacao global do repositorio
## Objetivo
Medir divida estrutural da arvore inteira e transforma-la em trabalho rastreavel.

A higiene que acompanha uma entrega olha o diff: arquivo tocado, consumidor direto, caminho substituido. Isso garante nao-regressao, e nao higienizacao. Um repositorio legado pode receber dezenas de entregas corretas dentro de um modulo ja sujo, e nada mede isso. Esta skill cobre a lacuna: varredura completa, sob demanda, com relatorio deterministico e work items prontos para virar issue.

## Quando usar
- Pedido explicito de varredura de higiene, limpeza, divida tecnica ou codigo morto no repositorio inteiro.
- Auditoria periodica do estado de higienizacao, inclusive como entrada de planejamento.
- Suspeita de duplicacao entre skills, de dependencia declarada e nunca usada ou de simbolo abandonado.
- Antes de um release, para medir se a linha de base de cada classe piorou.

## Quando nao usar
- Correcao pontual do diff de uma entrega: usar `entregar-issue/references/hygiene.md`.
- Estilo, formato e erro estatico: usar o gate de lint do repositorio.
- Alcance de arquivo operacional dentro de uma skill: usar o validador de alcance de arquivo operacional do repositorio.
- Qualquer implementacao: esta skill nao corrige, nao abre issue e nao mergeia.

## Modos
- `sweep`: varredura completa da arvore, todas as classes ativas, politica declarada. Modo padrao.
- `targeted`: varredura restrita a caminhos declarados, para conferir um subsistema sem varrer o repositorio.

## Autoridade e fronteira
- Somente leitura sobre o produto: a varredura escreve apenas o relatorio e os work items.
- Sem autoridade de merge, sem autoridade de implementacao e sem abertura automatica de issue.
- Work item produzido aqui e entrada para o controlador de entrega, que decide escopo, prioridade e execucao.
- A politica e a unica fonte de limiar, exclusao, excecao e linha de base. Nenhum limiar vive no codigo, e limiar exigido pela classe precisa estar declarado: campo ausente nao cai em default escondido.
- A varredura e somente leitura inclusive na validacao: o gate confere o relatorio contra o schema em memoria, sem criar, alterar ou remover arquivo na raiz varrida.

## Classes de deteccao
- `duplication`: corpos de funcao normalizados por AST, identicos entre funcoes, inclusive no mesmo arquivo, porque duas copias divergem na primeira alteracao. A normalizacao apaga nome de variavel, de parametro, de funcao chamada e de definicao aninhada, e o literal de documentacao; operador, constante e nome de atributo permanecem, porque somar nao e subtrair. Copia declarada em `config/shared-files.json` e exclusao legitima, e nao achado.
- `dead-module`: modulo que nenhum outro modulo importa e que nenhuma invocacao declarada alcanca. O import e resolvido contra a raiz, contra o diretorio de quem importa — script de skill roda com o proprio diretorio no caminho de importacao — e contra o pacote, no caso do import relativo.
- `dead-symbol`: simbolo de nivel de modulo — funcao, classe e atribuicao simples — cujo nome nao aparece em nenhum lugar da arvore alem da propria definicao.
- `unused-dependency`: requisito declarado em manifest e nunca importado no escopo do manifest, com ferramenta executada declarada na politica e comentario em linha descartado do nome.
- `complexity`: complexidade ciclomatica do proprio corpo da funcao acima do teto declarado; funcao aninhada e medida por si e gestao de recurso com `with` nao conta como ramo.

Cada classe declara na politica o que **nao** ve, e a politica declara o escopo de leitura. Tratar o relatorio como completo onde a classe declara limite e erro de leitura, nao de ferramenta.

- `scope.corpus_suffixes` lista os formatos de texto conferidos na busca por citacao: formato fora da lista produz falso positivo em classe `gated`.
- Excecao e declarada, nunca escondida no codigo: `classes.dead-symbol.ignore_names` nomeia o que o proprio interpretador consome, `classes.dead-module.package_init_is_entry` declara o arquivo de pacote como ponto de entrada e `classes.dead-module.exclude_tests` declara o diretorio de teste fora da varredura.
- Definicao repetida do mesmo nome no mesmo arquivo e Python legal: cada uma recebe rotulo proprio com ordem de aparicao.
- A identidade do achado continua derivada de conteudo material, sem numero de linha: mover codigo nao muda achado nem excecao aceita.
- Decisao de escopo e de excecao e declarada na politica: campo ausente nao vira default no codigo, porque isso tiraria da politica o papel de unica fonte de escopo.

## Execucao
1. Conferir a politica e o contrato: `python higienizar-repositorio/scripts/validate_hygiene.py --root .`.
2. Produzir o relatorio: `python higienizar-repositorio/scripts/hygiene_scan.py --root . --report <arquivo.json> --markdown <arquivo.md>`.
3. Produzir os work items: `python higienizar-repositorio/scripts/build_hygiene_work_items.py --root . --report <arquivo.json> --out-dir <diretorio>`.
4. Encaminhar os work items ao controlador de entrega, que abre a issue e define prioridade.

Para restringir a varredura, acrescentar `--paths <caminho> ...` ao passo 2. O modo direcionado restringe o conjunto analisado — arquivos, manifests e achados —, e a busca por citacao continua lendo a arvore inteira: citacao e propriedade da arvore, e restringi-la produziria falso positivo de simbolo morto. O passo 1 e obrigatorio antes de qualquer leitura do relatorio.

## Leitura do relatorio
- `open` em classe `gated` e divida sem decisao: corrigir ou declarar em `accepted`, com justificativa escrita.
- `accepted` e divida conhecida e aceita, com motivo registrado: continua sendo work item. A justificativa precisa ser texto de verdade — extensao minima, palavras e variedade —, porque preenchimento nao e justificativa; o merito e da revisao, a forma e do gate.
- Classe `reported` nao aceita excecao item a item: a divida dela e agregada e a contagem precisa ser exatamente a linha de base declarada, nem acima (divida nova) nem abaixo (linha de base folgada).
- A linha de base de classe `reported` vive numa historia declarada na politica: crescer exige entrada nova com motivo escrito, e reduzir e progresso e nao exige justificativa.
- `excluded` e exclusao declarada com motivo, caminho relativo canonico dentro da raiz e visivel no relatorio: escopo que encolhe sem aparecer no relatorio e indistinguivel de aprovacao, e o gate reprova. `scope.exclude_dirs` cobre a subarvore inteira, e a entrada pode ser caminho composto como `evals/fixtures`.
- A leitura de texto para citacao fica contida na raiz: link que resolve para fora entra em `not_analyzed`, porque texto de fora nao pode apagar achado da arvore medida. O mesmo vale para manifest que resolve para fora.
- Citacao de arquivo e resolvida por caminho — na raiz, no diretorio de quem cita e na raiz da skill —, aceita a ancora de marcador de lugar como `<skill>/scripts/x.py`, ignora caminho que sai da raiz e so aceita nome solto quando ele e unico na arvore: nome ambiguo nao identifica invocacao de nenhum homonimo.
- Caminho absoluto nao e citacao de arquivo da arvore, e marcador de lugar so conta quando esta fechado logo antes do caminho, como `<skill>/scripts/x.py`; um `>` solto nao e ancora.
- Rotulo sem sufixo pertence a definicao que aparece primeiro no texto, contando tambem a que fica abaixo do limiar: numerar so o conjunto medido daria o mesmo rotulo a duas definicoes.
- A varredura reprova politica sem chave de decisao declarada, e nao so o validador: medir com semantica implicita seria evidencia que a propria politica nao sustenta.
- O comando que produz o relatorio confere o contrato antes de gravar: artefato fora do contrato nao vira arquivo, e excecao sem motivo escrito reprova a varredura.
- Percorrer a arvore e trabalho da varredura, e nao de `rglob`: diretorio ilegivel e link para diretorio aparecem como cobertura nao analisada, em vez de sumirem.
- Motivo de cobertura nao carrega caminho absoluto: duas copias identicas da mesma arvore precisam produzir o mesmo relatorio, e caminho de fora da raiz declarado em `not_analyzed_allowed` reprova.
- Supressor declarativo, em `entry_points` e em `ignore_names`, declara nome e motivo escritos: lista de texto solto esconderia nome arbitrario sem auditabilidade.
- O conjunto de manifestos e declarado na politica, em `manifest_patterns`: conjunto fixo no codigo seria escopo escondido, e `pyproject.toml` e lido pelo formato, nao como lista de linhas. Formato sem leitura declarada entra em cobertura nao analisada, estrutura invalida dentro de formato declarado tambem e recusa visivel, e arquivo de trava e reconhecido por convencao de nome em qualquer padrao declarado.
- `python` fica fora da contagem de dependencia nos dois formatos: e versao exigida do interpretador, e nao distribuicao importavel.
- Citacao de nome solto resolve contra o escopo medido, e nao contra a arvore inteira: arquivo excluido nao torna ambigua a citacao de um nome que e unico no escopo.
- A citacao exige que o sufixo declarado termine o nome: sufixo seguido de caractere que continua identificador, inclusive marca combinante, aponta para outro nome e nao mantem arquivo vivo.
- Alvo direcionado que resolve para fora da raiz aparece em cobertura nao analisada, com o mesmo rotulo do percurso livre, em vez de abortar a varredura. Link quebrado e link em ciclo seguem a mesma regra, e alvo externo mantem o escopo vazio: conjunto vazio de alvos nao e ausencia de restricao.
- O rotulo de caminho de fora da raiz e apenas o nome do arquivo: caminho absoluto no relatorio quebraria a comparacao entre copias equivalentes da arvore.
- O indice de citacao e o do escopo medido, e a autocitacao nao conta: nem arquivo excluido, nem link de corpus que sai da raiz, nem o proprio texto do arquivo mantem modulo vivo.
- Estrutura invalida em formato declarado, como escalar em `project.optional-dependencies`, e recusa visivel, e nao uma dependencia por caractere.
- O gerador de work items tambem recusa escrever dentro da arvore medida: artefato gravado no objeto medido pode apagar a divida que ele mesmo descreve.
- Relatorio com problema de politica nao e publicado: a reprovacao acontece antes da gravacao, e nao depois de o arquivo existir.
- O rotulo de caminho de fora da raiz e apenas o nome do arquivo: caminho absoluto no relatorio quebraria a comparacao entre copias equivalentes da arvore.
- O indice de citacao e o do escopo medido, e a autocitacao nao conta: nem arquivo excluido, nem link de corpus que sai da raiz, nem o proprio texto do arquivo mantem modulo vivo.
- Estrutura invalida em formato declarado, como escalar em `project.optional-dependencies`, e recusa visivel, e nao uma dependencia por caractere.
- O gerador de work items tambem recusa escrever dentro da arvore medida: artefato gravado no objeto medido pode apagar a divida que ele mesmo descreve.
- Relatorio com problema de politica nao e publicado: a reprovacao acontece antes da gravacao, e nao depois de o arquivo existir.
- `exclude_dirs` exige diretorio relativo canonico dentro da raiz, sem `.`, `..`, barra duplicada nem barra final: forma nao canonica exclui outro diretorio, e `.` esvaziaria o escopo por declaracao.
- Chave de decisao so vale na classe a que pertence, e chave com nome parecido e erro: decisao de outra classe, ou nome que parece decisao, mentiria sem que ninguem percebesse.
- Supressor declarado com tipo errado reprova, em vez de ser ignorado: texto ou objeto no lugar da lista parece silenciar achado e nao silencia nada.
- Citacao com `..` e recusada somente quando de fato sai da raiz: `sub/../x.py` cita `x.py` dentro da arvore, e descartar por conter `..` acusaria divida que nao existe.
- Estrutura invalida de TOML e recusa visivel: `project`, `tool` ou `tool.poetry` escalar, hierarquia de grupo do Poetry invalida e chave nao lida dentro de grupo apontam para declaracao que a medicao nao le, e declaracao que desaparece da medicao e divida escondida.
- Import relativo na raiz so alcanca irmao quando a propria raiz e pacote declarado, e import relativo alem do pacote nao alcanca modulo nenhum.
- O gerador de work items reprova politica que o gate reprova, varredura com problema e relatorio que nao corresponde a arvore e a politica atuais, antes de publicar: artefato gerado de politica invalida, ou de relatorio de outra arvore, e evidencia que ninguem pode aceitar.
- Decisao declarada como booleana so aceita booleano, versao de politica exige o inteiro exato, e linha de base nao entra em classe controlada nem pela historia: politica malformada nao pode esconder achado nem servir de linha de base.
- Varredura e gerador recusam dois artefatos no mesmo caminho, mesmo quando escritos de forma diferente, e saida reutilizada: JSON sobrescrito por Markdown, ou work item de execucao anterior, nao podem circular como evidencia atual.
- Destino com mais de um link e recusado, porque escrita por link alcancaria a arvore medida sem sair dela, e relatorio com contagem decimal e recusado, porque o esquema aceita `1.0` como inteiro.
- Toda classe declarada como medida exige linha de base declarada, e nao apenas a de complexidade: medir contra alvo nao declarado nao e medicao.
- Caminho declarado precisa ser texto simples: NUL e quebra de linha nao sao caminho, e politica invalida reprova em vez de derrubar o validador.
- O relatorio Markdown publica o escopo excluido, e nao so o JSON: artefato humano sem a exclusao induziria leitura de cobertura completa sobre escopo reduzido por declaracao.
- A validacao nao deixa bytecode na arvore analisada: `__pycache__` de modulo importado e escrita dentro da raiz que a execucao afirma nao alterar.
- O relatorio nao pode ser gravado dentro da arvore medida: evidencia gravada no objeto medido entra no corpus de citacao, muda a medicao seguinte e pode sobrescrever arquivo coberto.
- O comando da varredura reprova politica que o gate reprova, antes de medir: medir com politica invalida publicaria evidencia que ninguem pode aceitar.
- O modo direcionado usa a raiz do repositorio para rotular cobertura, e nao o alvo: dois alvos com o mesmo diretorio recusado ficariam indistinguiveis, e alvo inexistente publica caminho relativo canonico.
- Identificador e caminho citado seguem a gramatica de Python, e nao classe de caractere: marca combinante e simbolo fora do plano basico contam como nome, e o arquivo nao e acusado de morto com a citacao no texto.
- `not_analyzed` e buraco de cobertura, nunca limpeza: arquivo ilegivel, diretorio ilegivel, link quebrado, link de diretorio, manifest ilegivel, alvo direcionado que nao existe, caminho que resolve para fora da raiz ou erro de sintaxe precisa ser corrigido ou declarado na politica. Permissao declarada sem arquivo correspondente tambem reprova.

## Contratos
- `schemas/hygiene-report.schema.json`: contrato do relatorio da varredura, incluindo escopo varrido e exclusoes declaradas.
- `schemas/hygiene-work-item.schema.json`: contrato do work item na forma canonica.
- `schemas/subskill-result.schema.json`: contrato de resultado de subskill compartilhado com o catalogo.

## Referencias
Ler `references/global-hygiene-profile.md` para metodo, limites de precisao por classe, forma de tratar cada achado e o que fazer quando a varredura acusa a propria entrega.
