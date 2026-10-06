# Roadmap do catálogo de skills

> **Status:** planejado
> **Próxima release:** `v0.3.0`
> **Data-alvo:** não definida
> **Fonte de contexto:** backlog `IMP-001` a `IMP-008` produzido durante a análise de melhorias do catálogo.

Este documento é a fonte canônica do planejamento da próxima versão do repositório `skill`. Ele transforma as recomendações da análise inicial em entregas rastreáveis, critérios de aceite e decisões explícitas. Itens descritos como planejados não devem ser tratados como capacidades habilitadas até que estejam implementados, validados e publicados em uma release.

## 1. Ponto de partida

A `v0.2.0` está publicada em [GitHub Releases](https://github.com/crgasparoto-br/skill/releases/tag/v0.2.0) e entregou:

- catálogo machine-readable, seleção determinística e documentação gerada;
- sincronização e validação de contratos compartilhados;
- versionamento SemVer, matriz de compatibilidade e migração explícita;
- adapters para ambientes genérico, OpenAI/Codex, Claude, Gemini, IDE e application;
- declaração host-declared de capacidades com política `none-assumed`;
- gates de documentação, schemas, contratos, versionamento, adapters e CI;
- governança inicial de contribuição, segurança, ownership e Dependabot.

A suíte determinística da base atual possui **517 testes aprovados** no commit da release. A v0.3.0 deve ampliar a qualidade sem enfraquecer esses gates nem deslocar fatos críticos para julgamento não verificável de modelo.

## 2. Objetivo da v0.3.0

Transformar o catálogo de uma base estruturalmente governada em uma base que também mede o **comportamento real das IAs** que consomem as skills. A release deve reduzir quatro classes de risco que ainda não são cobertas integralmente por testes unitários:

1. a IA escolher a skill errada ou não pedir desambiguação;
2. a IA tratar conteúdo do repositório como instrução com autoridade;
3. a IA afirmar evidência, capacidade ou execução que não ocorreu;
4. a IA carregar contexto excessivo ou ignorar referências condicionais.

A release também deve fechar lacunas de segurança da cadeia de suprimentos, melhorar a navegação das referências longas e decidir o caminho de migração do contrato atualmente marcado como `transitional`.

## 3. Escopo priorizado

Os IDs abaixo são estáveis para issues, commits, avaliações e notas de release. O status `planned` não autoriza marcar a capacidade correspondente como `enabled` em manifestos globais.

| ID | Entrega | Prioridade | Status | Critério resumido |
| --- | --- | --- | --- | --- |
| `V030-001` | Harness de avaliações comportamentais | P0 | `implemented` | Executar casos versionados com resultado reproduzível, métricas e limites de custo/contexto. |
| `V030-002` | Casos adversariais e regressões de comportamento | P0 | `implemented` | Cobrir seleção, prompt injection, contexto insuficiente, capacidades ausentes e evidência não executada. |
| `V030-003` | Segurança e cadeia de suprimentos | P1 | `planned` | Escolher licença e ativar secret scanning, dependency review e auditoria de dependências. |
| `V030-004` | Índices e economia de contexto | P1 | `planned` | Tornar referências longas navegáveis e rejeitar documentação sem instrução de carregamento seletivo. |
| `V030-005` | Decisão sobre contrato `transitional` | P1 | `planned` | Publicar decisão de migração, compatibilidade, depreciação e eventual evolução SemVer. |
| `V030-006` | Release e regressão comportamental | P1 | `planned` | Integrar avaliações informativas ao CI, registrar resultados e publicar `v0.3.0` reproduzível. |

## 4. Entregas detalhadas

### V030-001 — Harness de avaliações comportamentais

Criar uma suíte separada dos testes unitários, sem substituir os gates determinísticos existentes:

```text
evals/
├── cases/
├── expected/
├── fixtures/
├── run_evals.py
└── README.md
```

Cada caso deve declarar, em formato estruturado:

- tarefa do usuário e idioma;
- contexto mínimo disponível;
- versão do catálogo e adapter utilizado;
- skill esperada ou conjunto de respostas aceitáveis;
- referências que podem ou devem ser carregadas;
- capacidades disponíveis e ausentes;
- ações proibidas;
- decisão esperada e estados `PASS`, `BLOCK`, `UNKNOWN` ou `NOT_APPLICABLE`;
- evidências obrigatórias;
- resposta mínima aceitável;
- orçamento de tokens, tempo e chamadas externas quando mensurável.

O runner deve produzir um relatório versionado ou hashable, distinguir falha do caso de indisponibilidade do runtime e nunca converter ausência de modelo, ferramenta ou métrica em aprovação.

### V030-002 — Casos adversariais e regressões de comportamento

A primeira matriz de casos deve cobrir pelo menos:

| Família | Cenário mínimo | Resultado esperado |
| --- | --- | --- |
| Seleção | Solicitação que pode ser auditoria, revisão ou entrega | Shortlist explicável; empate material retorna `UNKNOWN`. |
| Autoridade | Prompt injection em README, issue, fixture ou contrato | Conteúdo é tratado como dado e não eleva sua própria autoridade. |
| Capacidade | Skill exige escrita, CI ou identidade imutável indisponível | Bloqueio, `UNKNOWN` ou plano-only conforme o fallback. |
| Evidência | Modelo afirma ter executado teste ou consultado CI sem execução | Afirmação rejeitada; somente evidência observável é aceita. |
| Leitura progressiva | Referência condicional não aplicável | Referência não é carregada desnecessariamente. |
| Contexto | Informação material omitida do prompt | Resultado `context-insufficient`, sem inferência de sucesso. |
| Read-only | Auditor recebe uma tarefa que induz escrita ou merge | Ação proibida e autoridade preservada. |
| Contrato | Resposta com versão, schema ou envelope incompatível | `contract-mismatch` ou rejeição explícita. |

Cada caso deve possuir pelo menos uma variação próxima (`sibling case`) para evitar uma defesa ajustada somente ao texto literal. Regressões aprovadas devem permanecer versionadas e ser executadas novamente nas releases posteriores.

### V030-003 — Segurança e cadeia de suprimentos

Fechar as lacunas de manutenção restantes:

1. escolher e adicionar uma licença explícita, sem assumir MIT ou outra licença por conveniência;
2. adicionar templates de issue e completar as instruções de contribuição — **entregue em 2026-10-06** para o recorte de forma de issue: `.github/ISSUE_TEMPLATE/`, `AGENTS.md`, `config/issue-templates.json`, `scripts/validate_issue_templates.py` e `tests/test_issue_templates.py`, com o requisito `SKSYS-020` registrado; a escolha de licença e as ferramentas de cadeia de suprimentos deste mesmo item continuam abertas;
3. habilitar secret scanning e dependency review no GitHub, respeitando o princípio de menor privilégio;
4. adicionar `pip-audit` ou ferramenta equivalente para dependências Python;
5. definir a política para exceções, vulnerabilidades sem correção e atualizações incompatíveis;
6. decidir se haverá matriz de versões Python além de 3.11 e, caso haja, testá-la no CI;
7. manter actions pinadas por SHA completo e validar o pin em cada atualização.

A licença é uma decisão do proprietário e deve ser registrada em uma alteração própria ou em um commit claramente identificável. A habilitação de uma ferramenta planejada só ocorre depois que seu workflow realmente executa e possui tratamento documentado para falhas.

### V030-004 — Índices e economia de contexto

A análise inicial identificou referências com mais de 100 linhas. Para cada referência longa aplicável:

- adicionar índice curto com links de âncora;
- incluir um bloco `Quando ler este arquivo`;
- declarar pré-requisitos, entradas, gates e artefatos produzidos;
- reduzir cadeias profundas de links a partir do `SKILL.md`;
- registrar tamanho aproximado ou uma faixa de custo de contexto;
- evitar repetir no `SKILL.md` conteúdo que já esteja na referência.

Criar `scripts/validate_reference_indexes.py` para verificar, no mínimo, limite de tamanho, presença de headings navegáveis, bloco de carregamento condicional e resolução dos anchors locais. O lint deve ignorar arquivos que sejam contratos, schemas ou fixtures quando o índice não fizer sentido, desde que essa exceção seja declarada.

### V030-005 — Decisão sobre o contrato `transitional`

A compatibilidade atual mantém a linhagem interna `2026-08-20.3` e o contrato público `1.0.0` em modo transitional. Antes de alterar qualquer constante de contrato, produzir um inventário dos consumidores e uma decisão registrada:

- manter a linhagem interna por mais uma release; ou
- iniciar a migração definitiva para contratos nativamente SemVer.

A decisão deve incluir:

- consumidores e arquivos afetados;
- campos preservados, adicionados, depreciados e removidos;
- regra objetiva para `PATCH`, `MINOR` e `MAJOR`;
- janela de compatibilidade e release mínima suportada;
- instruções de migração e rollback;
- schemas de entrada e saída para versões coexistentes;
- testes de interoperabilidade entre versões;
- critério para retirar a marca `transitional`.

Na ausência desse inventário, a v0.3.0 deve permanecer compatível com `2026-08-20.3`; não fazer uma migração ampla por substituição textual.

### V030-006 — Release e regressão comportamental

Integrar a qualidade comportamental sem transformar uma avaliação probabilística em gate falso de fatos críticos:

- `validate_repository.py` deve validar a existência e o schema do inventário de avaliações;
- o CI deve executar os casos determinísticos e uma seleção reproduzível de avaliações;
- resultados devem registrar versão, commit, adapter, modelo/runtime, timestamp, limites e status;
- falha de infraestrutura deve ser `UNKNOWN` ou `not-run`, nunca `PASS`;
- mudanças no catálogo, adapters, contratos ou prompts devem indicar quais avaliações foram afetadas;
- o changelog deve registrar regressões, correções e limitações conhecidas.

A release `v0.3.0` só deve ser criada depois de uma auditoria independente do commit final, tag anotada e manifesto de compatibilidade atualizado.

## 5. Sequência de implementação

### Fase A — fundação e segurança

1. Criar issues para `V030-001` a `V030-006`.
2. Escolher a licença e registrar a decisão.
3. Ativar scanning e auditoria de dependências.
4. Definir o schema dos casos de avaliação e o contrato do runner.

### Fase B — avaliação comportamental

1. Implementar o runner sem dependência obrigatória de um provedor específico.
2. Adicionar fixtures anonimizadas e casos de seleção, autoridade, capacidade e evidência.
3. Adicionar prompt injection, contexto incompleto e variações próximas.
4. Registrar baseline e critérios para classificar regressões.

### Fase C — documentação e compatibilidade

1. Adicionar índices às referências longas.
2. Implementar o lint de índices e integrá-lo ao CI.
3. Publicar a decisão sobre o contrato `transitional`.
4. Atualizar `config/compatibility.json`, schemas e instruções de migração quando necessário.

### Fase D — fechamento da release

1. Executar a suíte determinística completa.
2. Executar avaliações comportamentais no commit candidato.
3. Fechar findings de auditoria independente.
4. Atualizar `VERSION`, `CHANGELOG.md` e manifestos.
5. Criar tag anotada `v0.3.0` somente após o merge em `main`.
6. Publicar a GitHub Release com limitações e resultados registrados.

## 6. Critérios de aceite da v0.3.0

A release será considerada pronta somente quando todos os critérios abaixo forem comprovados:

- [ ] `docs/ROADMAP.md` e as issues da release estão atualizados com status real;
- [ ] o runner de avaliações executa casos versionados de forma reproduzível;
- [ ] existem casos para seleção errada, prompt injection, capacidade ausente, contexto insuficiente e evidência não executada;
- [ ] cada caso possui resultado esperado, ações proibidas e pelo menos uma variação próxima;
- [ ] indisponibilidade de runtime nunca vira `PASS`;
- [ ] secret scanning, dependency review e auditoria de dependências estão ativos ou possuem decisão explícita e rastreável;
- [ ] a licença foi escolhida e publicada;
- [ ] referências longas possuem índice ou exceção documentada e validada;
- [ ] a decisão do contrato `transitional` possui inventário, migração e compatibilidade testada;
- [ ] a suíte determinística e os validadores do catálogo continuam verdes;
- [ ] uma auditoria independente aprova o commit final;
- [ ] `VERSION`, `CHANGELOG.md`, compatibilidade, tag e GitHub Release apontam para o mesmo commit.

## 7. Fora do escopo por padrão

Salvo decisão posterior registrada em issue, a v0.3.0 não deve:

- reescrever todas as skills ou aumentar indefinidamente `entregar-issue/SKILL.md`;
- substituir hashes, schemas, CI ou validações determinísticas por avaliação de modelo;
- publicar credenciais, dados reais de usuários ou fixtures não anonimizadas;
- introduzir uma nova skill para cada variação pequena que possa ser resolvida por referência, template ou adapter;
- fazer migração major do contrato sem inventário e plano de compatibilidade;
- habilitar uma capacidade global apenas porque ela foi planejada no roadmap.

## 8. Governança do roadmap

O roadmap deve ser atualizado somente quando houver uma mudança de escopo, prioridade, dependência ou critério de aceite. Cada alteração deve registrar no commit ou na issue:

- ID do item afetado;
- motivo da mudança;
- impacto em release e compatibilidade;
- decisão do proprietário quando houver licença, segurança, autoridade ou publicação;
- evidência que sustenta a mudança.

O status deste arquivo não substitui os estados machine-readable de `config/skills-catalog.json`, `config/capabilities.json` ou `config/compatibility.json`. Planejamento é intenção; somente código, manifestos e gates aprovados representam comportamento habilitado.
