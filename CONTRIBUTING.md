# Contribuindo

Este repositório é uma base de skills para agentes de IA. Mudanças devem preservar **rastreabilidade, fonte canônica única, fail-closed e evidência executável**.

Leia [`AGENTS.md`](./AGENTS.md) antes de contribuir: ele é a instrução normativa para agentes de IA que trabalham neste repositório, incluindo o fluxo de branches e as regras de higiene.

## Antes de abrir uma alteração

0. Abra uma issue usando um template de [`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE/). O corpo da issue alimenta o fechamento de requisitos do ciclo de entrega: use as seções `Escopo`, `Requisitos`, `Critérios de aceite` e `Invariantes`, escreva um item por linha e apague os comentários de orientação antes de abrir.
1. Leia o `SKILL.md` afetado e as referências que ele carrega.
2. Identifique a fonte canônica antes de editar uma cópia.
3. Para uma nova invariante global, registre um requisito em `config/skill-system-requirements.json`.
4. Para uma nova skill, registre-a em `config/skills-catalog.json` e inclua `SKILL.md`, contratos, referências, schemas e testes.
5. Não inclua credenciais, tokens, dados pessoais, artefatos `.audit/` reais ou instruções privadas.

## Validação local

Execute a sequência da seção [Validação local](./README.md#validação-local) do README; ela é idêntica ao CI.

Se você alterou um contrato canônico ou uma fonte declarada em `config/shared-files.json`, regenere as cópias com `python scripts/sync_contracts.py --write`. Não edite uma cópia isoladamente.

## Alterações de skills

- Mantenha `SKILL.md` abaixo de 500 linhas.
- Mantenha os templates de `.github/ISSUE_TEMPLATE/` com apenas headings e comentários: item pré-preenchido vira candidato de requisito no fechamento, e `tests/test_issue_templates.py` reprova a linha que produzir candidato.
- Todo arquivo em `references/`, `scripts/` ou `schemas/` precisa ser alcançável a partir do `SKILL.md`; ao substituir um arquivo, apague o antigo no mesmo PR.
- Antes de criar arquivo novo, procure um existente que possa ser estendido; um arquivo replicado entre skills deve ser declarado em `config/shared-files.json`.
- Schema que nenhum validador aplica é uma segunda fonte de verdade: aplique-o no validador ou não o mantenha.
- Preserve divulgação progressiva; mova detalhes variantes para `references/`.
- Use scripts para comportamento determinístico e testes para invariantes.
- Diferencie verificação interna de auditoria independente.
- Preserve `UNKNOWN` quando faltar evidência.
- Não adicione autoridade de merge, ações destrutivas ou acesso a credenciais por conveniência.

## Pull requests

Descreva a fonte canônica alterada, os contratos afetados, a estratégia de validação e qualquer mudança de comportamento. O CI deve passar antes da revisão. Mudanças incompatíveis precisam explicar migração e impacto nas skills consumidoras.
