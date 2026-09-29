# Adaptador IDE

Mantenha `adapters/`, `config/`, a skill escolhida e todos os seus recursos no mesmo workspace ou disponibilize caminhos absolutos equivalentes. Carregue `config/compatibility.json` → `config/skills-catalog.json` → `config/capabilities.json` → `config/platform-adapters.json` → `<skill>/SKILL.md` → referências condicionais → `schemas/contracts/scripts`. O host deve declarar se o agente pode ler, escrever, executar testes, observar CI e calcular identidade imutável.

Uma regra de projeto da IDE pode apontar para `adapters/generic.md` e para este arquivo. Não copie somente o `SKILL.md` sem seus `references/`, `schemas/`, `contracts/` e `scripts/`. Escrita local não implica autoridade para publicar, fazer merge ou alterar configurações remotas.
