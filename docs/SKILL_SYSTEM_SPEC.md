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

`entregar-issue` permanece proprietário dos contratos compartilhados. Cópias em outras skills devem ser sincronizadas da fonte canônica; não editar uma cópia gerada isoladamente.

### 4.10 Observabilidade sem fabricação

Contadores e métricas devem distinguir:

- zero comprovado;
- valor conhecido;
- valor parcial;
- valor desconhecido.

Não preencher ausência de telemetria com zero. Identidades de tentativa, execução e evidência devem permanecer separadas quando representarem conceitos diferentes.

## 5. Contexto e carregamento progressivo

O `SKILL.md` deve permanecer como control plane compacto da skill. Referências, schemas, contratos e scripts são carregados somente quando necessários ao passo corrente. Se uma referência for necessária para decidir um gate, sua ausência é falha de evidência, não autorização para ignorar o gate.

## 9. Catálogo machine-readable

`config/skills-catalog.json` é a fonte única para a lista pública de skills, finalidade, entradas, modos, gatilhos, autoridade e capacidades exigidas. O README contém uma projeção gerada delimitada por marcadores; execute `scripts/build_catalog_docs.py --check` para detectar drift.

`scripts/select_skill.py` produz uma shortlist explicável. Empate material ou ausência de gatilho retorna `UNKNOWN`; o roteador não substitui o julgamento semântico nem autoriza uma skill a executar uma ação que suas capacidades não suportem.

`config/capabilities.json` define, para cada capacidade exigida, o estado quando ela estiver ausente e o fallback permitido. Ausência de escrita, execução, identidade imutável ou leitura remota nunca pode ser promovida a sucesso.

## 10. Modelo de requisitos

`config/skill-system-requirements.json` registra requisitos globais com IDs estáveis, estado, referências de implementação e referências de validação. Alterações que introduzam uma nova invariante global devem preferir estender esse registro e os contratos existentes antes de duplicar regras em múltiplos `SKILL.md`.

## 11. Manifesto de capacidades

`.github/skill-system-capabilities.json` descreve capacidades globais ativas do catálogo. O manifesto é declarativo e deve refletir comportamento realmente implementado. Uma capacidade não pode ser marcada como habilitada apenas porque está planejada.

## 12. Segurança e autoridade

`docs/SECURITY.md` é a fonte transversal para limites de escrita, independência, credenciais, efeitos destrutivos e merge. Contratos específicos podem ser mais restritivos, nunca mais permissivos sem alteração explícita desta especificação.

## 13. Validação

`python scripts/validate_repository.py` deve falhar quando:

- um artefato global obrigatório estiver ausente ou inválido;
- a versão do sistema divergir entre os artefatos globais;
- uma capacidade obrigatória estiver desabilitada sem mudança normativa;
- requisitos declararem referências inexistentes quando a referência for local;
- ownership canônico divergir;
- uma skill obrigatória perder `SKILL.md`, contratos, referências, schemas ou testes;
- o catálogo divergir dos metadados das skills;
- uma cópia de contrato divergir do hash canônico;
- links Markdown locais ou referências de skills deixarem de resolver.

Novas invariantes globais devem incluir validação automatizada proporcional ao risco.
