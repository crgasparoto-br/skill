---
name: revisar-issue
description: Revisar, normalizar e reescrever issues do GitHub como especificacoes claras, testaveis e prontas para implementacao, inclusive revisao de issue especifica ou em lote, melhoria de criterios de aceite e reconciliacao com README/docs/arquitetura/ADR/API/runbooks quando houver conflito ou duplicidade de fonte canonica. Sob `entregar-issue`, executar somente quando o readiness gate falhar, corrigir apenas pontos bloqueantes, reutilizar fontes e registro documental, versionar mudancas materiais e retornar resultado estruturado; nao implementar codigo nem criar entrega paralela.
---

# Revisar Issue

## Objetivo

Corrigir lacunas que possam levar implementadores a decisoes materialmente diferentes. Preservar intencao de produto, tornar requisitos observaveis e manter issue e documentacao versionada coerentes sem reescrever por estilo.

## Modos

- `standalone-review`: revisar uma issue especifica e, quando autorizado, atualizar issue e documentacao relacionada.
- `standalone-batch-review`: revisar issues abertas em lote, uma a uma, normalizando terminologia, referencias canonicas e ownership documental.
- `orchestrated-readiness-remediation`: corrigir somente lacunas bloqueantes recebidas de `entregar-issue`.

No modo standalone, ler `references/github-review-governance.md`. No modo orquestrado, ler `references/delivery-contract.md`. Ler `references/invariant-taxonomy.md` quando houver requisito negativo, reutilizacao, fonte canonica, precedencia, fallback ou dependencia proibida. Ler `references/specification-standard.md` para estruturar ou validar a especificacao final.

## Fast gate

Retornar `not-applicable` quando houver apenas preferencia editorial, formatacao ou melhoria opcional. Prosseguir somente quando faltar decisao, criterio, limite de escopo, fonte de verdade ou comportamento verificavel que possa alterar implementacao ou aceite.

## Descoberta standalone

1. Ler titulo, corpo e comentarios materialmente relevantes da issue.
2. Ler somente a documentacao do repositorio necessaria para entender comportamento, arquitetura, API, dados, operacao ou convencoes afetadas.
3. Identificar fontes canonicas existentes antes de criar nova definicao.
4. Classificar cada afirmacao material como `issue_specific`, `durable_rule`, `implementation_detail` ou `open_decision`.
5. Detectar drift documental: duplicidade, contradicao, definicao obsoleta, duas fontes aparentes de verdade ou regra duravel indevidamente mantida apenas na issue.
6. Em lote, revisar cada issue independentemente e somente depois normalizar terminologia e referencias compartilhadas.

## Entradas orquestradas

Consumir lacunas, snapshot preliminar, fontes, versao e `documentation-impact.json`. Nao reler toda a issue ou documentacao quando as fontes recebidas cobrem a lacuna. Ampliar descoberta somente quando uma pergunta bloqueante depender de fonte ausente.

## Fluxo

1. Mapear cada lacuna a requisito, fonte e decisao necessaria.
2. Separar requisito, premissa, pergunta aberta e fora de escopo. Classificar invariantes em `must_behave`, `must_not_behave`, `must_reuse`, `must_be_single_source`, `must_not_depend_on`, `precedence_invariants` e `forbidden_implementation` quando aplicavel.
3. Produzir a menor revisao que torne o contrato implementavel. No modo orquestrado, usar patch minimo nas secoes afetadas; no standalone, permitir reestruturacao mais ampla quando a issue ainda nao estiver implementation-ready.
4. Manter regra duravel em uma unica fonte canonica quando o repositorio sustentar essa ownership; na issue, registrar delta de entrega, restricoes, criterios de aceite e referencia exata para a fonte.
5. Quando issue e documentacao conflitarem sem evidencia suficiente para decidir precedencia, nao inventar regra: registrar pergunta aberta e marcar readiness apropriado.
6. Carregar `fluxos-conversacionais` em `specification` somente quando houver continuidade real entre mensagens, callbacks, filas ou eventos posteriores.
7. Nao inventar arquitetura, API, dados, regra de negocio ou precedencia documental.
8. Validar criterios observaveis e consistencia com fontes canonicas. Para cada invariante estrutural, registrar uma implementacao plausivel errada que ainda passaria no caminho feliz e o controle que a distinguiria.
9. Atualizar GitHub somente quando autorizado e houver mudanca material. No standalone, reconciliar documentacao e abrir/atualizar branch, commit ou PR somente conforme `references/github-review-governance.md`; nunca implementar codigo-fonte como efeito colateral da revisao.
10. Incrementar `specification_version` e invalidar snapshot anterior somente quando o contrato mudar. Sob composicao, manter `changed_files=[]` para arquivos do candidato e deixar `entregar-issue` invalidar `contract` e descendentes pelo novo snapshot.

## Eficiencia

- Agrupar lacunas da mesma causa em uma unica revisao.
- Nao criar secoes vazias nem repetir regra duravel ja referenciada por caminho canonico.
- Nao executar nova revisao quando fontes, lacunas e versao tiverem o mesmo fingerprint.
- Retornar perguntas abertas em vez de expandir escopo por suposicao.
- Em lote, evitar reescrever issues que ja estejam implementation-ready apenas para padronizar estilo.

## Entrega

No standalone, reportar readiness, alteracoes da issue, fontes canonicas consultadas, documentacao atualizada ou pendente, ambiguidades restantes e artefatos GitHub criados quando autorizados. Se a issue for claramente epic, aplicar `epic` somente quando escrita GitHub estiver autorizada e o repositorio suportar esse label.

No modo orquestrado, retornar readiness, versoes, lacunas corrigidas, perguntas abertas, fontes alteradas, requisitos afetados, impacto documental, `invalidates_previous_snapshot` e inventario de invariantes estruturais quando aplicavel. Usar `specification-gap` ou `blocked` quando decisao material permanecer ausente. Nao criar branch, implementar, fechar issue ou alterar PR nesse modo.

## Composicao versionada

No modo orquestrado, aplicar `references/delivery-contract.md` como unica fonte do envelope, reutilizacao e versao. Toda execucao nova deve emitir `input_fingerprint` e `reused=false`; qualquer no-op deve incluir `skip_reason`. Nao duplicar plano, estado, ciclo, identidade global ou delegacao.
