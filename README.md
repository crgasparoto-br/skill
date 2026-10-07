# Skills de Engenharia de Software para IAs

Coleção de skills reutilizáveis para assistentes de IA que trabalham com issues, implementação, auditoria, CI, documentação, interfaces e fluxos conversacionais.

As instruções centrais estão em Markdown e seguem um formato independente de provedor. Os arquivos `agents/openai.yaml` são adaptadores opcionais para produtos compatíveis; uma IA que não reconheça esse formato pode usar diretamente cada `SKILL.md` e carregar as referências necessárias sob demanda.

**Release atual:** [`0.2.0`](./VERSION) · **catálogo:** `2026-09-29.5` · **compatibilidade:** [`config/compatibility.json`](./config/compatibility.json). Para integração reproduzível, prefira uma tag `v<version>` ou um SHA imutável; `main` representa desenvolvimento contínuo.

## Catálogo

<!-- BEGIN GENERATED: skill-catalog -->
| Skill | Finalidade | Entrada principal |
| --- | --- | --- |
| [`auditar-issue`](./auditar-issue/) | Auditar uma entrega em leitura, reconstruindo evidências e preservando a independência do parecer. | Entrega congelada, identidade remota e SHA. |
| [`corrigir-ci`](./corrigir-ci/) | Diagnosticar e remediar falhas de CI até um estado terminal verificável, sem fazer merge. | Falha ou estado pendente de CI. |
| [`design-interface`](./design-interface/) | Projetar, implementar e validar interfaces com acessibilidade, responsividade e consistência visual. | Interface, fluxo visual ou mudança de UX. |
| [`documentacao-repositorio`](./documentacao-repositorio/) | Governar fontes canônicas e manter documentação de repositórios verificável e atualizada. | Repositório, mudança de comportamento ou documentação. |
| [`entregar-issue`](./entregar-issue/) | Conduzir a entrega ponta a ponta de uma issue com plano, implementação, gates, CI e handoff. | Issue, PR, branch ou pendência de software. |
| [`fluxos-conversacionais`](./fluxos-conversacionais/) | Especificar e verificar fluxos persistentes, assíncronos ou conversacionais com estado e idempotência. | Fluxo com continuidade, callback, evento, retry ou estado. |
| [`revisar-issue`](./revisar-issue/) | Tornar issues claras, testáveis e reconciliadas com a documentação canônica. | Issue específica ou lote de issues. |
<!-- END GENERATED: skill-catalog -->

## Como uma IA utiliza uma skill

1. Leia `config/skills-catalog.json` para conhecer finalidade, modos, gatilhos, autoridade e capacidades exigidas.
2. Use `scripts/select_skill.py --query "..." --json` como shortlist explicável; trate `UNKNOWN` ou empate como necessidade de desambiguação.
3. Leia o `SKILL.md` da pasta escolhida.
4. Siga as referências indicadas pelo próprio `SKILL.md` apenas quando o modo de execução exigir.
5. Use `schemas/`, `contracts/`, `scripts/` e `tests/` como artefatos operacionais da skill, não como contexto obrigatório em toda invocação.
6. Preserve a distinção entre verificação interna e auditoria independente descrita nas instruções.

Exemplo de carregamento genérico:

```text
Leia https://github.com/crgasparoto-br/skill/blob/main/entregar-issue/SKILL.md
Use essa skill para executar a issue #123 no repositório owner/repo.
Carregue as referências vinculadas pelo SKILL.md somente quando forem necessárias.
```

Para uma integração local:

```bash
git clone https://github.com/crgasparoto-br/skill.git
cat skill/entregar-issue/SKILL.md
```

## Compatibilidade entre IAs

O formato comum é deliberadamente simples:

- `SKILL.md`: metadados e instruções normativas em Markdown;
- `references/`: conhecimento complementar, carregado progressivamente;
- `schemas/` e `contracts/`: contratos verificáveis e dados estruturados;
- `scripts/`: validações determinísticas e utilitários executáveis;
- `tests/`: regressões e invariantes da skill;
- `agents/openai.yaml`: metadados locais opcionais para interfaces OpenAI compatíveis;
- `adapters/`: instruções agnósticas e por plataforma para carregar o catálogo sem acoplamento a um provedor;
- `config/compatibility.json`: matriz de compatibilidade entre release, catálogo, contratos e skills.
- `config/platform-adapters.json`: manifesto dos ambientes suportados e da ordem de carregamento;
- `docs/PLATFORM_ADAPTERS.md`: guia para adaptar o núcleo a cada host.

### ChatGPT, Codex e APIs compatíveis

Use a pasta da skill como arquivo de instruções ou como skill personalizada quando a plataforma oferecer esse recurso. Os arquivos em `agents/openai.yaml` podem ser usados como metadados de interface, mas não são necessários para interpretar o conteúdo principal.

### Claude, Gemini e outros assistentes

Forneça o `SKILL.md` como contexto de sistema/projeto ou copie seu conteúdo para o mecanismo de instruções da plataforma. Quando o `SKILL.md` apontar para uma referência, forneça também aquele arquivo. Não é necessário interpretar `agents/openai.yaml`.

### IDEs e agentes locais

Mapeie o `SKILL.md` para o mecanismo de regras do agente — por exemplo, uma regra de projeto — e mantenha `references/`, `scripts/` e `tests/` no mesmo diretório para que os caminhos relativos continuem válidos.

## Arquitetura e governança global

O catálogo possui uma camada global de governança acima das regras específicas de cada skill:

- [`docs/SKILL_SYSTEM_SPEC.md`](./docs/SKILL_SYSTEM_SPEC.md) é a especificação mestre e define hierarquia de fontes, identidade exact-head, fail-closed, ownership, contexto suficiente e observabilidade;
- [`config/skill-system-requirements.json`](./config/skill-system-requirements.json) registra requisitos globais com IDs estáveis e referências de implementação/validação;
- [`config/skills-catalog.json`](./config/skills-catalog.json) é o catálogo machine-readable de skills, gatilhos, modos, autoridade e capacidades;
- [`config/capabilities.json`](./config/capabilities.json) define estados e fallbacks quando uma capacidade necessária não está disponível;
- [`schemas/skill-catalog.schema.json`](./schemas/skill-catalog.schema.json) formaliza o formato do catálogo;
- [`schemas/capabilities.schema.json`](./schemas/capabilities.schema.json) formaliza o registro de capacidades;
- [`VERSION`](./VERSION), [`CHANGELOG.md`](./CHANGELOG.md) e [`docs/RELEASE.md`](./docs/RELEASE.md) definem releases SemVer, migração e compatibilidade;
- [`config/compatibility.json`](./config/compatibility.json) evita combinar versões de skills apenas por semelhança textual;
- [`config/shared-files.json`](./config/shared-files.json) declara a fonte canônica de cada arquivo replicado entre skills;
- [`config/platform-adapters.json`](./config/platform-adapters.json) registra adapters, arquivos de instrução e a política de capacidades do host;
- [`docs/PLATFORM_ADAPTERS.md`](./docs/PLATFORM_ADAPTERS.md) documenta generic, OpenAI, Claude, Gemini, IDE e application;
- [`evals/README.md`](./evals/README.md) define o harness provider-agnostic de avaliações comportamentais;
- [`evals/cases/`](./evals/cases/) contém a matriz adversarial e as regressões comportamentais versionadas da V030-002;
- [`docs/ROADMAP.md`](./docs/ROADMAP.md) formaliza o escopo, as prioridades e os critérios de aceite da v0.3.0;
- [`.github/skill-system-capabilities.json`](./.github/skill-system-capabilities.json) declara as capacidades globais efetivamente habilitadas;
- [`docs/SECURITY.md`](./docs/SECURITY.md) define limites de escrita, independência, merge, credenciais e efeitos destrutivos.
- [`AGENTS.md`](./AGENTS.md) é a instrução normativa para agentes de IA que trabalham neste repositório: hierarquia de fontes, fluxo de branches, forma canônica da issue, validação local e regras de higiene;
- [`config/issue-templates.json`](./config/issue-templates.json) é a declaração única das seções normativas que os extratores de requisito leem no corpo da issue, aplicada em [`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE/) e validada por [`scripts/validate_issue_templates.py`](./scripts/validate_issue_templates.py).
- [`config/dependency-policy.json`](./config/dependency-policy.json) declara a política de exceção de vulnerabilidade, exigindo pacote e versão fixada, validada por [`scripts/validate_dependency_locks.py`](./scripts/validate_dependency_locks.py); os lockfiles por skill fixam versão, artefato e hash, e [`scripts/audit_dependencies.py`](./scripts/audit_dependencies.py) confere a integridade do digest contra o artefato e consulta o banco externo no workflow [`.github/workflows/dependency-audit.yml`](./.github/workflows/dependency-audit.yml), fora da sequência obrigatória.

As regras globais usam `UNKNOWN` como estado material de evidência insuficiente. Ausência de informação não deve ser convertida em sucesso, `false`, zero ou `not-applicable`. Aprovação interna, auditoria independente, readiness de release e enforcement de merge são fatos distintos.

A memória da conversa pode ajudar na continuidade, mas o estado necessário à correção deve ser reconstruível a partir do repositório, GitHub e artefatos explicitamente versionados.

## Governança dos contratos

`entregar-issue` é o proprietário canônico dos contratos compartilhados de entrega. As demais skills registram essa relação em `contracts/version.json`. Como cada skill é empacotada isoladamente, alguns scripts, schemas e testes também existem em mais de uma skill; [`config/shared-files.json`](./config/shared-files.json) declara a fonte canônica de cada um. Não altere uma cópia isoladamente: edite a fonte canônica e regenere com `python scripts/sync_contracts.py --write`.

Nenhuma skill mantém referência, script ou schema que o próprio `SKILL.md` não alcance: `scripts/validate_reachability.py` reprova arquivos mortos em vez de deixá-los divergir.

A separação operacional principal é:

- `entregar-issue`: controla a entrega e o handoff;
- `corrigir-ci`: assume temporariamente a propriedade da remediação de CI e devolve um envelope estruturado;
- `auditar-issue`: permanece somente leitura e fornece a avaliação independente;
- as skills especializadas contribuem apenas dentro do recorte atribuído.

## Validação local

Esta é a mesma sequência executada pelo workflow [`.github/workflows/validate.yml`](./.github/workflows/validate.yml):

```bash
python -m pip install --require-hashes -r requirements.lock.txt -r entregar-issue/requirements-dev.lock.txt -r auditar-issue/requirements-dev.lock.txt
python scripts/validate_repository.py
python scripts/validate_catalog.py --root .
python scripts/sync_contracts.py --check --root .
python scripts/validate_docs.py --root .
python scripts/build_catalog_docs.py --check --root .
python scripts/validate_versioning.py --root .
python scripts/validate_adapters.py --root .
python scripts/validate_evals.py --root .
python evals/run_evals.py --root . --results-dir evals/fixtures/results --report /tmp/eval-report.json
python evals/run_evals.py --root . --verify-report /tmp/eval-report.json
python scripts/validate_reachability.py --root .
python scripts/validate_issue_templates.py --root .
python scripts/validate_context_budget.py --root .
python entregar-issue/scripts/validate_skill_genericity.py --skill-root .
python scripts/validate_reference_indexes.py --root .
python scripts/validate_dependency_locks.py --root .
python -m pytest -q
```

Quando um contrato canônico ou uma fonte declarada em `config/shared-files.json` for alterada, regenere as cópias antes de validar:

```bash
python scripts/sync_contracts.py --write
```

Hashes de contratos e pacotes são calculados sobre bytes; `.gitattributes` fixa LF para que o resultado seja idêntico em qualquer sistema operacional.

## Estrutura de uma skill

```text
nome-da-skill/
├── SKILL.md
├── agents/          # metadados opcionais de interface (ex.: OpenAI)
├── assets/          # ícones ou outros recursos de interface
├── contracts/       # contratos operacionais
├── references/      # detalhes carregados sob demanda
├── schemas/         # schemas JSON
├── scripts/         # quando a skill possui automações determinísticas
└── tests/           # regressões e invariantes
```

## Contribuição

Mantenha o `SKILL.md` focado no fluxo central, preserve a divulgação progressiva das referências e adicione testes para cada nova invariante. Evite colocar credenciais, dados pessoais, tokens ou artefatos de auditoria reais no repositório.

Este repositório ainda não declara uma licença de redistribuição. Para autorizar formalmente cópia, adaptação e redistribuição por terceiros, adicione uma licença explícita em uma alteração futura.
