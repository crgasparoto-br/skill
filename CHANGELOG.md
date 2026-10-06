# Changelog

Todas as mudanças relevantes deste catálogo são registradas neste arquivo. A versão pública do conjunto é mantida em [`VERSION`](./VERSION). O formato segue SemVer para releases do catálogo; a versão interna de contratos permanece identificada no manifesto de compatibilidade durante a migração.

## [Unreleased]

### Fixed

- restaura o guard terminal `validate_delivery_completion.py` usado pelo controlador `entregar-issue`;
- faz `validate_terminal_handoff.py` emitir `terminal-handoff-proof.json` consumível pelo completion guard;
- adiciona empacotamento fail-closed da `entregar-issue`, validando scripts referenciados e publicando `skill.zip` completo como artefato da CI.

### Added

- `CODE-GROWTH-001` passa a ser produzido pela entrega: `check_code_growth.py` mede o crescimento de arquivos de código com política padrão (300/500/20) sobrescrevível por `.github/code-growth-policy.json` lido do SHA base, e o certificado exige o relatório quando o escopo toca código;
- certificado de handoff passa a exigir `codebase_grounding` quando o escopo local da issue toca código; o validador compartilhado recalcula a aplicabilidade e rejeita rebaixamento ou relatório stale;
- gate `codebase-grounding` em `entregar-issue`: busca antes de criar (`GROUND-REUSE-001`), prova de existência antes de usar (`GROUND-EXIST-001`) e proibição de sobra (`GROUND-DEAD-001`), com validador determinístico contra o Git e refutação independente em `auditar-issue`;
- harness provider-agnostic de avaliações comportamentais com casos versionados, replay determinístico, métricas limitadas e relatórios hashable;
- contratos JSON Schema para casos, resultados e relatórios de avaliação;
- gate de validação do harness integrado ao validador global e ao CI;
- vinculação exata entre caso, adapter e resultado, atestação estrutural, verificação de relatórios e replay sem arquivos extras.
- matriz V030-002 com 22 casos adversariais versionados para seleção, autoridade, capacidades, evidências, contexto insuficiente, leitura progressiva, read-only e contratos incompatíveis;
- pares `sibling_case_id` recíprocos, controles de ações proibidas e evidências obrigatórias, com replay determinístico de cada regressão.

### Compatibility

Esta alteração está planejada para a `v0.3.0` e ainda não altera a tag pública `v0.2.0`. O snapshot interno do sistema avança para `2026-09-29.5`; o contrato público continua `1.0.0` e a linhagem interna continua `2026-08-20.3`.

## [0.2.0] — 2026-09-29

### Added

- manifesto machine-readable de adaptadores para ambientes genérico, OpenAI, Claude, Gemini, IDE e aplicação própria;
- protocolo comum de carregamento progressivo e declaração de capacidades pelo host;
- validação dos adapters, seus arquivos de instrução e ordem de carregamento.

### Compatibility

Esta é uma mudança minor compatível: os adapters são aditivos e não alteram a linhagem interna `2026-08-20.3` nem a versão pública do contrato `1.0.0`.

## [0.1.0] — 2026-09-29

### Added

- catálogo machine-readable de skills, gatilhos, autoridade e capacidades;
- contrato de capacidades com fallbacks fail-closed;
- sincronização e validação de contratos gerados;
- validação de documentação, links e catálogo gerado;
- governança de contribuição, segurança e CI com actions pinadas;
- manifesto de compatibilidade que separa release pública, catalog version e linhagem interna de contratos.

### Compatibility

Esta release mantém `2026-08-20.3` como linhagem interna dos contratos existentes e publica `1.0.0` como versão pública compatível do contrato durante a transição. Consulte [`config/compatibility.json`](./config/compatibility.json) e [`docs/RELEASE.md`](./docs/RELEASE.md) antes de combinar skills de releases diferentes.
