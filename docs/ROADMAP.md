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
| `V030-003` | Segurança e cadeia de suprimentos | P1 | `planned` | Lockfile por skill e política de exceção entregues; licença, secret scanning, dependency review e matriz de Python permanecem abertos. |
| `V030-004` | Índices e economia de contexto | P1 | `implemented` | Tornar referências longas navegáveis e rejeitar documentação sem instrução de carregamento seletivo. |
| `V030-005` | Decisão sobre contrato `transitional` | P1 | `planned` | Publicar decisão de migração, compatibilidade, depreciação e eventual evolução SemVer. |
| `V030-006` | Release e regressão comportamental | P1 | `planned` | Integrar avaliações informativas ao CI, registrar resultados e publicar `v0.3.0` reproduzível. |
| `V030-007` | Genericidade de assets permanentes | P1 | `implemented` | Rejeitar acoplamento concreto a issue, host, caminho e identificador de domínio, e executar o validador sobre o catálogo. |
| `V030-009` | Análise estática real do código | P1 | `implemented` | Aplicar famílias de regras com política declarada, reprovar sujeira, import morto e supressão não declarada, e manter a cobertura de regras impossível de encolher em silêncio. |
| `V030-008` | Governança do registro de auditores confiáveis | P2 | `implemented` | Declarar custódia, separação entre produtor e aprovador, rotação, revogação e limitação de operador único, e tornar a entrada de registro verificável. |

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
| Seleção | Solicitação que pode ser auditoria, revisão ou entrega | Shortlist explicável; empate material retorna `UNKNOWN` e intenção resolvida seleciona o skill correto. |
| Autoridade | Prompt injection em README, issue, fixture ou contrato | Conteúdo é tratado como dado e não eleva sua própria autoridade. |
| Capacidade | Skill exige escrita, CI ou identidade imutável indisponível | Bloqueio, `UNKNOWN` ou plano-only conforme o fallback. |
| Evidência | Modelo afirma ter executado teste ou consultado CI sem execução | Afirmação rejeitada; somente evidência observável é aceita. |
| Leitura progressiva | Referência condicional não aplicável | Referência não é carregada desnecessariamente. |
| Contexto | Informação material omitida do prompt | Resultado `context-insufficient`, sem inferência de sucesso. |
| Read-only | Auditor recebe uma tarefa que induz escrita ou merge | Ação proibida e autoridade preservada. |
| Contrato | Resposta com versão, schema ou envelope incompatível | `contract-mismatch` ou rejeição explícita. |

Cada caso deve possuir pelo menos uma variação próxima (`sibling case`) para evitar uma defesa ajustada somente ao texto literal. Regressões aprovadas devem permanecer versionadas e ser executadas novamente nas releases posteriores.

**Entregue em 2026-10-06** para o recorte de seleção e de relatório: a família `selection` passou a provar também **seleção resolvida**, não apenas abstenção, com quatro casos em pares de irmãos aterrados no roteador real (`scripts/select_skill.py`) e dois casos de fraseado reordenado que permanecem `UNKNOWN`. A regra da categoria em `scripts/validate_evals.py` distingue as três formas — empate material, seleção resolvida e ausência de correspondência — e o CI passou a gerar e verificar o relatório de replay de `evals/run_evals.py`, exercitando `content_sha256`, `run_id` e o resumo. Requisito `SKSYS-021`.

### V030-003 — Segurança e cadeia de suprimentos

Fechar as lacunas de manutenção restantes:

1. escolher e adicionar uma licença explícita, sem assumir MIT ou outra licença por conveniência;
2. adicionar templates de issue e completar as instruções de contribuição — **entregue em 2026-10-06** para o recorte de forma de issue: `.github/ISSUE_TEMPLATE/`, `AGENTS.md`, `config/issue-templates.json`, `scripts/validate_issue_templates.py` e `tests/test_issue_templates.py`, com o requisito `SKSYS-020` registrado; a escolha de licença e as ferramentas de cadeia de suprimentos deste mesmo item continuam abertas;
3. habilitar secret scanning e dependency review no GitHub, respeitando o princípio de menor privilégio;
4. adicionar `pip-audit` ou ferramenta equivalente para dependências Python;
5. definir a política para exceções, vulnerabilidades sem correção e atualizações incompatíveis;
6. decidir se haverá matriz de versões Python além de 3.11 e, caso haja, testá-la no CI;
7. manter actions pinadas por SHA completo e validar o pin em cada atualização.

Os passos 4 e 5 foram **entregues em 2026-10-06**: os quatro manifests de skill têm lockfile irmão com versão exata,
artefato nomeado e hash sha256 do fechamento transitivo, gerado por `scripts/lock_dependencies.py` e verificado offline
por `scripts/validate_dependency_locks.py`, que reprova lockfile dessincronizado, versão fixada fora do especificador
declarado, entrada sem hash, entrada sem artefato ou com artefato incompatível, anotação `# via` órfã, entrada duplicada
e exceção de política sem justificativa, sem data, sem pacote, sem versão ou apontando resolução inexistente. A
integridade do digest, conferida contra o artefato, e a consulta ao banco de vulnerabilidade ficam em
`.github/workflows/dependency-audit.yml`, com gatilho agendado e manual, e reportam `UNKNOWN` quando não conseguem
verificar, em vez de tratar ausência de verificação como verificação de ausência. O lockfile é resolvido em um contexto registrado no próprio cabeçalho, e outra versão de Python escolhe outra
distribuição, com outro digest: adotar matriz de versões, passo 6, exigiria um lockfile por versão de Python, e essa
é a decisão que o passo 6 precisa enfrentar. O passo 1 continua sendo decisão do proprietário, e o passo 3 depende de
configuração do repositório no GitHub.

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

**Entregue em 2026-10-06** para o recorte de limite de tamanho: `config/context-budget.json` e `scripts/validate_context_budget.py` passaram a aplicar orçamento de contexto medido em bytes por arquivo e caracteres por linha a todo `SKILL.md` e a toda referência, substituindo a regra de 500 linhas que nenhum validador aplicava. Cinco exceções registram a medição exata dos arquivos que excedem o padrão hoje, e a lista só pode encolher. O lint de navegabilidade — headings, bloco `Quando ler este arquivo` e âncoras locais — continua aberto e pode ser absorvido por esse validador ou por um próprio. Requisito `SKSYS-022`.

**Entregue em 2026-10-06** para o recorte de navegabilidade: `config/reference-index.json` declara o limiar em bytes — e não em linhas, pela mesma razão do orçamento de contexto — e `scripts/validate_reference_indexes.py` exige que toda referência acima do limiar declare quando deve ser lida e exponha um índice cujas âncoras resolvem e cujas entradas cobrem todas as seções. As doze referências acima de 8 KB receberam bloco de carregamento condicional e índice com âncoras, e as duas que já tinham índice passaram a ter âncoras resolvíveis. O teto de referência do orçamento subiu de 16 KiB para 17 KiB para comportar o bloco exigido, de modo que a política de navegabilidade não seja penalizada pelo orçamento. Requisito `SKSYS-024`.

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

### V030-007 — Genericidade de assets permanentes

O validador de genericidade existe desde a primeira versão com duas regras, e nunca era executado sobre o catálogo: a única invocação era um teste da própria skill sobre um diretório temporário. O alcance era menor que a invariante que o repositório declara.

**Entregue em 2026-10-06**: `entregar-issue/scripts/validate_skill_genericity.py` passa a bloquear caminho absoluto de host, identificador concreto em prosa Markdown fora de exemplo delimitado e host externo concreto que não seja domínio reservado de exemplo ou host genérico declarado, além das duas regras preexistentes, e o CI passa a executar o validador sobre a raiz do catálogo. Requisito `SKSYS-023`.

Permanece registrado um resíduo de proveniência: vinte schemas declaram `$id` em host reservado de exemplo cujo rótulo carrega o nome do produto de origem. O host é reservado por construção e portanto permitido pela regra, mas alterar a identidade de contratos versionados é mudança de compatibilidade e pertence a `V030-005`.

### V030-008 — Governança do registro de auditores confiáveis

A independência de auditoria tem dois tipos de controle, e eles não têm a mesma força. O que é imposto por código é o contexto separado, a leitura somente e a rederivação com parser próprio. O que fecha o ciclo é um controle externo e operacional: o registro de auditores confiáveis consumido por `validate_external_audit_report.py`, cuja validade depende de quem custodia a chave. Esse registro não existe no repositório, e isso é correto, mas o procedimento que o mantém não estava declarado em nenhum lugar.

**Entregue em 2026-10-06**: `docs/SECURITY.md` passa a declarar custódia, separação entre produtor e aprovador, procedimento de geração e custódia de chave, rotação, revogação e a limitação de operador único, que é registrada em vez de presumida. `auditar-issue/scripts/build_trusted_auditor_entry.py` monta a entrada do registro derivando `public_key_sha256` dos bytes publicados, recusa arquivo com chave privada, recusa chave que não seja Ed25519 e valida a própria saída contra o esquema. Requisito `SKSYS-025`.

Fica aberto: distribuir o `.github/CODEOWNERS` entre produtor e aprovador quando houver uma segunda pessoa. Enquanto houver um único proprietário, a separação é regra de contrato e está declarada como limitação.

A seção do procedimento é comparada com a forma canônica declarada em `tests/test_auditor_registry_policy.py`, e não reconhecida por marcadores. A comparação normaliza apenas o que o Markdown ignora — espaço à direita e linha vazia sobrando — e o documento precisa ser Markdown renderizável: recuo que tira o heading da renderização, contexto inerte, HTML bruto, escape de Markdown, caractere de controle e separador que o Markdown não reconhece reprovam.

Rodadas sucessivas de auditoria independente reprovaram versões anteriores da checagem, cada uma explorando uma forma de conter a política sem exibi-la: remoção de cláusula, relocação, comentário, cerca de código, sufixo contraditório, envoltório externo, HTML bruto, escape de crase, separador que o Markdown não reconhece e recuo no heading. A lista de formas recusadas é a soma dessas rodadas, não a prova de que a enumeração terminou, e a redação do item evita afirmar fechamento.

A contrapartida está declarada em `AGENTS.md`: alterar a seção exige alterar a forma canônica no mesmo commit, e esse diff exige auditoria independente contra a issue, porque o teste prova deliberação e não preservação dos requisitos.

### V030-009 — Análise estática real do código
Entregue o gate `scripts/validate_lint.py` com a política `config/lint-policy.json`: cada família de regras do Ruff
aparece exatamente uma vez como aplicada, aplicada em parte com a parte desligada declarada, ou dispensada com motivo
escrito; a cobertura é conferida no nível da regra, de modo que família aplicada com seleção estreita, família
parcial que não decide sobre alguma regra e família parcial que desliga tudo reprovam; a seleção efetiva é derivada
da política, nunca embutida no código; a versão da ferramenta é fixada no manifest e no lockfile e declarada na
política, com reprovação por divergência; supressão em linha ou de arquivo só é aceita com código permitido e
justificativa na própria diretiva, e diretiva de arquivo sem código é recusada; o escopo varrido é declarado na
política, e arquivo coberto fora da raiz, diretório ilegível e saída inesperada da ferramenta reprovam em vez de
reduzir o conjunto analisado em silêncio; e o gate roda sem rede e sem cache. A árvore foi corrigida até
passar limpo em 216 arquivos: import morto, variável não usada, nome de laço reatribuído, exceção sem encadeamento,
caminho via `os`, fuso ambíguo, alias de flag de expressão regular, `subprocess` sem `check`, ordenação de import,
`stdout`/`stderr` explícitos e compreensões desnecessárias.
Critério de aceite: `python3 scripts/validate_lint.py --root .` aprova a árvore entregue; reprova arquivo novo que
viole família aplicada, política que não cubra o catalogo, família que não decida sobre alguma de suas regras,
dispensa sem motivo escrito, versão divergente, supressão com código fora da lista permitida, supressão sem
justificativa e diretiva de arquivo sem código; a suíte completa continua aprovada sem mudança de comportamento
observável; a sequência de validação é idêntica em CI, `README.md` e `AGENTS.md`, com o gate na mesma posição,
verificado por `tests/test_validation_parity.py`, e o CI acrescenta apenas os passos de empacotamento e de replay de
avaliações, que não são validação; e o requisito global, o changelog e este roadmap registram a entrega.
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
- [x] referências longas possuem bloco de carregamento condicional e índice com âncoras resolvíveis, verificado pelo lint de navegabilidade;
- [x] o registro de auditores confiáveis tem custódia, separação entre produtor e aprovador e limitação de operador único declaradas, com a entrada verificável por script;
- [x] assets permanentes rejeitam acoplamento concreto a issue, host, caminho ou identificador de domínio, e o validador é executado sobre o catálogo;
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
