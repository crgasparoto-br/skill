# Fronteira de recertificacao apos CI

## Objetivo

Impedir composicao circular entre `corrigir-ci` e `entregar-issue`. A Skill de CI possui o material somente ate CI terminal; a recertificacao pertence ao controlador superior.

## Regra

Em modo delegado por `entregar-issue`:

1. `corrigir-ci` observa, diagnostica, corrige, publica material e acompanha a CI ate terminal;
2. ao atingir CI material verde, reconsulta o head e fecha a propriedade de CI;
3. produz um unico envelope schema 2 com `next_phase=finalize-after-ci` e `ci_owner_closed=true`;
4. retorna ao controlador ja existente;
5. **nao invoca `entregar-issue`, nao publica `.audit/entregar-issue/*`, nao cria result-only child e nao executa latch terminal de handoff**.

O controlador `entregar-issue` consome o envelope e executa `finalize-after-ci -> post-write-refreeze se necessario -> result-only -> terminal handoff`.

## Motivo

A composicao `entregar -> corrigir -> entregar -> corrigir` duplica ownership, aumenta custo de contexto e pode encerrar em falso `blocked-handoff-recertification` por limite de invocacao. O modelo correto e `entregar [nivel 0] -> corrigir [subrotina] -> entregar.finalize-after-ci [terminal]`.

## Standalone

Quando o usuario invoca `corrigir-ci` diretamente, a Skill pode informar CI material verde sem afirmar que uma entrega governada esta pronta para auditoria. Se detectar handoff stale, deve devolver o mesmo envelope/next action em vez de tentar assumir ownership dos artefatos de entrega.

## Bloqueio real

`interrupted-by-runtime` e `blocked-external` continuam validos para impedimentos reais da CI. Ausencia de recertificacao dentro de `corrigir-ci` nao e bloqueio: e responsabilidade normal do caller apos `green-material`.
