# Padrões de interface

Usar primeiro os padrões do repositório. Aplicar estes defaults apenas quando o projeto não fornecer uma regra mais específica.

## Quando ler este arquivo

Consultar quando o recorte de UI exigir decidir a fonte visual, a precedencia, os componentes ou os defaults pertinentes. Carregar somente as secoes necessarias a etapa, sem refazer descoberta global.

## Índice

- [Descoberta e precedencia por solucao](#descoberta-e-precedencia-por-solucao)
- [Hierarquia](#hierarquia)
- [Grid e largura](#grid-e-largura)
- [Espaçamento e densidade](#espaçamento-e-densidade)
- [Tipografia](#tipografia)
- [Cards e contêineres](#cards-e-contêineres)
- [Formulários](#formulários)
- [Modais e drawers](#modais-e-drawers)
- [Tabelas e listas](#tabelas-e-listas)
- [Golden Screens e controles de escolha](#golden-screens-e-controles-de-escolha)
- [Botões e ícones](#botões-e-ícones)
- [Cores e estados semânticos](#cores-e-estados-semânticos)
- [Responsividade](#responsividade)
- [Acessibilidade](#acessibilidade)

## Descoberta e precedencia por solucao

No recorte atribuido, localizar fontes da **propria solucao**, sem varrer novamente todo o repositorio: documentacao canonica de UI/UX, Golden Screen oficialmente aprovada, biblioteca de componentes, tokens/CSS executaveis e telas correlatas. Conferir caminhos e estados reais; nome de arquivo, aparencia similar ou memoria de outro projeto nao comprovam aprovacao.

Aplicar nesta ordem, somente onde a fonte tratar o componente ou estado em questao:

1. **Padroes locais aprovados**: design system, Golden Screen e convencoes visuais oficialmente adotadas e versionadas pelo projeto.
2. **Componentes locais executaveis**: variantes, tokens, CSS e estados da propria aplicacao, para detalhes nao cobertos por fonte aprovada.
3. **Telas correlatas da mesma solucao**: padroes existentes e observaveis quando nao houver regra mais especifica.
4. **Defaults genericos desta skill**: aplicar apenas ao que permanecer sem padrao local identificavel.

- Requisitos e criterios da issue delimitam a mudanca, mas nao substituem silenciosamente fontes canonicas. Em conflito entre documentacao aprovada, implementacao real ou requisito, identificar as fontes e a divergencia antes de decidir; nao presumir que uma mudanca acidental de CSS revogou o padrao.
- Quando nao houver documento formal, mas houver componentes locais, reutilizar seu comportamento e registrar que a referencia e **implementada**, nao oficialmente aprovada.
- Na ausencia de fonte local verificavel, declarar **sem padrao local identificado** e usar os defaults pertinentes desta skill; nao criar design system ficticio nem copiar referencias de outra aplicacao.
- Documentar no resultado as fontes consultadas, a precedencia aplicada, os defaults, as lacunas e os conflitos relevantes, sem criar inventario global ou artefato novo por padrao.
- Convencoes de produto, rotas, seletores, tokens e referencias visuais particulares pertencem exclusivamente ao repositorio consumidor. Esta Skill define somente o processo geral de descoberta e verificacao. Acessibilidade e seguranca nao podem ser reduzidas por convencao visual local.

## Hierarquia

- Manter um único título principal por página.
- Posicionar contexto essencial próximo ao título, sem parágrafos introdutórios longos.
- Destacar uma ação principal por contexto; reduzir contraste e peso das demais.
- Ordenar conteúdo de visão geral para detalhe e de decisão para execução.
- Usar cor como reforço, nunca como único indicador.
- Evitar títulos, bordas e fundos repetidos quando espaçamento e tipografia já separam os grupos.

## Grid e largura

- Usar a escala e os breakpoints existentes.
- Na ausência de padrão, adotar grid baseado em múltiplos de 4 ou 8 px.
- Limitar conteúdo amplo a aproximadamente 1200–1440 px e centralizar quando a aplicação não usar layout fluido.
- Limitar formulários comuns a aproximadamente 640–840 px.
- Usar largura menor para campos curtos, como CEP, código, data, quantidade e sigla.
- Não usar largura total em botões desktop sem necessidade; no mobile, permitir largura total quando facilitar toque e leitura.
- Manter área clicável de aproximadamente 44×44 px para controles importantes quando o design system não definir outra medida acessível.

## Espaçamento e densidade

- Usar a escala existente de spacing.
- Como default: 24–32 px entre seções, 16–24 px entre grupos e 8–12 px entre label, campo e apoio.
- Reduzir margens laterais para aproximadamente 16 px no mobile.
- Usar linhas de tabela ou lista com densidade suficiente para comparação; evitar alturas exageradas sem conteúdo multilinha.
- Não confundir “clean” com excesso de vazio.

## Tipografia

- Reutilizar família, pesos e escala do produto.
- Reservar maior contraste e peso para título, valor ou decisão principal.
- Manter labels persistentes em formulários; placeholder não substitui label.
- Evitar textos explicativos quando label, agrupamento ou exemplo curto resolverem.
- Manter números comparáveis alinhados e formatados de forma consistente.

## Cards e contêineres

Usar card somente quando pelo menos uma condição for verdadeira:

- o conteúdo forma uma unidade independente;
- existe ação própria do bloco;
- é necessário separar contexto, status ou interação;
- o card participa de uma coleção comparável.

Não colocar cada campo, métrica ou parágrafo em um card. Preferir seções, listas, divisores discretos e alinhamento.

## Formulários

- Ordenar campos conforme o raciocínio do usuário, não conforme o modelo de dados.
- Manter campos relacionados próximos.
- Usar uma coluna para formulários longos e leitura sequencial.
- Usar duas colunas apenas para campos curtos, relacionados e que permaneçam legíveis em telas menores.
- Exibir obrigatoriedade, ajuda e erro próximos ao campo.
- Preservar dados após erro sempre que seguro.
- Posicionar ação principal ao final do fluxo e manter ação de cancelar com menor destaque.

## Modais e drawers

- Usar modal ou drawer para CRUD curto, decisão pontual ou contexto que não mereça navegação própria.
- Usar página para formulários longos, múltiplas seções, dependências complexas ou necessidade de URL compartilhável.
- Como default, usar aproximadamente 480–720 px para modais comuns e limitar a altura a 90vh com scroll interno deliberado.
- Manter título, conteúdo e ações visíveis e bem separados.
- Impedir modal cortado em 1366×768 e mobile.
- Restaurar foco ao fechar e permitir Escape quando não houver risco de perda silenciosa.

## Tabelas e listas

- Usar tabela quando comparação por coluna for importante.
- Usar lista quando cada item tiver conteúdo heterogêneo, descrição ou ações contextuais.
- Fixar ou tornar acessíveis cabeçalho e ações quando listas extensas exigirem.
- Alinhar números à direita e textos à esquerda, salvo padrão local diferente.
- Manter ação de linha em menu quando houver muitas ações secundárias.
- Evitar truncar dado essencial sem tooltip, expansão ou acesso ao detalhe.
- No mobile, priorizar colunas essenciais, cartões de linha ou scroll horizontal deliberado; não esmagar todas as colunas.

## Golden Screens e controles de escolha

- Antes de alterar controles, identificar a referencia visual aprovada do projeto, quando existir, e reutilizar variantes, estados e tokens executaveis da propria solucao. Na ausencia de referencia formal, priorizar componentes locais verificaveis.
- Distinguir visualmente alternativa disponivel, item selecionado e acao de confirmacao conforme o design system do projeto. Nao indicar selecao inexistente nem impor uma variante proprietaria de outro produto.
- Conferir a cascata CSS global e local e os estilos computados de fundo, texto e borda em **repouso, hover, focus-visible, active e disabled**; nao confiar apenas na presenca de classes ou propriedades estaticas.
- Quando existirem variantes e tokens locais para controles de escolha, reutilizar seus estados e verificar a precedencia dos seletores no CSS executado, sem introduzir convencoes proprias de outro produto.
- Bloquear o aceite quando um estado material tiver contraste insuficiente ou divergir injustificadamente de referencia local aprovada, quando houver. Validar o estado real no navegador com ponteiro e teclado; conferir o HEAD exato, desktop e mobile e registrar evidencia.

## Botões e ícones

- Reutilizar biblioteca de ícones do projeto.
- Usar ícone com texto para ações não universais.
- Usar apenas ícone em ações convencionais, com nome acessível e tooltip quando necessário.
- Manter o mesmo ícone para a mesma ação em todo o produto.
- Não decorar todos os títulos e labels com ícones.
- Separar ação destrutiva e exigir confirmação proporcional ao risco.

## Cores e estados semânticos

- Usar tokens existentes.
- Reservar cor primária para ação e destaque principal.
- Usar semântica consistente para sucesso, alerta, erro e informação.
- Não usar apenas vermelho/verde para transmitir estado.
- Evitar fundos coloridos extensos quando badge, ícone e texto resolvem.

## Responsividade

Validar ao menos:

- desktop amplo, como 1440×900;
- desktop de baixa altura, como 1366×768;
- mobile, como 390×844 ou breakpoint equivalente;
- tablet quando o layout mudar entre desktop e mobile.

Garantir:

- nenhuma ação essencial fora da viewport sem caminho claro;
- ausência de scroll horizontal acidental;
- filtros e ações reorganizados por prioridade;
- texto sem sobreposição;
- modais e menus dentro da área visível;
- toque confortável e foco visível.

## Acessibilidade

- Usar HTML semântico e componentes acessíveis do projeto.
- Associar label e campo.
- Manter ordem de foco coerente.
- Exibir foco visível.
- Fornecer nome acessível a ícones e controles.
- Não depender apenas de cor, posição ou hover.
- Verificar contraste conforme WCAG aplicável ao projeto.
- Permitir zoom e reflow sem perda material de conteúdo.
