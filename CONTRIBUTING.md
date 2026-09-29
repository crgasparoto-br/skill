# Contribuindo

Este repositório é uma base de skills para agentes de IA. Mudanças devem preservar **rastreabilidade, fonte canônica única, fail-closed e evidência executável**.

## Antes de abrir uma alteração

1. Leia o `SKILL.md` afetado e as referências que ele carrega.
2. Identifique a fonte canônica antes de editar uma cópia.
3. Para uma nova invariante global, registre um requisito em `config/skill-system-requirements.json`.
4. Para uma nova skill, registre-a em `config/skills-catalog.json` e inclua `SKILL.md`, contratos, referências, schemas e testes.
5. Não inclua credenciais, tokens, dados pessoais, artefatos `.audit/` reais ou instruções privadas.

## Validação local

```bash
python3 scripts/validate_repository.py
python3 scripts/sync_contracts.py --check
python3 scripts/validate_catalog.py
python3 scripts/validate_docs.py
python3 scripts/build_catalog_docs.py --check
python3 -m pytest -q
```

Se você alterou um contrato canônico, regenere as cópias com:

```bash
python3 scripts/sync_contracts.py --write
```

Não edite uma cópia gerada isoladamente.

## Alterações de skills

- Mantenha `SKILL.md` abaixo de 500 linhas.
- Preserve divulgação progressiva; mova detalhes variantes para `references/`.
- Use scripts para comportamento determinístico e testes para invariantes.
- Diferencie verificação interna de auditoria independente.
- Preserve `UNKNOWN` quando faltar evidência.
- Não adicione autoridade de merge, ações destrutivas ou acesso a credenciais por conveniência.

## Pull requests

Descreva a fonte canônica alterada, os contratos afetados, a estratégia de validação e qualquer mudança de comportamento. O CI deve passar antes da revisão. Mudanças incompatíveis precisam explicar migração e impacto nas skills consumidoras.
