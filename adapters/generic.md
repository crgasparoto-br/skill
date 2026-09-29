# Adaptador genérico

Use este protocolo quando a plataforma não possui um formato de adapter próprio. Ele é deliberadamente **agnóstico**: não presume Git, escrita, CI, navegador, execução de testes ou credenciais.

## Ordem obrigatória

1. Ler `config/compatibility.json` e confirmar a release suportada.
2. Ler `config/skills-catalog.json` e selecionar uma shortlist explicável.
3. Declarar as capacidades realmente disponíveis no host usando os nomes de `config/capabilities.json`.
4. Ler `config/platform-adapters.json` e este adapter.
5. Ler somente o `<skill>/SKILL.md` selecionado.
6. Carregar referências condicionais e o grupo `schemas/contracts/scripts`.
7. Bloquear, retornar `UNKNOWN` ou produzir plano-only quando uma capacidade exigida estiver ausente.

## Envelope mínimo do host

```json
{
  "adapter": "generic",
  "release_version": "0.2.0",
  "available_capabilities": ["repository-read"],
  "requested_skill": "<skill-id>"
}
```

O host deve registrar a versão efetivamente carregada e não pode converter um arquivo ausente ou uma ferramenta indisponível em sucesso. A plataforma decide como fornecer arquivos e executar comandos; a skill decide apenas dentro da autoridade declarada em seu catálogo e contrato.
