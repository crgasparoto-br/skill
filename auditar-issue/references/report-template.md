# RESULTADO: [APROVADA | APROVADA COM RESSALVAS | APROVADA INTERNAMENTE | INCONCLUSIVA | REPROVADA]

> **Conclusao:** `[APROVADA | APROVADA COM RESSALVAS | APROVADA INTERNAMENTE | INCONCLUSIVA | REPROVADA]` — achados bloqueantes: `[n]` — recomendacoes opcionais: `[n]`
> **Motivo determinante:** [uma frase objetiva com o requisito bloqueador, a ressalva demonstrada ou a evidencia que sustenta a aprovacao]
> **Libera merge/release:** [SIM | NAO]

**Validade:** [Independente | Controller-adversarial | Pre-auditoria]
**Triagem:** bloqueadores comprovados: `[n]` | riscos inferidos: `[n]` | limitacoes do auditor: `[n]`

**Rejection ID:** `[audit-rejection:...]` — incluir somente em auditoria `Independente` com `RESULTADO: REPROVADA`; reutilizar exatamente o mesmo ID no resultado estruturado e no `external-audit.json` quando existir.

# Auditoria da implementacao — [issue/titulo]

## Quando ler este arquivo

Ler quando for produzir o parecer, para usar a forma canônica do relatório e a matriz de requisitos.

## Índice

- [Motivo determinante](#motivo-determinante)
- [Validade da execucao](#validade-da-execucao)
- [Resumo executivo](#resumo-executivo)
- [Escopo auditado](#escopo-auditado)
- [Estado dos gates e alcance de testes](#estado-dos-gates-e-alcance-de-testes)
- [Matriz de requisitos](#matriz-de-requisitos)
- [Achados bloqueantes](#achados-bloqueantes)
- [Riscos inferidos nao confirmados](#riscos-inferidos-nao-confirmados)
- [Limitacoes exclusivas do auditor](#limitacoes-exclusivas-do-auditor)
- [Retificacao do parecer](#retificacao-do-parecer)
- [Recomendacoes opcionais](#recomendacoes-opcionais)
- [Testes e validações](#testes-e-validações)
- [Fronteira pública, privacidade e autorização](#fronteira-pública-privacidade-e-autorização)
- [Auditoria documental](#auditoria-documental)
- [Auditoria de interface](#auditoria-de-interface)
- [Regressões e riscos](#regressões-e-riscos)
- [Pendências objetivas](#pendências-objetivas)
- [Proxima acao disponivel](#proxima-acao-disponivel)
- [Proposta de issues corretivas](#proposta-de-issues-corretivas)
- [Artefato de auditoria externa](#artefato-de-auditoria-externa)
- [Artefatos controller v3](#artefatos-controller-v3)
- [Audit escape](#audit-escape)
- [Resultado inconclusivo por runtime](#resultado-inconclusivo-por-runtime)

## Motivo determinante

[Explicar em um paragrafo o motivo determinante do resultado, mencionando requisitos bloqueadores, ressalvas ou a evidencia que sustenta a aprovacao.]

## Validade da execucao

- justificativa da independencia: [...]
- procedencia verificavel do contexto separado: [...]
- relacao com o contexto de implementacao: [nenhuma | explicar por que nao e independente]
- SHA congelado: `[...]`
- SHA confirmado no encerramento: `[...]`
- SHA da base antes/depois: `[...]` / `[...]`
- merge preview antes/depois: `[...]` / `[...]`

### Triagem do resultado

Preencher as tres contagens da linha **Triagem** antes de decidir o veredito. `bloqueadores comprovados` e exatamente o total do bloco de conclusao, sempre respaldado por evidencia do candidato/entrega (analise estatica conclusiva pode servir como prova; hipotese sem prova discriminante nao serve). `riscos inferidos` representa suspeitas nao confirmadas, fora da contagem de blockers. `limitacoes do auditor` registra incapacidade exclusiva do runtime/conector para executar um gate obrigatorio, sem encontrar defeito na entrega.

Rejeitar secao vazia, placeholder e prova generica. Exigir IDs unicos e fonte verificavel. Contar A-*, RISK-* e LIM-* visiveis apenas nas secoes canonicas, mesmo com contagem zero. ATX (recuo 0-3, tab, `#` final): H1 fecha H2. IDs em listas/citacoes (inclusive apos linha vazia) invalidos; fences sao inertes so dentro do container ativo, assim como comentarios HTML e codigo recuado 4. Prova: `arquivo:linha`, URL, SHA, CI run numerado ou comando com alvo e resultado; `pytest` isolado nao basta. Preservar o gate independente de completude.

A precedencia e: bloqueador comprovado > limitacao do auditor. Com ambos, `REPROVADA`, limitacao registrada e merge bloqueado; sem bloqueador e com limitacao obrigatoria, `INCONCLUSIVA`; aprovacao exige zero bloqueadores e zero limitacoes materiais. Nunca marcar ausencia de Git Bundle/DNS como falha de produto. Em toda retificacao do parecer, atualizar o artefato integral e repetir `validate_verdict_header.py` antes da mensagem; nunca substituir apenas a conclusao verbal.

### Regras do cabecalho

A primeira linha continua sendo o titulo do resultado. Imediatamente abaixo dele vem o bloco de conclusao em destaque, que repete o veredito e o resume, antes de qualquer outro metadado. Ele nao substitui o motivo determinante, os achados nem a matriz: resume o veredito, a contagem de achados bloqueantes e recomendacoes, o motivo em uma frase e a liberacao de merge/release. Manter o bloco consistente com o corpo do relatorio; divergencia entre o bloco e o corpo e defeito do proprio relatorio. Em `INCONCLUSIVA` por runtime, declarar no bloco que nao ha defeito funcional atribuido ao candidato. A triagem e obrigatoria mesmo com todos os contadores em zero.

- `APROVADA`: apenas auditoria independente com portao de release satisfeito.
- `APROVADA COM RESSALVAS`: apenas auditoria independente, sem bloqueio, com ressalva material nao bloqueante.
- `APROVADA INTERNAMENTE`: controller-adversarial ou pre-auditoria favoravel; `Libera merge/release: NAO`.
- `INCONCLUSIVA`: limitacao do runtime/ferramenta/connector da auditoria impede prova obrigatoria sem evidencia de falha do candidato; `Libera merge/release: NAO`; nao gerar finding da issue para essa causa.
- `REPROVADA`: finding bloqueante, gate material falho/ausente por responsabilidade do candidato/entrega, identidade invalida ou handoff materialmente inconsistente.

## Resumo executivo

- requisitos obrigatórios: [quantidade]
- implementados: [quantidade]
- parciais: [quantidade]
- não implementados: [quantidade]
- incorretos: [quantidade]
- não verificáveis: [quantidade]
- achados bloqueantes abertos: [quantidade]
- recomendacoes opcionais: [quantidade]

[Resumir o que foi entregue e as principais lacunas. Não usar o percentual como substituto do parecer.]

## Escopo auditado

- repositório: `[owner/repo]`
- issue principal: `[#n]`
- subissues: `[#n, #n]`
- branch/PR: `[identificação]`
- commit auditado: `[sha]`
- validade da execução: `[independente | pré-auditoria]`
- base de comparação: `[branch/sha]`
- base remota antes/depois: `[sha]` / `[sha]`
- merge preview antes/depois: `[sha]` / `[sha]`
- documentos consultados: `[lista]`
- impacto documental declarado: `[arquivos ou sem impacto com justificativa]`
- registro documental recebido: `[identificação/estado, tratado como alegação]`
- limitações: `[nenhuma ou lista objetiva; usar audit-runtime-limitation quando externa ao candidato]`

## Estado dos gates e alcance de testes

Preencher quando houver CI/status remoto relevante, suite abortada ou `blocker-bounded`.

| Gate/teste ou familia | Estado do gate | declared | reached | passed | Origem/observacao |
|---|---|---:|---:|---:|---|
| `...` | green/red-candidate-caused/red-inherited-or-infra/not-reached/missing/unknown | sim/nao | sim/nao | sim/nao | ... |

### Cobertura e saturacao adversarial

Registrar a colheita proporcional antes de afirmar que os blockers conhecidos
representam as lacunas materiais da entrega. Um parecer reprovado tambem exige
transparencia sobre o que foi e nao foi investigado; nao limitar o resultado a
dois findings nem inflar a contagem por variacoes da mesma causa raiz.

| Requisito | Familia / superficie | Dimensoes adversariais | Status | Evidencia e limites |
|---|---|---|---|---|
| `R-...` | `...` | `origem / escopo / transformacao / consumidor` ou dominio equivalente | `covered / not-applicable / not-executed` | `SHA, procedimento, esperado, observado, evidencia` ou justificativa |

- Cobertura declarada: `[abrangente | limitada]`, com motivo e superficies em aberto.
- Variantes consolidadas por causa raiz: `[IDs + dimensoes]`.
- Superficies remanescentes e riscos residuais: `[lista; vazio somente se confirmado]`.
- Provas caras omitidas apos blocker: `[procedimento + justificativa]`.
- Em reauditoria com preflight deterministico ainda aberto: classificar
  `preflight-bounded` sem alegar que a matriz ampla foi reexecutada.

- `blocker_bounded`: `[true|false]`
- provas caras puladas: `[lista + skip_reason]`
- evidencias verdes reutilizadas: `[run/job + escopo comprovado]`

Nao marcar teste posterior ao primeiro abort como executado. Nao extrapolar job verde alem do harness/cenario que ele realmente exercitou.

## Matriz de requisitos

| ID | Origem | Requisito atômico | Evidência | Status | Severidade/observação |
|---|---|---|---|---|---|
| REQ-001 | issue | ... | `arquivo:linhas`, teste ou comportamento | Implementado | ... |

Usar uma linha por requisito. Não combinar requisitos diferentes para aparentar cobertura.

## Achados bloqueantes

Incluir apenas observacoes com `disposition=blocking`.

### [ALTO] A-001 — [titulo objetivo do achado comprovado]

- **Requisitos afetados:** REQ-...
- **Origem comprovada:** candidato
- **Evidência:** arquivo:linha, URL, commit ou comando, com observacao reproduzivel
- **Categoria de escape:** `execution-state-gap | control-propagation-gap | capability-operation-drift | adapter-support-drift | silent-translation-loss | legacy-variant-gap | documentation-claim-drift | other`
- **Portão requerido:** `F28` a `F33` quando aplicável
- **Caso literal:** ...
- **Casos irmãos:** pelo menos dois cenários de famílias ou superfícies distintas
- **Solicitado:** ...
- **Encontrado:** ...
- **Impacto:** ...
- **Lacuna a corrigir:** ...

Repetir por achado, em ordem decrescente de severidade.


## Riscos inferidos nao confirmados

Cada risco contabilizado exige um item separado com ID RISK-001, sem ser convertido em bloqueador:

### RISK-001 — [titulo do risco inferido]

- **Cenário hipotético:** [condicao e resultado possivel]
- **Base da inferência:** [fonte ou trecho que sustenta suspeita e limite da prova]
- **Grau de certeza:** baixo
- **Prova discriminante pendente:** [experimento concreto para confirmar ou afastar]

Nao incluir meras sugestoes sem impacto no contrato.

## Limitacoes exclusivas do auditor

Cada limitacao contabilizada exige um item separado com ID LIM-001, sem virar finding da issue:

### LIM-001 — [titulo da limitacao exclusiva do auditor]

- **Recurso indisponível:** [recurso de runtime/connector]
- **Gate obrigatório afetado:** [nome e obrigacao nao coberta]
- **Tentativas e fallbacks:** [passos de recuperacao, inclusive bundle CI quando aplicavel]
- **Prova indisponível:** [evidencia obrigatoria que nao foi obtida]

Nao propor alteracao no candidato para corrigir o ambiente do auditor.

## Retificacao do parecer

Qualquer edicao do parecer (inclusive titulo, texto livre e motivo) exige `--revision --previous <anterior>`, registro de retificacao e comparacao integral. O modo inicial isolado nao detecta historico. Para cada ID alterado/removido exigir prova contextual, preservando historico e SHA.

- **Veredito anterior:** [veredito original]
- **Veredito atual:** [veredito novo]
- **Motivo da retificacao:** [razao especifica]
- **Nova evidencia:** [origem, procedimento e observacao]
- **HEAD auditado:** [SHA Git completo]
- **Prova de reclassificacao A-001:** [fonte e prova se A-001 mudou ou foi removido]

## Recomendacoes opcionais

Listar recomendacoes com ID estavel, `actionable=true|false` e `remediation_mode=targeted-remediation|systemic-remediation`. Recomendacao `actionable=false` nao amplia o contrato. Quando `actionable=true` e a entrega entrar em remediacao dessa auditoria, `entregar-issue` deve fecha-la no ledger 1:1 antes do novo handoff.

## Testes e validações

| Comando/cenário | Resultado | Evidência/observação |
|---|---|---|
| `comando` | passou/falhou/não executado | ... |

Listar também testes relevantes que deveriam existir, mas não existem.

## Fronteira pública, privacidade e autorização

Preencher quando houver requisito de não revelação, autorização, elegibilidade ou isolamento.

- **Procedures/endpoints auditados:** [...]
- **Payload público observado:** [...]
- **Erro público observado:** [...]
- **Casos discriminantes:** [existente, inexistente, inelegível, outro tenant, vínculo prévio...]
- **Dados protegidos ausentes da resposta:** [...]
- **Entitlement/recurso exato do destino:** [...]
- **Negação versus falha temporária:** [...]
- **Testes diretos na fronteira:** [...]
- **Achados:** [...]

## Auditoria documental

- **Parecer documental:** [Aprovada | Reprovada | Não verificável]
- **Fontes canônicas avaliadas:** [...]
- **Fontes canônicas presentes no diff e atualizadas, ou justificativa de ausência de impacto:** [...]
- **Comparação com o registro declarado pela implementação:** [...]
- **Verificação independente realizada:** [...]
- **Regras estáveis sem fonte versionada:** [nenhuma | listar]
- **Validações:** [...]
- **Divergências e achados:** [...]

Relacionar cada achado documental aos requisitos e à severidade no relatório principal.

## Auditoria de interface

Preencher quando houver impacto visual.

- **Parecer visual:** [Aprovada | Reprovada | Não verificável]
- **Rotas e cenários:** [...]
- **Viewports:** [...]
- **Evidências:** [screenshots, execução e passos reproduzíveis]
- **Achados materiais:** [...]
- **Limitações:** [...]

Relacionar cada achado visual aos requisitos e à severidade no relatório principal.

## Regressões e riscos

[Descrever regressões confirmadas, riscos plausíveis sustentados por evidência e áreas não verificadas. Separar fato de risco inferido.]

## Pendências objetivas

1. [ação necessária vinculada ao requisito e ao achado]
2. ...

## Proxima acao disponivel

Incluir esta secao somente quando `RESULTADO: REPROVADA` e houver remediacao executavel. O auditor nao implementa nem altera o candidato; a continuidade apenas reaproveita os findings estruturados e deve preservar o controlador de origem.

- `delivery_origin=direct-entregar-issue`: **Implementar pendencias:** `@Entregar Issue implementar pendencias desta auditoria`
- `delivery_origin=standalone-unknown`: omitir comando de continuidade; entregar somente os findings.

Para `delivery-not-ready`, `delivery-not-saturated` ou `remediation-incomplete`, aplicar a mesma regra por origem. No fluxo direto, `entregar-issue` seleciona `handoff-only`, `post-write-refreeze`, `fresh-handoff-required`, remediacao de saturacao ou work items conforme a identidade/findings. Quando o material SHA direto ja possuir CI exact-SHA terminal verde e faltar apenas fechamento/handoff, o resultado estruturado deve preferir `next_phase=finalize-after-ci`, evitando nova discovery, implementacao ou rodada de `corrigir-ci` para o mesmo material. Omitir toda esta secao em `APROVADA`, `APROVADA COM RESSALVAS`, `APROVADA INTERNAMENTE` e `INCONCLUSIVA`, inclusive quando houver apenas `audit-runtime-limitation`.

## Proposta de issues corretivas

### [Título sugerido]

**Objetivo:** ...

**Requisitos afetados:** REQ-...

**Critérios de aceite:**

- ...
- ...

**Evidência da lacuna:** ...

Não criar as issues sem autorização expressa.


## Artefato de auditoria externa

Quando a execucao for independente e houver chave previamente confiada:

- arquivo: `external-audit.json`;
- schema: `schemas/external-audit.schema.json`, versao 3;
- report ID: `[uuid]`;
- audit context ID e issuer: `[...]`;
- key ID: `[...]`;
- SHA-256 do arquivo assinado: `[...]`;
- validacao: `validate_external_audit_report.py ...` `[PASS|FAIL]`;
- custodia da chave privada fora do contexto de implementacao: `[confirmada|nao demonstravel]`.

Se a custodia ou o contexto separado nao puderem ser demonstrados, nao assinar e nao apresentar o arquivo como aprovacao importavel.

## Artefatos controller v3

Quando em `controller-adversarial`, acrescentar:

- `source-manifest.json`: caminho e SHA-256;
- `requirements-rederivation.json`: caminho e SHA-256;
- `coverage-matrix.json`: caminho e SHA-256;
- `controller-audit-report.json`: caminho, SHA-256 e resultado de `validate_controller_audit_result.py`.

A matriz de requisitos deve registrar separadamente evidencia positiva, IDs de controles negativos, `negative_control_evidence` estruturada e regressao. Nao resumir esses campos em uma unica coluna generica nem aceitar nome de teste sem artefato hasheado.

## Audit escape

Incluir secao explicita quando uma auditoria independente refutar aprovacao interna previa do mesmo SHA: SHA e hash do relatorio interno anterior, findings escapados, motivo da falha dos gates internos, Skill governante a revisar e controle adversarial reutilizavel requerido.


## Resultado inconclusivo por runtime

Quando o resultado for `INCONCLUSIVA` por `audit-runtime-limitation`:

- nao listar a limitacao em **Achados bloqueantes**;
- declarar explicitamente que nao foi identificado defeito funcional novo por essa causa;
- registrar `blocker_bounded=false`;
- listar em **Pendencias objetivas** apenas a acao de infraestrutura da auditoria, nunca mudanca no repositorio;
- no resultado estruturado usar `status=blocked`, `findings=[]` para a causa de runtime, `limitations` com categoria `audit-runtime-limitation` e `requires_refreeze=false` se a identidade estiver estavel.
