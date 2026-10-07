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

Cada classe declara na politica o que **nao** ve, e a politica declara o escopo de leitura: `scope.corpus_suffixes` lista os formatos de texto conferidos na busca por citacao, porque formato fora da lista produz falso positivo em classe `gated`. Tratar o relatorio como completo onde a classe declara limite e erro de leitura, nao de ferramenta.

## Execucao
1. Conferir a politica e o contrato: `python higienizar-repositorio/scripts/validate_hygiene.py --root .`.
2. Produzir o relatorio: `python higienizar-repositorio/scripts/hygiene_scan.py --root . --report <arquivo.json> --markdown <arquivo.md>`.
3. Produzir os work items: `python higienizar-repositorio/scripts/build_hygiene_work_items.py --root . --report <arquivo.json> --out-dir <diretorio>`.
4. Encaminhar os work items ao controlador de entrega, que abre a issue e define prioridade.

Para restringir a varredura, acrescentar `--paths <caminho> ...` ao passo 2. O passo 1 e obrigatorio antes de qualquer leitura do relatorio.

## Leitura do relatorio
- `open` em classe `gated` e divida sem decisao: corrigir ou declarar em `accepted`, com justificativa escrita.
- `accepted` e divida conhecida e aceita, com motivo registrado: continua sendo work item. A justificativa precisa ser texto de verdade — extensao minima, palavras e variedade —, porque preenchimento nao e justificativa; o merito e da revisao, a forma e do gate.
- Classe `reported` nao aceita excecao item a item: a divida dela e agregada e a contagem precisa ser exatamente a linha de base declarada, nem acima (divida nova) nem abaixo (linha de base folgada).
- A linha de base de classe `reported` vive numa historia declarada na politica: crescer exige entrada nova com motivo escrito, e reduzir e progresso e nao exige justificativa.
- `excluded` e exclusao declarada com motivo, caminho relativo dentro da raiz e visivel no relatorio: escopo que encolhe sem aparecer no relatorio e indistinguivel de aprovacao, e o gate reprova.
- `not_analyzed` e buraco de cobertura, nunca limpeza: arquivo ilegivel, link quebrado, caminho que resolve para fora da raiz ou erro de sintaxe precisa ser corrigido ou declarado na politica. Permissao declarada sem arquivo correspondente tambem reprova.

## Contratos
- `schemas/hygiene-report.schema.json`: contrato do relatorio da varredura, incluindo escopo varrido e exclusoes declaradas.
- `schemas/hygiene-work-item.schema.json`: contrato do work item na forma canonica.
- `schemas/subskill-result.schema.json`: contrato de resultado de subskill compartilhado com o catalogo.

## Referencias
Ler `references/global-hygiene-profile.md` para metodo, limites de precisao por classe, forma de tratar cada achado e o que fazer quando a varredura acusa a propria entrega.