# Padrões de distribuição por tipo de tela

Escolher o padrão pela tarefa dominante. Misturar padrões apenas quando houver justificativa funcional.

## Quando ler este arquivo

Consultar apenas a superfície e o padrão ligados à tarefa atual, antes de mudanças materiais de composição.

## Índice

- [Antes de uma mudança material](#antes-de-uma-mudança-material)
- [Tela analítica ou dashboard](#tela-analítica-ou-dashboard)
- [Representação dos dados](#representação-dos-dados)
- [Casos verificáveis](#casos-verificáveis)
- [Tela de lista, inbox ou registros](#tela-de-lista-inbox-ou-registros)
- [Formulário de criação ou edição](#formulário-de-criação-ou-edição)
- [Tela de escrita, editor ou conteúdo](#tela-de-escrita-editor-ou-conteúdo)
- [Tela de detalhe](#tela-de-detalhe)
- [Configurações](#configurações)
- [Fluxo ou wizard](#fluxo-ou-wizard)
- [Escolha entre modal, drawer e página](#escolha-entre-modal-drawer-e-página)
- [Ordenação lógica universal](#ordenação-lógica-universal)

## Antes de uma mudança material

Após resolver a precedência em [padrões de interface](interface-standards.md), registre no plano existente a tarefa e a superfície, a hierarquia, a ação primária, a densidade e como layout e ações se reorganizam em telas estreitas. Escolha os [estados pelo papel](interface-standards.md#estados-por-papel-e-risco), sem exigir plano ou artefato separado para um ajuste trivial.

| Superfície | Prioridade da composição | Não transportar por padrão |
| --- | --- | --- |
| Página pública | Explicar a proposta e facilitar a próxima ação do visitante. Usar destaque inicial só quando ajudar a tarefa. | Fórmulas fixas de seções, chamadas ou imagens. |
| Tela operacional | Tornar dados, filtros e ações de trabalho rápidos de localizar e comparar. Em largura estreita, manter informação e ação essenciais. | Hero, ritmo de campanha ou animações de entrada. |
| Componente isolado | Manter o contexto e o layout ao redor. Definir o papel, a ação e os estados aplicáveis no componente existente. | Estrutura de página, menu ou variante sem necessidade funcional. |

## Tela analítica ou dashboard

Ordenar normalmente:

1. título, período e contexto;
2. filtros globais essenciais;
3. indicadores principais, em quantidade limitada;
4. tendência, comparação ou composição;
5. exceções, alertas e itens que exigem decisão;
6. detalhamento tabular ou lista;
7. ações secundárias, exportação e metodologia.

Regras:

- não transformar toda medida em card;
- priorizar indicadores que mudem decisão;
- manter filtros próximos do conteúdo que afetam;
- usar gráficos somente quando facilitarem comparação, tendência ou distribuição;
- não repetir o mesmo dado em card, gráfico e tabela sem função distinta;
- apresentar unidades, período, fonte e estado de atualização;
- para regiões que dependem de dados, aplicar os [estados de dados](interface-standards.md#estados-por-papel-e-risco).

### Representação dos dados

Começar pela pergunta. Usar a representação mais direta, inclusive tabela ou texto se o gráfico não ajudar. Exibir valores provenientes da fonte; identificar explicitamente valores sintéticos como teste ou exemplo. Se faltarem dados, mostrar a ausência, nunca preencher com zeros ou tendências inventadas.

Usar eixos, domínios e intervalos coerentes com a comparação. Em barras, iniciar o eixo de magnitude em zero; em outras escalas, tornar o intervalo explícito e rejeitar cortes ou proporções que distorçam a leitura. Manter rótulos e unidades legíveis em larguras estreitas e fornecer alternativa acessível com os valores relevantes, por exemplo uma tabela ou descrição equivalente.

## Casos verificáveis

Os casos abaixo documentam decisões de contrato; não substituem a verificação de uma interface executável.

| ID | Contexto | Aceitar | Rejeitar |
| --- | --- | --- | --- |
| PUBLICA | Página pública | explicar-proposta-e-proxima-acao | impor-secoes-ou-hero |
| OPERACIONAL | Dashboard de trabalho | priorizar-dados-filtros-e-acoes | importar-hero-de-marketing |
| COMPONENTE | Controle isolado | manter-contexto-e-variantes-locais | redesenhar-estrutura-da-pagina |
| CONTROLE | Controle síncrono simples | documentar-estados-assincronos-inaplicaveis | exigir-todos-os-oito-estados |
| ENVIO | Submissão assíncrona | cobrir-progresso-erro-e-resultado-confirmado | omitir-erro-ou-celebrar-sem-confirmacao |
| DADOS | Região consulta e renderiza dados | distinguir-carregamento-vazio-erro-e-preenchido | apresentar-erro-como-vazio |
| GRAFICO | Valores verificados ou exemplos identificados | representar-valores-unidades-e-periodo-fieis | fabricar-valores-ou-tendencia |
| SEM-DADOS | Série indisponível | explicitar-ausencia | converter-ausencia-em-zero |
| ESCALA | Barras comparáveis | preservar-proporcao-a-partir-de-zero | cortar-eixo-e-exagerar-diferenca |
| INTERACAO | Teclado em carregamento e movimento reduzido | preservar-foco-contraste-espaco-e-acao | perder-foco-ou-deslocar-controle |

## Exemplo de gráfico com dados fornecidos

Fixture sintética, apenas para teste. Pergunta: quantos pedidos foram concluídos em cada semana? Fonte da fixture: semana 1 = 40 e semana 2 = 60, em pedidos/semana. O gráfico e sua alternativa acessível devem apresentar os mesmos valores e períodos; se a fonte estiver indisponível, não há valores para representar.

| Caso | Valores da fonte | Valores mostrados | Eixo das barras | Decisão |
| --- | --- | --- | --- | --- |
| FIEL | 40, 60 | 40, 60 | 0–80 | representar |
| AUSENTE | — | — | — | informar-ausencia |
| DISTORCIDO | 40, 60 | 40, 60 | 35–80 | rejeitar |

No eixo fiel, as alturas são proporcionais a 40 e 60. Com início em 35, viram 5 e 25: a segunda barra aparenta ser cinco vezes maior, embora a contagem seja apenas uma vez e meia a primeira.

## Tela de lista, inbox ou registros

Ordenar normalmente:

1. título, contagem ou contexto;
2. ação principal;
3. busca, filtros e ordenação;
4. lista ou tabela;
5. paginação ou carregamento progressivo;
6. ações de linha e seleção em massa;
7. estado vazio orientado à próxima ação.

Regras:

- manter linhas compactas e escaneáveis;
- priorizar data, identificação, status, valor e ação conforme o domínio;
- permitir ordenar campos temporais relevantes;
- não usar cards grandes para registros repetitivos quando lista resolve melhor;
- manter filtros ativos visíveis e fáceis de limpar.

## Formulário de criação ou edição

Ordenar normalmente:

1. título e contexto mínimo;
2. identificação essencial;
3. dados principais por domínio;
4. opções e detalhes secundários;
5. revisão ou consequências importantes;
6. ações de salvar e cancelar.

Regras:

- agrupar por significado;
- apresentar dependências antes dos campos que elas alteram;
- ocultar opções avançadas somente quando forem realmente secundárias;
- usar etapas quando o volume ou a dependência tornar uma página única difícil de compreender;
- não usar duas colunas em campos longos ou com erro multilinha.

## Tela de escrita, editor ou conteúdo

Ordenar normalmente:

1. título/documento e status;
2. ações principais de salvar, publicar ou enviar;
3. área de escrita dominante;
4. metadados essenciais;
5. opções de revisão, histórico ou colaboração;
6. configurações avançadas em painel secundário.

Regras:

- dar espaço visual à tarefa de escrita;
- evitar painéis laterais competindo com o conteúdo;
- manter estado de salvamento visível sem interromper;
- preservar foco, atalhos e recuperação de conteúdo;
- separar edição do conteúdo de configurações editoriais.

## Tela de detalhe

Ordenar normalmente:

1. identificação e status;
2. ações do registro;
3. resumo dos dados mais relevantes;
4. seções por domínio ou linha do tempo;
5. relacionamentos e anexos;
6. histórico, auditoria e ações destrutivas.

Regras:

- evitar uma grade uniforme de cards para todos os campos;
- destacar dados que orientem decisão;
- usar definition list, tabela ou pares label/valor conforme a natureza do dado;
- manter ações destrutivas no final ou em menu separado.

## Configurações

Ordenar normalmente:

1. navegação por categoria;
2. título e consequência da configuração;
3. controles relacionados;
4. ajuda contextual apenas onde houver ambiguidade;
5. salvar, aplicar ou feedback de persistência;
6. zona de risco separada.

Regras:

- evitar uma página longa sem agrupamento;
- não misturar preferências pessoais, integrações e segurança na mesma seção;
- indicar quando a alteração é imediata, global ou irreversível.

## Fluxo ou wizard

Ordenar normalmente:

1. progresso e nome da etapa;
2. objetivo da etapa;
3. campos ou decisões atuais;
4. validação e ajuda contextual;
5. voltar e avançar;
6. revisão final antes da confirmação.

Regras:

- usar wizard somente quando houver sequência ou dependência real;
- preservar dados ao voltar;
- permitir compreender o que falta;
- não dividir um formulário simples em etapas artificiais.

## Escolha entre modal, drawer e página

- **Modal**: ação curta, foco único, baixa quantidade de dados.
- **Drawer**: inspeção ou edição contextual mantendo referência à lista.
- **Página**: tarefa longa, múltiplas seções, URL própria, navegação ou risco elevado.

## Ordenação lógica universal

Quando nenhum padrão se encaixar, ordenar por:

1. orientação: onde estou e sobre o quê;
2. contexto: período, status, entidade e restrições;
3. decisão: o que preciso entender;
4. ação: o que posso fazer agora;
5. detalhe: evidências e dados complementares;
6. exceção: erros, riscos e itens raros;
7. histórico: rastreabilidade e ações destrutivas.
