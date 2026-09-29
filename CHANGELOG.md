# Changelog

Todas as mudanças relevantes deste catálogo são registradas neste arquivo. A versão pública do conjunto é mantida em [`VERSION`](./VERSION). O formato segue SemVer para releases do catálogo; a versão interna de contratos permanece identificada no manifesto de compatibilidade durante a migração.

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
