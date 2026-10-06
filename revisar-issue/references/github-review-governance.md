# Governanca de revisao GitHub standalone

## Quando ler este arquivo

Ler quando a revisão for standalone no GitHub, incluindo revisão em lote e escritas no repositório.

## Índice

- [1. Escopo da revisao](#1-escopo-da-revisao)
- [2. Fonte canonica e documentacao](#2-fonte-canonica-e-documentacao)
- [3. Revisao em lote](#3-revisao-em-lote)
- [4. Escritas no GitHub](#4-escritas-no-github)
- [5. Checklist de qualidade](#5-checklist-de-qualidade)
- [6. Limites](#6-limites)

## 1. Escopo da revisao

Transformar a issue em contrato implementavel para agentes de codigo, preservando intencao e incerteza real. Avaliar objetivo, contexto, escopo e fora de escopo, requisitos, dependencias, premissas, cenarios, falhas, fallback, criterios de aceite, testes e impacto documental.

Ler titulo, corpo e comentarios relevantes. Consultar documentacao versionada materialmente relacionada, priorizando README, `docs/`, ADRs, arquitetura, contratos/API/schema, runbooks, guias de contribuicao, documentacao de dominio e arquivos diretamente afetados.

Nao substituir regra de produto por detalhe de implementacao. Nao adicionar boas praticas genericas que nao sejam necessarias para implementabilidade ou verificacao.

## 2. Fonte canonica e documentacao

### Quando reconciliar documentacao

Reconciliar quando a revisao revelar pelo menos um destes casos:

- regra duravel de produto ou dominio que futuras entregas precisarao reutilizar;
- mudanca de contrato de API, ownership de dados, fronteira arquitetural, procedimento operacional, setup ou convencao de repositorio;
- contradicao entre issue e documentacao com evidencia suficiente para determinar a regra correta;
- mesma regra definida em varios documentos com semantica materialmente diferente;
- issue prestes a virar segunda fonte permanente de verdade para comportamento ja pertencente a documentacao versionada;
- ambiguidade documental que faria implementadores escolherem solucoes centrais diferentes.

Nao atualizar documentacao apenas por estilo, detalhe transitorio, debugging pontual ou requisito estritamente local a uma unica entrega.

### Escolha da fonte canonica

Respeitar primeiro qualquer ownership explicitamente definida pelo repositorio. Na ausencia dela, usar como heuristica:

- arquitetura e ownership de dados -> arquitetura, ADR ou documentacao de dominio;
- contratos de API -> API, schema ou contrato;
- comportamento duravel visivel ao usuario -> produto ou dominio;
- deploy e operacao -> runbook ou operacoes;
- setup e uso do repositorio -> README, CONTRIBUTING ou setup;
- escopo, aceite, rollout e verificacao de uma entrega -> issue.

Preferir fonte existente. Nao criar outro documento apenas para resolver duplicidade.

### Evitar dupla definicao

1. Manter a definicao completa da regra duravel na fonte canonica.
2. Na issue, manter delta de entrega, restricoes e criterios necessarios para implementacao.
3. Referenciar caminho exato e, quando util, secao da fonte canonica.
4. Substituir definicoes secundarias conflitantes por referencia quando isso for seguro.
5. Nao duplicar blocos grandes de regra entre issue e docs sem convencao explicita do repositorio.

### Quando adiar

Nao escolher precedencia quando produto, comportamento real e documentacao nao fornecerem evidencia suficiente. Registrar pergunta aberta e listar os caminhos documentais afetados quando:

- intencao de produto estiver realmente indefinida;
- comportamento observado e documentacao divergirem sem fonte decisiva;
- a issue propuser nova direcao arquitetural ainda nao aprovada;
- atualizar docs declararia prematuramente comportamento ainda em decisao.

## 3. Revisao em lote

- Trabalhar issue por issue e manter rastreabilidade individual.
- Usar formato consistente sem forcar secoes vazias.
- Normalizar terminologia e referencias canonicas apenas depois das revisoes individuais.
- Priorizar issues com maior risco de ambiguidade e retrabalho.
- Nao reescrever issue pronta apenas por estilo.
- Identificar padroes repetidos de drift ou ambiguidade.
- Quando varias issues exigirem a mesma correcao documental, preferir mudanca coerente em uma unica branch/PR quando compativel com o fluxo do repositorio.

## 4. Escritas no GitHub

Efetuar escrita somente quando o usuario autorizou e existe melhoria material.

### Issue

- Preservar IDs, links, restricoes e intencao original.
- Atualizar somente depois de ler contexto suficiente do repositorio.
- Em `review-only` ou `draft-only`, nao escrever; retornar proposta.
- Aplicar label `epic` apenas quando a issue for claramente epic e o label existir ou for suportado pelo repositorio.
- Nao fechar issue, fazer merge ou executar alteracao nao relacionada.

### Documentacao

Quando reconciliacao for necessaria e autorizada:

1. Ler o arquivo-alvo a partir da base de revisao vigente.
2. Preservar convencoes e terminologia existentes.
3. Fazer a menor mudanca que restabeleca uma definicao canonica clara.
4. Nao editar codigo-fonte como parte da revisao.
5. Reutilizar branch adequada quando existir; caso contrario, seguir convencao do repositorio para branch de documentacao/revisao.
6. Criar commit objetivo e abrir/atualizar PR quando esse for o fluxo normal.
7. Nunca fazer merge sem autorizacao explicita.
8. Atualizar a issue com referencia para a fonte canonica e PR/commit documental quando isso melhorar rastreabilidade.

## 5. Checklist de qualidade

Antes de finalizar, confirmar:

- objetivo explicito e resultado esperado;
- escopo delimitado;
- requisitos concretos, nao redundantes e observaveis;
- edge cases, erros e fallback cobertos quando relevantes;
- criterios de aceite verificaveis;
- premissas e perguntas abertas separadas de requisitos;
- dois implementadores provavelmente tomariam as mesmas decisoes centrais;
- regras duraveis possuem uma fonte canonica clara quando possivel;
- issue nao contradiz materialmente as referencias canonicas;
- drift documental foi reconciliado ou explicitamente marcado;
- mudanca documental nao alterou silenciosamente intencao de produto;
- nenhum codigo-fonte foi implementado como efeito colateral da revisao.

## 6. Limites

Nao mudar intencao de produto. Nao introduzir requisitos grandes apenas para completar a especificacao. Nao remover restricoes silenciosamente. Nao fabricar arquitetura, API, modelo de dados, regra de negocio ou fonte canonica. Nao resolver ambiguidade criando outra definicao duplicada. Quando a evidencia for insuficiente, melhorar o que for sustentado e manter a decisao faltante visivel.
