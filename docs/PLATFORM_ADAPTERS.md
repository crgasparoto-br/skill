# Adaptadores de plataforma

O repositório possui um núcleo agnóstico e adapters pequenos por ambiente. O manifesto [`config/platform-adapters.json`](../config/platform-adapters.json) é a fonte machine-readable; as instruções detalhadas vivem em [`adapters/`](../adapters/).

| Adapter | Arquivo | Ambiente | Presunções |
| --- | --- | --- | --- |
| `generic` | [`adapters/generic.md`](../adapters/generic.md) | Qualquer assistente | Nenhuma capacidade é presumida. |
| `openai` | [`adapters/openai.yaml`](../adapters/openai.yaml) | ChatGPT, Codex e APIs compatíveis | O host declara ferramentas disponíveis. |
| `claude` | [`adapters/claude.md`](../adapters/claude.md) | Projetos e agentes Claude | O host declara ferramentas disponíveis. |
| `gemini` | [`adapters/gemini.md`](../adapters/gemini.md) | Gems e agentes Gemini | O host declara ferramentas disponíveis. |
| `ide` | [`adapters/ide.md`](../adapters/ide.md) | IDEs e agentes locais | Workspace não implica autoridade remota. |
| `application` | [`adapters/application.md`](../adapters/application.md) | Aplicações próprias | A aplicação fornece o envelope de capacidades. |

Todos usam a mesma sequência exata: `config/compatibility.json` → `config/skills-catalog.json` → `config/capabilities.json` → `config/platform-adapters.json` → `<skill>/SKILL.md` → referências condicionais → `schemas/contracts/scripts`. A ausência de uma capacidade nunca é tratada como sucesso.
