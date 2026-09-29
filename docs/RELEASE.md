# Política de releases e compatibilidade

## Superfícies de versão

| Superfície | Exemplo | Finalidade |
| --- | --- | --- |
| `VERSION` | `0.2.0` | Versão pública SemVer do conjunto de skills e adaptadores. |
| `config/skills-catalog.json.catalog_version` | `2026-09-29.5` | Snapshot temporal do catálogo e da governança interna. |
| `config/skill-system-requirements.json.system_version` | `2026-09-29.5` | Versão das invariantes globais do sistema. |
| `contracts/version.json.contract_version` | `2026-08-20.3` | Linhagem interna legada dos contratos já consumidos pelas skills. |
| `config/compatibility.json.contract_policy.public_contract_version` | `1.0.0` | Versão pública SemVer do contrato de composição. |

A versão pública é a referência para consumidores externos. A linhagem interna não deve ser alterada silenciosamente: durante a transição, uma entrada explícita em `config/compatibility.json` mapeia cada versão pública para a linhagem interna suportada.

## Regras SemVer

- **MAJOR:** quebra de schema, mudança de semântica, remoção de campo, mudança de autoridade ou incompatibilidade que exige migração.
- **MINOR:** capacidade, campo, adapter, skill ou comportamento aditivo compatível.
- **PATCH:** correção compatível, documentação, validação mais precisa ou correção de erro sem mudança de contrato.

Alterar apenas a data de catalogação ou uma implementação interna não autoriza esconder uma quebra de contrato. Se consumidores precisarem alterar o modo de carregamento ou de interpretação, a versão pública deve refletir isso.

## Checklist de release

1. Atualizar `VERSION` conforme SemVer.
2. Atualizar `catalog_version` e `system_version` no mesmo change set.
3. Atualizar `config/compatibility.json`, incluindo `min_release`, `migration` e o mapeamento de contrato.
4. Adicionar a entrada correspondente em `CHANGELOG.md`.
5. Executar `python scripts/validate_versioning.py`.
6. Executar `python scripts/validate_repository.py`, a suíte de testes e os checks do CI.
7. Após o merge, criar uma tag anotada `v<VERSION>` apontando para o commit final revisado.
8. Nunca reutilizar uma tag ou publicar uma release com manifesto diferente do commit tagueado.

A criação da tag e da release é deliberadamente posterior ao merge; uma pull request não cria uma release imutável.

## Compatibilidade e migração

Cada skill validada deve aparecer no manifesto de compatibilidade com sua versão pública de contrato, linhagem interna, release mínima suportada e instrução de migração. Uma combinação não declarada deve ser tratada como `UNKNOWN` ou incompatível, nunca como compatível por aproximação textual.

Cada adapter validado deve aparecer em `config/platform-adapters.json` e `config/compatibility.json` com `introduced_in`/`min_release` iguais. A release `0.2.0` introduz `generic`, `openai`, `claude`, `gemini`, `ide` e `application` sem presumir capacidades do host.

| Adapter | Introduced in | Compatibility status |
| --- | --- | --- |
| `generic` | `0.2.0` | `supported` |
| `openai` | `0.2.0` | `supported` |
| `claude` | `0.2.0` | `supported` |
| `gemini` | `0.2.0` | `supported` |
| `ide` | `0.2.0` | `supported` |
| `application` | `0.2.0` | `supported` |

Ao remover uma versão, mantenha uma nota de migração e a última release que a suporta. Não apague o histórico do changelog para esconder uma quebra.
