# Colheita completa de blockers em uma unica auditoria

## Objetivo

Reduzir ciclos em que cada auditoria independente devolve apenas um defeito material novo.

## Matriz de saturacao antes de publicar o parecer

Derivar do contrato atomizado, diff, caminhos reais de execucao e rejeicoes anteriores
uma lista de `requisito -> familia -> superficie -> dimensoes de ataque`.
Para cada superficie material, confrontar a implementacao errada plausivel com
um controle positivo, um negativo discriminante e um caso irmao quando houver
alternativa relevante. Nao escolher a quantidade de achados como meta ou criterio
de encerramento. A matriz e uma ferramenta de cobertura, nao prova automatica
de completude.

Para detectores AST, parsers e gates arquiteturais, expandir a classe do primeiro
escape pelo fluxo `origem -> binding/escopo -> transformacao -> consumidor -> efeito`:
variar import, leitura e carregamento; `const`/`let`, alias, shadowing e reatribuicao;
projecao de valor versus registro, chamada transparente versus opaca;
fluxo direto, condicional e ramos exaustivos; consumo por operadores/iteradores;
codigo produtivo, fixture importada, teste isolado e dado administrativo.
Selecionar combinacoes por pares de eixos e casos de fronteira de maior risco
em vez de produto cartesiano irrestrito; justificar eixos nao aplicaveis.
Aplicar a tecnica a outros dominios por semantica, nunca por nomes de alimentos.

## Condicao de encerramento da colheita barata

Antes de publicar o parecer completo, registrar para **cada** superficie material:
`covered` (controle e resultado observados no SHA auditado),
`not-applicable` (justificativa ligada ao contrato) ou
`not-executed` (motivo, impacto e risco residual). Usar uma linha por familia
e superficie com dimensoes, comando/procedimento, esperado, observado, evidencia
e limitacoes. Duas falhas iniciais nao encerram a busca enquanto existirem
superficies materiais sem classificacao; nao impor teto de findings.
Agrupar variantes sob o mesmo finding de causa raiz e reportar separadamente
causas independentes. Distinguir **reprovada com colheita abrangente** de
**reprovada com cobertura limitada**; nao alegar exaustividade se restar lacuna.

Respeitar `reaudit-readiness.md`: se o mesmo gate deterministico anterior
continua vermelho ou o replay obrigatorio falta, encerrar no preflight rapido,
sem simular uma nova descoberta ampla. Apos preflight pronto, varrer o
restante de forma proporcional. Em `blocker-bounded`, cancelar provas caras
nao relacionadas, nunca a varredura estatica barata. Nao atribuir limitacao
do ambiente da auditoria ao candidato.

## Regra apos primeiro blocker

Quando o primeiro blocker torna o candidato nao aprovavel:

1. interromper apenas provas caras nao relacionadas;
2. continuar a varredura estatica e controles baratos por **todos os requisitos atomicos ainda nao fechados**, nao somente casos irmaos da causa ja encontrada;
3. revisar todas as familias de risco materiais da issue que ainda nao receberam ataque independente;
4. agrupar findings por causa raiz, mas nao omitir blockers independentes apenas porque pertencem a outra familia;
5. devolver no mesmo relatorio o conjunto coeso de blockers baratos observaveis.

## Checklist de saturacao independente

Depois do primeiro blocker, revisar pelo menos:

- autorizacao/entitlement;
- tenant e ownership;
- fronteira publica e nao enumeracao;
- `reference-liveness`: liveness de referencias entre etapas;
- `temporal-destination`: passado/atual/futuro e coerencia de periodo/destino;
- concorrencia, idempotencia e rollback;
- historico/imutabilidade/nova revisao;
- contrato estrutural/caminho canonico;
- documentacao contraditoria.

Marcar familia `not-applicable` apenas com justificativa baseada no contrato. O objetivo nao e executar toda suite, e sim evitar que um blocker barato de outra familia estreie apenas na proxima auditoria.
