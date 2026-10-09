# Registro de evidências de migração de CI

Template preenchível para cada repositório consumidor do [contrato canônico](./CI_POST_ORQUESTRADOR.md). Copiar para a PR de migração e substituir todo `UNKNOWN` por evidência verificável. **Não usar este template como prova de migração por si só.**

## Identificação

- Repositório: UNKNOWN
- Issue de migração: UNKNOWN
- PR: UNKNOWN
- Branch base e SHA: UNKNOWN
- Head SHA testado: UNKNOWN
- Merge preview SHA testado: UNKNOWN
- Responsável pela proteção de branch/rulesets: UNKNOWN
- Data (UTC): UNKNOWN

## Inventário de required checks — antes e depois

| Contexto obrigatório atual (literal) | Workflow/job e app emissor | Ruleset/branch protection | Contexto substituto (literal) | Evidência de sucesso no head e merge preview | Alteração validada em ruleset (UTC) | Rollback |
| --- | --- | --- | --- | --- | --- | --- |
| UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

**Invariantes:** não excluir nem renomear contexto requerido antes de provar o substituto e coordenar o ruleset; `UNKNOWN` bloqueia a remoção do legado. Confirmar via API do GitHub e interface administrativa. CI verde isoladamente não comprova regras de proteção.

## Matriz de risco local

| Perfil | Paths / condições verificáveis | Gates efetivos | Comando reproduzível | Run e SHA |
| --- | --- | --- | --- | --- |
| FAST | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| STANDARD | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| CRITICAL | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

Exigir precedência CRITICAL > STANDARD > FAST. Mudança no workflow, segurança, secrets, classificador, banco ou migração; path desconhecido; falha/truncamento do diff: CRITICAL ou bloqueio explícito. Registrar como a política local diferencia documentação segura de documentação executável.

## Ensaios positivos e negativos

Preencher cada caso com `PASS` ou `FAIL`, comando, URL do run, SHA do head e do candidato. `NOT RUN` nunca equivale a PASS.

| Caso | Esperado | Observado | Evidência |
| --- | --- | --- | --- |
| Documentação estritamente segura | FAST + gates aplicáveis | NOT RUN | UNKNOWN |
| Código de aplicação | STANDARD + build/testes aplicáveis | NOT RUN | UNKNOWN |
| Auth, workflow, migração, rename crítico, path desconhecido | CRITICAL | NOT RUN | UNKNOWN |
| Diff incompleto / API indisponível / perfil inválido | CRITICAL ou falha fechada | NOT RUN | UNKNOWN |
| Gate obrigatório failure/cancelled/skipped indevidamente | Agregador reprova | NOT RUN | UNKNOWN |
| Head alterado após início da execução | Check antigo não aprova novo head | NOT RUN | UNKNOWN |
| Base alterada / merge preview inválido | Agregador reprova | NOT RUN | UNKNOWN |
| Required check renomeado sem ruleset atualizado | Rollout bloqueado | NOT RUN | UNKNOWN |
| Tentativa de executar IA/skill/orquestrador no Actions | Inspeção reprova | NOT RUN | UNKNOWN |

## Gates específicos preservados

- Stack e versões pinadas: UNKNOWN
- Build/typecheck/lint/testes unitários: UNKNOWN
- Testes de integração, banco, migrações e E2E: UNKNOWN
- Segurança, arquitetura e testes visuais quando aplicáveis: UNKNOWN
- Artefatos/logs sem secrets e vínculo ao SHA: UNKNOWN
- Eventual merge queue (`merge_group`) e política de forks: UNKNOWN

## Corte e reversão

1. Salvar commit, workflows, dependências/locks, contexts e rulesets originais: UNKNOWN.
2. Publicar classificador e checks novos em paralelo aos legados: UNKNOWN.
3. Validar head exato, merge preview e cenários negativos em PR: UNKNOWN.
4. Confirmar configuração real do ruleset e só então retirar check legado: UNKNOWN.
5. Eliminar runtime/locks/variáveis do `delivery-orchestrator` somente após busca de consumidores e testes: UNKNOWN.
6. Rollback testado/ensaiado: commit de reversão ou restauração de workflow + contexts anteriores, sem desabilitar proteção: UNKNOWN.

## Parecer de conformidade

- [ ] Há prova do SHA exato, merge preview e resultado terminal de todos os gates aplicáveis.
- [ ] Os required contexts reais foram inventariados e verificados por pessoa com acesso à proteção.
- [ ] Nenhum job de CI executa IA, skill ou runtime do delivery-orchestrator.
- [ ] Os testes negativos foram executados e falharam como esperado.
- [ ] A remoção de legado não deixa dependências ou consumidores órfãos.
- [ ] Existe rollback reproduzível e proteção nunca é relaxada para obter verde.

**Decisão:** PENDENTE até todas as caixas e evidências estarem completas. O merge depende de autorização explícita.
