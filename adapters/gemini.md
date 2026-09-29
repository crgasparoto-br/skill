# Adaptador Gemini

Use o catálogo como índice, não carregue todas as skills em cada solicitação. O host deve fornecer exatamente nesta ordem: `config/compatibility.json`, `config/skills-catalog.json`, `config/capabilities.json`, `config/platform-adapters.json`, `<skill>/SKILL.md`, referências condicionais e `schemas/contracts/scripts`.

O adapter não presume conectores, acesso remoto, escrita ou execução local. Mapear cada ferramenta real para um nome de `config/capabilities.json`; se o mapeamento não existir, retornar `UNKNOWN` ou bloquear a ação. Não substituir evidência executada por uma afirmação do modelo.
