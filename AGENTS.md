# AGENTS.md — instruções normativas para agentes de IA neste repositório

Este arquivo é a fonte aplicável para qualquer agente de IA que trabalhe neste repositório: leitura, revisão, implementação, auditoria ou documentação. Ele complementa o `CONTRIBUTING.md` (voltado a contribuidores humanos) e não substitui o contrato normativo do catálogo.

## Hierarquia de fontes

Quando houver conflito, aplicar esta precedência:

1. [docs/SKILL_SYSTEM_SPEC.md](docs/SKILL_SYSTEM_SPEC.md) — arquitetura e invariantes globais do catálogo;
2. [config/skill-system-requirements.json](config/skill-system-requirements.json) — requisitos globais com IDs estáveis;
3. [config/skills-catalog.json](config/skills-catalog.json), [config/capabilities.json](config/capabilities.json) e seus schemas;
4. `entregar-issue/contracts/*` — contratos compartilhados, cujo proprietário canônico é `entregar-issue`;
5. `<skill>/SKILL.md` — comportamento normativo da skill;
6. `<skill>/references/*` — detalhamento carregado progressivamente;
7. `scripts/`, `tests/` e workflows — implementação executável e evidência de conformidade;
8. issues, PRs e conversas — acompanhamento operacional, que nunca substitui uma fonte canônica versionada.

## Fluxo de trabalho

O desenvolvimento é sequencial: uma issue por vez, sem divergência paralela.

1. Abrir a issue usando um template de `.github/ISSUE_TEMPLATE/`. Issue sem forma canônica é lacuna de especificação, não detalhe de redação.
2. Criar a branch a partir de `develop`, com prefixo `feat/`, `fix/`, `chore/` ou `docs/`.
3. Abrir a PR contra `develop`.
4. Promover `develop` para `main` somente em release. Nenhuma skill tem autoridade implícita de merge, e nenhuma automação deste repositório faz merge. Tags e releases apontam para commits já mergeados em `main`.

## Forma canônica da issue

O ciclo de entrega deriva requisitos do corpo da issue. As seções `Escopo`, `Requisitos`, `Critérios de aceite` e `Invariantes` são lidas como candidatos obrigatórios do fechamento, por dois parsers independentes: o produtor em `entregar-issue` e o controle de auditoria em `auditar-issue`.

Consequências práticas para quem escreve a issue:

- escrever um item por linha; cada linha dessas seções vira requisito auditado;
- evitar item de lista em seção não normativa quando o texto não for requisito;
- os comentários dos templates servem como orientação e devem ser apagados antes de abrir a issue;
- `Invariantes` é a seção para restrição estrutural: comportamento proibido, reuso de fonte existente, fonte única de verdade, proibição de dependência, precedência entre fontes ou caminho de código vedado.

As seções normativas lidas pelos extratores estão declaradas em [config/issue-templates.json](config/issue-templates.json) e validadas por `scripts/validate_issue_templates.py`. O padrão completo de especificação está em [revisar-issue/references/specification-standard.md](revisar-issue/references/specification-standard.md).

### Restrição de redação nos templates

O extrator lê **todas** as linhas do corpo, inclusive comentários HTML. Uma linha de orientação que contenha verbo de obrigação passa a ser extraída como requisito. Por isso os templates deste repositório contêm apenas headings e comentários, e o texto dos comentários é mantido inerte. `tests/test_issue_templates.py` reprova qualquer linha que produza candidato de requisito.

## Validação local

A sequência abaixo é idêntica à do workflow [.github/workflows/validate.yml](.github/workflows/validate.yml). Executá-la antes de abrir a PR é obrigatório.

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

Quando um contrato canônico ou uma fonte declarada em [config/shared-files.json](config/shared-files.json) for alterada, regenerar as cópias antes de validar:

```bash
python scripts/sync_contracts.py --write
```

## Regras de higiene

Estas regras existem para impedir sujeira, ambiguidade, código obsoleto e duplicação desnecessária. Valem para qualquer alteração.

- Não editar cópia gerada de contrato: alterar a fonte canônica e regenerar.
- Não manter arquivo inalcançável: toda referência, script e schema de uma skill precisa ser alcançável a partir do seu `SKILL.md`, reprovado por `scripts/validate_reachability.py`.
- Não criar segunda fonte de verdade: schema que nenhum validador aplica é removido ou passa a ser aplicado.
- Buscar arquivo existente antes de criar outro; arquivo replicado entre skills precisa entrar em `config/shared-files.json`.
- Manter cada `SKILL.md` compacto como control plane dentro do orçamento de [config/context-budget.json](config/context-budget.json), medido em bytes por arquivo e caracteres por linha, sem parágrafos densos que misturem cláusulas independentes. A contagem de linhas não mede carregamento progressivo e não é mais a regra.
- Preservar `UNKNOWN` quando faltar evidência; nunca converter ausência em `false`, zero, sucesso ou `not-applicable`.
- Distinguir verificação interna de auditoria independente; trocar de skill no mesmo contexto não cria independência.
- Tratar alteração de seção canônica como mudança de política: quando um teste compara uma seção normativa com uma forma canônica, alterar a seção exige alterar a forma canônica no mesmo commit, e esse diff passa a exigir auditoria independente contra a issue vigente. O teste prova que a mudança foi deliberada, não que ela preserva os requisitos.
- Tratar o lockfile de dependência como derivado: alteração de dependência começa no manifest (`requirements.txt` na raiz, para o ferramental do catálogo, ou o da skill), e o lockfile é regenerado com `scripts/lock_dependencies.py`; a entrada precisa declarar `# arquivo` e a versão fixada precisa satisfazer o especificador do manifest, porque editar o lockfile à mão esconde a resolução e a validação reprova.
- Escrever documento normativo em Markdown renderizável: contexto inerte — cerca, comentário ou HTML bruto — e recurso de parser — escape de Markdown, caractere de controle, separador que o Markdown não reconhece como fim de linha — escondem a norma sem alterar o texto canônico. O procedimento do registro de auditores recusa esses recursos em vez de enumerar as formas de esconder uma regra.
- Não registrar credenciais, tokens, dados pessoais ou artefatos `.audit/` reais no repositório.
- Não adicionar autoridade de merge, ação destrutiva ou ampliação de permissão por conveniência.

## Escopo e limites de autoridade

Os limites de escrita, independência, credenciais, efeitos destrutivos e merge estão em [docs/SECURITY.md](docs/SECURITY.md). A política de release, versionamento e compatibilidade está em [docs/RELEASE.md](docs/RELEASE.md). O planejamento da próxima versão, com itens identificados como `planned`, está em [docs/ROADMAP.md](docs/ROADMAP.md): planejamento é intenção e não representa capacidade habilitada.
