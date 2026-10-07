# Skill System — Especificação Mestre

> **Contrato normativo do catálogo.** Este documento define a arquitetura e os invariantes globais compartilhados pelas skills deste repositório. Regras específicas continuam pertencendo ao `SKILL.md`, contratos e referências de cada skill.

## 1. Objetivo

O catálogo deve permitir que diferentes assistentes executem fluxos de engenharia de software com comportamento previsível, verificável e independente do histórico da conversa. O modelo de linguagem pode interpretar requisitos, implementar código e produzir julgamentos semânticos, mas fatos de controle, autoridade e evidência devem permanecer explícitos e verificáveis.

## 2. Hierarquia de fontes

Quando houver conflito, aplicar esta precedência:

1. `docs/SKILL_SYSTEM_SPEC.md` — arquitetura e invariantes globais do catálogo.
2. `config/skill-system-requirements.json` — projeção machine-readable dos requisitos globais, estado e evidências.
3. `config/skills-catalog.json`, `config/capabilities.json` e seus schemas — catálogo machine-readable, seleção, capacidades, fallbacks e metadados públicos.
4. `entregar-issue/contracts/*` — contratos compartilhados cujo proprietário canônico é `entregar-issue`.
5. `<skill>/SKILL.md` — comportamento normativo específico da skill.
6. `<skill>/references/*` — detalhamento carregado progressivamente.
7. `scripts/`, `tests/` e workflows — implementação executável e evidência de conformidade.
8. Issues, PRs e conversas — acompanhamento operacional; nunca substituem uma fonte canônica versionada.

Memória de conversa pode ajudar na continuidade, mas não é dependência de correção. Estado material deve ser reconstruível a partir do repositório, GitHub e artefatos explicitamente versionados.

## 3. Responsabilidades

- `entregar-issue`: controlador de entrega; possui os contratos compartilhados, coordena implementação, validação, freeze e handoff.
- `corrigir-ci`: proprietário temporário da remediação de CI; devolve controle por envelope estruturado.
- `auditar-issue`: auditor independente e somente leitura; não corrige o candidato.
- skills especializadas: atuam apenas no recorte delegado e não assumem o controle global da entrega.
- runtime/integrador: controla provider, credenciais, disponibilidade de ferramentas e limites externos; nenhuma skill amplia a própria autoridade.

## 4. Invariantes globais

### 4.1 Identidade explícita e exact-head

Evidência de CI, auditoria, medição ou fechamento aplica-se somente ao material que realmente examinou. Escrita material posterior invalida evidências descendentes que dependem do SHA anterior.

### 4.2 Fail closed

Ausência, ambiguidade ou evidência insuficiente nunca autoriza um caminho mais permissivo. Quando um controle aplicável não puder ser comprovado, representar o resultado como `UNKNOWN` ou estado bloqueante equivalente; não converter desconhecido em `PASS`, `false` ou zero.

Estados conceituais recomendados para controles:

- `PASS`
- `BLOCK`
- `UNKNOWN`
- `NOT_APPLICABLE`

### 4.3 Loops limitados

Retries, ciclos de implementação, remediação, auditoria ou substituição devem possuir limites explícitos. Esgotamento encerra ou escala; não inicia loop AI-on-AI aberto.

### 4.4 Sem autoridade implícita de merge

Nenhuma skill possui autoridade implícita para merge. Aprovação interna, auditoria favorável e readiness de release são fatos distintos de enforcement nativo de merge.

### 4.5 Independência de auditoria

Auditoria independente usa identidade e evidência do candidato, não raciocínio privado do implementador. Trocar o nome da skill dentro do mesmo contexto não prova independência.

### 4.6 Ownership exclusivo por fase

Quando uma fase transfere ownership — por exemplo, `entregar-issue -> corrigir-ci` — apenas um owner pode controlar a mesma responsabilidade para o mesmo material SHA. O retorno deve ser explícito e estruturado.

### 4.7 Fatos antes de julgamento

Usar a precedência:

```text
fatos determinísticos -> política determinística -> julgamento semântico limitado -> resultado do gate
```

Julgamento de modelo não pode sobrescrever fato incompatível.

### 4.8 Contexto suficiente

Contexto progressivo é obrigatório para eficiência, mas redução de contexto não pode remover informação material necessária a uma conclusão. Quando a omissão impedir uma decisão suportável, retornar `context-insufficient` ou equivalente em vez de inferir aprovação.

### 4.9 Contratos canônicos e cópias geradas

`entregar-issue` permanece proprietário dos contratos compartilhados. Cópias em outras skills devem ser sincronizadas da fonte canônica; não editar uma cópia gerada isoladamente. Arquivos replicados fora de `contracts/` (scripts, schemas e testes compartilhados) declaram sua fonte canônica em `config/shared-files.json` e seguem a mesma regra.

### 4.11 Sem arquivos mortos

Toda referência, script e schema de uma skill deve ser alcançável a partir do seu `SKILL.md`. Arquivo inalcançável não é carregado, diverge em silêncio e cria instruções concorrentes; deve ser religado onde se aplica ou removido. Schema que nenhum validador aplica é uma segunda fonte de verdade e segue a mesma regra.

### 4.10 Observabilidade sem fabricação

Contadores e métricas devem distinguir:

- zero comprovado;
- valor conhecido;
- valor parcial;
- valor desconhecido.

Não preencher ausência de telemetria com zero. Identidades de tentativa, execução e evidência devem permanecer separadas quando representarem conceitos diferentes.

## 5. Contexto e carregamento progressivo

O `SKILL.md` deve permanecer como control plane compacto da skill. Referências, schemas, contratos e scripts são carregados somente quando necessários ao passo corrente. Se uma referência for necessária para decidir um gate, sua ausência é falha de evidência, não autorização para ignorar o gate.

## 6. Catálogo machine-readable

`config/skills-catalog.json` é a fonte única para a lista pública de skills, finalidade, entradas, modos, gatilhos, autoridade e capacidades exigidas. O README contém uma projeção gerada delimitada por marcadores; execute `scripts/build_catalog_docs.py --check` para detectar drift.

`scripts/select_skill.py` produz uma shortlist explicável. Empate material ou ausência de gatilho retorna `UNKNOWN`; o roteador não substitui o julgamento semântico nem autoriza uma skill a executar uma ação que suas capacidades não suportem.

`config/capabilities.json` define, para cada capacidade exigida, o estado quando ela estiver ausente e o fallback permitido. Ausência de escrita, execução, identidade imutável ou leitura remota nunca pode ser promovida a sucesso.

## 7. Versionamento e compatibilidade

`VERSION` é a versão pública SemVer do conjunto de skills e adaptadores. `config/skills-catalog.json.catalog_version` e `config/skill-system-requirements.json.system_version` identificam snapshots temporais internos. `config/compatibility.json` é a fonte canônica para mapear a release pública, a versão pública do contrato, a linhagem interna e a migração de cada skill.

Uma combinação de versões não declarada no manifesto deve permanecer `UNKNOWN` ou incompatível. Tags de release devem apontar para commits imutáveis e só devem ser criadas depois do merge e da execução dos gates de release.

## 8. Adaptadores de plataforma

`config/platform-adapters.json` registra os ambientes suportados e seus arquivos de instrução. Todos os adapters usam `host-declared` e `none-assumed`: o ambiente deve declarar as capacidades reais da sessão, e o adapter nunca pode inventar acesso a Git, escrita, CI, navegador ou execução de testes.

O protocolo comum é `config/compatibility.json` → `config/skills-catalog.json` → `config/capabilities.json` → `config/platform-adapters.json` → `<skill>/SKILL.md` → referências condicionais → `schemas/contracts/scripts`. Um adapter específico pode explicar como montar contexto na plataforma, mas não pode substituir a semântica normativa do `<skill>/SKILL.md` ou ampliar autoridade.

## 8.1 Avaliações comportamentais

`evals/` contém casos versionados que medem o comportamento observável de runtimes de IA sem substituir hashes, schemas, CI ou outros gates determinísticos. Cada caso declara contexto, capacidades, resultado esperado, ações proibidas, evidências obrigatórias e orçamentos de uso.

O runner deve distinguir `PASS`, `FAIL`, `NOT_RUN` e `INVALID`. Runtime ausente, resultado inválido, métrica indisponível ou falha de infraestrutura nunca pode ser convertido em aprovação. Um resultado `PASS` exige correspondência exata ao contrato do caso e respeito aos limites declarados.

O harness é provider-agnostic. A CI valida os contratos e reproduz fixtures determinísticos; qualquer adapter de modelo deve declarar provider, modelo, adapter e métricas observadas. Avaliações comportamentais complementam, mas não substituem, a validação determinística de fatos críticos.

## 8.2 Higienização global

A higiene do diff cobre a entrega; ela não mede a árvore. O perfil de higienização global existe para
medir, sob demanda, quatro dívidas estruturais sobre o repositório inteiro — duplicação de corpo de
função, código morto em módulo e em símbolo, dependência declarada e nunca importada, e complexidade
acima do teto — e transformá-las em trabalho rastreável.

Invariantes:

- cada classe declara o que **não** vê, porque classe que reivindica completude produz confiança falsa;
- a política é a única fonte de limiar, exclusão, exceção e linha de base, limiar exigido pela classe
  precisa estar declarado, e nenhum limiar vive no código;
- achado aberto em classe controlada exige correção ou exceção declarada com justificativa escrita, e a
  justificativa precisa ter forma de texto: extensão, palavras e variedade;
- a identidade de um achado é derivada do conteúdo material — caminho, símbolo e valor medido —, e não
  do número de linha, de modo que alteração substantiva invalida a exceção antiga;
- classe medida contra linha de base não aceita exceção item a item, reprova tanto acima quanto abaixo
  da contagem declarada, e cresce apenas por entrada nova na história de linha de base, com motivo;
- exceção órfã reprova nos dois sentidos: exceção sem achado e permissão de cobertura sem arquivo;
- exclusão de caminho é declaração com motivo escrito, em caminho relativo canônico dentro da raiz, aparece
  no relatório, e diretório excluído cobre a subárvore inteira, inclusive com caminho composto; formato de texto
  conferido na busca por citação e exclusão por classe — teste, arquivo de pacote e nome de protocolo — são
  declarados na política, nunca fixos no código, e toda chave de decisão é obrigatória, sem default silencioso; a
  leitura de texto e de manifest fica contida na raiz; citação é resolvida por caminho, com nome solto aceito apenas
  quando único na árvore; e arquivo que o escopo inclui e a varredura não analisa precisa estar declarado, para que a
  cobertura não encolha em silêncio;
- a varredura é determinística e offline, o relatório é validado contra schema em memória, e a validação
  é somente leitura sobre a árvore varrida;
- o perfil relata e propõe: não implementa correção, não abre issue e não tem autoridade de merge.

## 9. Modelo de requisitos

`config/skill-system-requirements.json` registra requisitos globais com IDs estáveis, estado, referências de implementação e referências de validação. Alterações que introduzam uma nova invariante global devem preferir estender esse registro e os contratos existentes antes de duplicar regras em múltiplos `SKILL.md`.

## 10. Manifesto de capacidades

`.github/skill-system-capabilities.json` descreve capacidades globais ativas do catálogo. O manifesto é declarativo e deve refletir comportamento realmente implementado. Uma capacidade não pode ser marcada como habilitada apenas porque está planejada.

## 11. Segurança e autoridade

`docs/SECURITY.md` é a fonte transversal para limites de escrita, independência, credenciais, efeitos destrutivos e merge. Contratos específicos podem ser mais restritivos, nunca mais permissivos sem alteração explícita desta especificação.

## 12. Validação

`python scripts/validate_repository.py` deve falhar quando:

- um artefato global obrigatório estiver ausente ou inválido;
- a versão do sistema divergir entre os artefatos globais;
- uma capacidade obrigatória estiver desabilitada sem mudança normativa;
- requisitos declararem referências inexistentes quando a referência for local;
- ownership canônico divergir;
- uma skill obrigatória perder `SKILL.md`, contratos, referências, schemas ou testes;
- o catálogo divergir dos metadados das skills;
- uma cópia de contrato ou um arquivo declarado em `config/shared-files.json` divergir da fonte canônica;
- uma skill contiver referência, script ou schema inalcançável a partir do `SKILL.md`;
- links Markdown locais ou referências de skills deixarem de resolver;
- a versão pública, catalog version, system version e compatibilidade divergirem;
- uma release declarar uma migração, skill ou adapter fora do manifesto correspondente;
- um adapter não declarar arquivo de instruções ou presumir capacidades do host.

Novas invariantes globais devem incluir validação automatizada proporcional ao risco.
