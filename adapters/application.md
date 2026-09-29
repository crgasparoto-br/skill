# Adaptador aplicação própria

A aplicação deve tratar o catálogo como um contrato de integração, não como texto livre. Antes de invocar o modelo, seguir exatamente `config/compatibility.json` → `config/skills-catalog.json` → `config/capabilities.json` → `config/platform-adapters.json` → `<skill>/SKILL.md` → referências condicionais → `schemas/contracts/scripts`:

1. validar `config/compatibility.json`;
2. selecionar a skill a partir de `config/skills-catalog.json`;
3. montar o conjunto de capacidades reais da sessão;
4. carregar progressivamente o `SKILL.md` e referências necessárias;
5. preservar `UNKNOWN`, bloqueio e plano-only no envelope da aplicação.

Registrar `adapter`, `release_version`, `skill_id`, `available_capabilities`, SHA material quando aplicável e resultado do gate. Não enviar segredos ou conteúdo de repositório além do necessário para a tarefa.
