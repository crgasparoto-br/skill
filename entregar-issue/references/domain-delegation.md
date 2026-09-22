# Delegacao de especialidades

## Regra geral

Delegar somente quando a especialidade possui trabalho material que nao cabe em checklist interno. Cada delegacao recebe requisito, caminhos, identidade, write ownership e fingerprint. Nenhuma especialidade possui ciclo, plano global, freeze, publicacao ou decisao final.

## Design de interface

Acionar para mudanca percebida ou operada pelo usuario: conteudo, estado, interacao, layout, navegacao, responsividade, acessibilidade ou design system. Criacao de nova tela, pagina, rota navegavel ou dashboard e sempre aplicavel.

Para o fluxo padrao do `entregar-issue`, executar duas chamadas com fingerprints distintos:

1. `mode=guidance`, `phase=pre-implementation`: antes da primeira edicao visual, produzir hierarquia, acao primaria, estados, estrategia responsiva, acessibilidade e componentes/tokens do design system a reutilizar. Operar sem escrita.
2. `mode=internal-verification`, `phase=post-implementation`: depois do diff estabilizar e antes do gate final, verificar o recorte implementado em leitura e devolver findings/evidencias.

Usar `implementation` somente quando o controlador atribuir caminhos visuais exclusivos a `design-interface`. Nunca permitir escrita concorrente no mesmo caminho. Nao reduzir a aplicabilidade porque a issue descreve apenas comportamento e nao fornece preferencias esteticas.

## Fluxos conversacionais

Acionar quando etapa futura recuperar contexto persistido ou quando houver correlacao, callback, fila, retry, idempotencia, expiracao, cancelamento, concorrencia ou isolamento.

## Documentacao do repositorio

Manter atualizacao simples como modulo interno. Acionar a Skill completa apenas para descoberta ampla, ADR, API, runbook, reorganizacao, fontes geradas ou varredura global de contradicoes.

## Resultado

Validar contrato, `input_fingerprint`, `reused`, identidade, artefatos e caminhos. Resultado de especialidade e evidencia interna; nao encerra a entrega.
