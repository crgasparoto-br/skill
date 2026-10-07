# Changelog

Todas as mudanças relevantes deste catálogo são registradas neste arquivo. A versão pública do conjunto é mantida em [`VERSION`](./VERSION). O formato segue SemVer para releases do catálogo; a versão interna de contratos permanece identificada no manifesto de compatibilidade durante a migração.

## [Unreleased]

### Removed

- fluxo legado de orquestração substituído pelo controlador atual: máquina de estados `orchestration-state` v3, `loop-state` v5 e sua migração, `evidence.json` v9, gate interno e coletor remoto do Orquestrador, importação de auditoria externa via estado aprovado e os testes que exercitavam somente esse código (`entregar-issue` passa de 163 para 108 arquivos em `references/`, `scripts/` e `schemas/`);
- modo alternativo `orquestrador`/Delivery V2 e aliases de wrappers inexistentes (`issue-loop-engineer`, `implementar-issue`, `higienizacao`); delegação fica restrita às skills listadas no modelo arquitetural do `SKILL.md`;
- cópias redundantes: `entregar-issue/references/github-actions-policy.md` (fica `contracts/`), `entregar-issue/schemas/controller-context.schema.json` (promovido ao contrato), `corrigir-ci/references/ci-ownership.md` e `design-interface/references/integration-contract.md`, que contradizia o controlador atual.

### Changed

- referências vivas que estavam desconectadas passam a ser carregadas pelo `SKILL.md`: snapshot de especificação e fechamento de requisitos (com seus scripts), gates críticos F20–F27, checklists de fechamento por categoria, gate remoto, matriz de impacto documental, checklist de auditoria e inicializadores de matriz, saturação, evidência padrão, proveniência e métricas visuais;
- `runtime_graph` passa a ser exposto por `scripts/map_runtime_consumers.py` para a reconciliação pós-diff e para `GROUND-DEAD-001`; grafo incompleto resulta em `UNKNOWN`;
- `requirement-closure.json` e `audit-remediation.json` passam a ser validados contra seus schemas; `execution-plan.json` e o envelope de `corrigir-ci` têm paridade schema↔validador verificada em teste;
- resultado de subskill e `skill_plan` só aceitam skills do catálogo;
- `auditar-issue` passa a usar o `validate_learning_closure.py` estrito de `entregar-issue` (antes aceitava `rejection_id` ausente).

### Fixed

- hashes de contratos e fixtures dependiam do final de linha do checkout; `.gitattributes` fixa LF e os validadores usam caminhos POSIX;
- restaura o guard terminal `validate_delivery_completion.py` usado pelo controlador `entregar-issue`;
- faz `validate_terminal_handoff.py` emitir `terminal-handoff-proof.json` consumível pelo completion guard;
- adiciona empacotamento fail-closed da `entregar-issue`, validando scripts referenciados e publicando `skill.zip` completo como artefato da CI.

### Added

- o CI passa a instalar as dependências de teste do próprio lockfile com `--require-hashes`, de modo que o ambiente que executa o gate é o ambiente registrado, e uma distribuição que não corresponde ao digest reprova a instalação;
- reprodutibilidade de dependências: cada manifest de skill passou a ter lockfile irmão que fixa versão exata, artefato e hash sha256 do fechamento transitivo, e [`scripts/validate_dependency_locks.py`](./scripts/validate_dependency_locks.py) reprova, offline, lockfile dessincronizado, versão fixada que não satisfaz o especificador declarado, entrada sem hash, entrada sem `# arquivo` ou com artefato incompatível com nome e versão, faixa aberta, anotação `# via` órfã e cadeia que não alcança pacote declarado; [`config/dependency-policy.json`](./config/dependency-policy.json) declara a política para vulnerabilidade sem correção, exigindo pacote, versão fixada, justificativa e data de revisão; a integridade do digest, conferida contra o artefato por `pip download --require-hashes`, e a consulta ao banco externo ficam em [`.github/workflows/dependency-audit.yml`](./.github/workflows/dependency-audit.yml), fora da sequência obrigatória, que reporta `UNKNOWN` em vez de sucesso quando não consegue verificar e reprova exceção que não casa identificador, pacote e versão de um achado real; o gate também reprova inclusão `-r` que não resolve, avalia marcador de ambiente contra o contexto registrado no cabeçalho e reprova marcador que não entende, exige sufixo de distribuição na anotação do artefato, exige que os campos de nome e versão do artefato sejam exatamente os fixados, reprova linha de requisito que não interpreta e inclusão que não é manifest, e analisa versão e especificador por inteiro, incluindo segmento local; o marcador de ambiente é avaliado contra o interpretador que executa o gate, e não contra o comentário de contexto, com precedência de `and` antes de `or` como a PEP 508 exige e com a gramática validada por inteiro antes de qualquer atalho lógico, reprovando opção de manifest que o gate não implementa, inclusão que sai da raiz do repositório, opção que não seja `--hash` no próprio lockfile e versão ou especificador que não seja PEP 440 válido por completo, inclusive a semântica de versão local em `==` e `!=`, exigindo que manifest, lockfile e política resolvam para dentro da raiz do repositório (`SKSYS-026`);
- governança do registro de auditores confiáveis: [`docs/SECURITY.md`](./docs/SECURITY.md) declara custódia, separação entre produtor e aprovador do registro, geração e custódia de chave, rotação, revogação e a limitação de operador único, e [`auditar-issue/scripts/build_trusted_auditor_entry.py`](./auditar-issue/scripts/build_trusted_auditor_entry.py) monta a entrada derivando o fingerprint dos bytes publicados, recusando chave privada e chave que não seja Ed25519 e validando a própria saída contra o esquema (`SKSYS-025`);
- navegabilidade das referências longas: [`config/reference-index.json`](./config/reference-index.json) declara o limiar em bytes e [`scripts/validate_reference_indexes.py`](./scripts/validate_reference_indexes.py) exige bloco de carregamento condicional e índice com âncoras que resolvem e cobrem todas as seções; as doze referências acima de 8 KB receberam os dois blocos, e o teto de referência do orçamento subiu de 16 KiB para 17 KiB para comportar o bloco exigido (`SKSYS-024`);
- genericidade de assets permanentes efetivamente aplicada: [`entregar-issue/scripts/validate_skill_genericity.py`](./entregar-issue/scripts/validate_skill_genericity.py) passa a bloquear caminho absoluto de host, identificador concreto em prosa Markdown fora de exemplo delimitado e host externo concreto que não seja domínio reservado de exemplo ou host genérico declarado, e o CI passa a executar o validador sobre a raiz do catálogo, que antes só era exercitado em diretório temporário por um teste da própria skill (`SKSYS-023`);
- orçamento de contexto aplicado ao control plane e às referências: [`config/context-budget.json`](./config/context-budget.json) declara limites de bytes por arquivo e caracteres por linha, e [`scripts/validate_context_budget.py`](./scripts/validate_context_budget.py) reprova arquivo acima do padrão sem exceção, exceção sem justificativa, exceção órfã, exceção desnecessária e exceção que divirja da medição atual (`SKSYS-022`);
- teste de paridade que compara a sequência de validação executada pelo CI com a publicada em [`README.md`](./README.md) e [`AGENTS.md`](./AGENTS.md), e verifica que todo validador independente é alcançável a partir do workflow;
- cobertura de **seleção resolvida** no harness de avaliações: quatro casos em pares de irmãos aterrados no roteador real, dois casos de fraseado reordenado que permanecem `UNKNOWN` e a regra da categoria `selection` em `scripts/validate_evals.py` distinguindo empate material, seleção resolvida e ausência de correspondência (`SKSYS-021`);
- geração e verificação do relatório de replay de `evals/run_evals.py` no CI, exercitando `content_sha256`, `run_id` e o resumo, que antes não eram cobertos por nenhuma etapa;
- forma canônica versionada para a issue que alimenta o fechamento de requisitos: [`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE/) com templates de desenvolvimento, defeito e epic, [`config/issue-templates.json`](./config/issue-templates.json) declarando as seções normativas lidas pelos extratores e [`scripts/validate_issue_templates.py`](./scripts/validate_issue_templates.py) reprovando template sem seção normativa ou com item pré-preenchido que viraria candidato de requisito (`SKSYS-020`);
- [`AGENTS.md`](./AGENTS.md) como instrução normativa para agentes de IA que trabalham no repositório: hierarquia de fontes, fluxo de issue para `develop` e `develop` para `main`, forma canônica da issue, restrição de redação dos templates, validação local e regras de higiene;
- `tests/test_issue_templates.py` provando que o texto de orientação dos templates é inerte para as regexes reais de `entregar-issue`, que as seções normativas declaradas continuam reconhecidas pelo parser independente de `auditar-issue` e que remover uma seção normativa ou inserir placeholder bloqueia o validador;
- `config/shared-files.json` declara a fonte canônica dos arquivos replicados entre skills, verificados e regenerados por `sync_contracts.py` (SKSYS-012);
- `scripts/validate_reachability.py` reprova referência, script ou schema inalcançável a partir do `SKILL.md` (SKSYS-019);
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
