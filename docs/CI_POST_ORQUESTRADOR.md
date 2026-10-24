# Contrato canônico de CI independente do Orquestrador

**Status:** padrão normativo para migração gradual dos repositórios consumidores.  
**Origem:** [skill#66](https://github.com/crgasparoto-br/skill/issues/66).  
**Aplicação:** [SolverFin#704](https://github.com/crgasparoto-br/SolverFin/issues/704), [controle_calorias#1317](https://github.com/crgasparoto-br/controle_calorias/issues/1317), [training-system#499](https://github.com/crgasparoto-br/training-system/issues/499).

O documento [CI_STANDARD.md](./CI_STANDARD.md) é o guia prático complementar. Este arquivo é a **única fonte normativa**; o guia não substitui critérios de aceite nem autoriza mudança em required checks.

## Fronteiras de responsabilidade

- O catálogo `skill` orienta agentes **fora** do GitHub Actions: `entregar-issue` prepara código, plano, evidências e PR; `corrigir-ci` lê logs e propõe/aplica correções com autorização.
- O CI pertencente a cada produto é **determinístico, local e independente**. Nenhum workflow de produto executa skills, agentes de IA, chamadas a modelos, prompts ou serviços runtime do `delivery-orchestrator`.
- A identidade de checks, a política de branch protection e os gates específicos são propriedade de cada repositório. Este documento define invariantes comuns, **não** substitui a configuração local.
- Nenhuma alteração proposta por este contrato concede merge automático. O agente não faz merge sem autorização explícita; workflows nunca fazem merge por conta própria.

## Contrato mínimo de execução

1. O workflow aceita `pull_request` e, quando adequado, `merge_group`; mantém permissões mínimas de token e protege execução de código de PR não confiável. Não usar `pull_request_target` para executar checkout de código não confiável.
2. O classificador local determina **FAST**, **STANDARD** ou **CRITICAL** a partir do diff completo base/head e de regras versionadas no próprio produto. Falha de API, diff truncado, caminho desconhecido, alteração de classificador/workflow/proteção, segredo, autorização ou migração exige **CRITICAL**, nunca FAST por omissão. Não usar apenas labels, nomes de branch ou intenção declarada.
3. **FAST** executa checks determinísticos mínimos seguros (por exemplo, lint, validação de formato e verificações afetadas); **STANDARD** adiciona suite de build/teste/integração relevante; **CRITICAL** executa todos os gates de produto, segurança, migrações, arquitetura e regressões pertinentes. O produto pode elevar, nunca reduzir, o perfil em condições sensíveis.
4. A promoção é **fail-closed**: classificações ausentes, inválidas, sem evidência ou etapas obrigatórias skipped/cancelled/timed out não geram aprovação. O gate agregador obrigatório deve rodar com condição `always()` e exigir resultado `success` de todo job aplicável; jobs intencionalmente dispensados devem ser definidos por política explícita, nunca interpretados implicitamente como aprovação.
5. Validar o **merge preview** (resultado sintético de base + head, por exemplo ref de merge do PR ou merge queue) para detectar incompatibilidade com a base. Separadamente, verificar o **exact-head SHA**: evidências e checks devem corresponder ao commit head atual, não a commit antigo, base isolada, ou ref mutável sem revalidação. Divergência entre SHA medido e SHA atual reprova ou exige novo run.
6. Gates de produto, relatórios e artefatos necessários à auditoria permanecem ativos em todos os perfis aos quais se aplicam. Alteração de nome de job não pode tornar um required check impossível de produzir; `concurrency` e cancelamento não devem produzir falsos verdes.
7. Cada repositório mantém documentação versionada para seus caminhos sensíveis, jobs, entradas/saídas do classificador, permissões, ambiente de execução, política de artefatos e dependências locais. Fixar ações por versões ou SHA conforme política de segurança local.

## Matriz de compatibilidade de checks obrigatórios

A tabela registra o **contrato de migração**, não afirma que os rulesets atuais já foram inventariados ou alterados. Antes do primeiro PR consumidor, coletar nomes reais e origem dos required contexts via API/configuração do GitHub e registrar a evidência na issue local.

| Produto | Antes (contextos/fluxos legados conhecidos) | Depois (contrato exigido) | Estratégia de compatibilidade |
| --- | --- | --- | --- |
| SolverFin | `delivery-v2-ci.yml` e classificador legados; `ci.yml`; `statement-visual-validation.yml` | CI local neutro + Prisma/PostgreSQL, integração e validação visual obrigatórios conforme política | Manter os contextos de required checks efetivamente configurados até novo gate equivalente ficar verde; transição dos nomes em duas etapas |
| controle_calorias | `agent-check.yml`, `delivery-v2-ci-classifier*`, variável `DELIVERY_V2_RISK_PROFILE` | CI neutro + Vitest sharding, TypeScript, build, arquitetura, documentação, TiDB, artefatos, exact-head | Publicar check substituto em paralelo; atualizar rulesets somente depois da validação e preservar checks de produto |
| training-system | `validate-pr.yml` e classificador Delivery V2 | CI neutro com auth, integração, migrações, merge preview e exact-head | **Preservar o contexto literal `Validate repository`** durante toda a migração |

**Registro obrigatório por produto, antes/depois:** exportar para a PR de migração uma tabela `required context atual | workflow/job emissor | novo context | ruleset/branch protection | evidência de sucesso no head | data de troca | rollback`. Não marcar contexto como substituído apenas porque o workflow foi renomeado. Checks de GitHub Actions são identificados pelos nomes efetivamente publicados; conferir também origem do app e eventuais duplicidades.

## Pontos de extensão de cada produto

- **SolverFin:** manter `ci.yml`, suites Prisma/PostgreSQL, testes de integração e `statement-visual-validation.yml`. Migrar `delivery-v2-ci.yml` e classificador sem remover gates existentes.
- **controle_calorias:** preservar shards Vitest, verificação TypeScript, build, arquitetura, documentação, TiDB e produção de artefatos; revisar `CONTRIBUTING.md`, template da PR e consumidores reais dos bundles antes de excluí-los.
- **training-system:** preservar `Validate repository`, autenticação, integração, migrações e documentação em `docs/architecture/ci-validation.md`; paths desconhecidos/sensíveis devem escalar para CRITICAL.

## Testes de contrato (positivos e negativos)

Executar e anexar evidência ao PR de cada consumidor:

| Caso | Resultado esperado |
| --- | --- |
| Alteração documental explicitamente segura | FAST com gates mínimos aplicáveis |
| Alteração comum de aplicação | STANDARD com testes e build aplicáveis |
| Auth/segredo/migração/workflow/classificador ou path desconhecido | CRITICAL com todos os gates relevantes |
| Falha ao ler lista completa de arquivos, API indisponível ou configuração de risco inválida | CRITICAL ou bloqueio explícito, **nunca aprovação FAST** |
| Gate obrigatório falha, é ignorado inesperadamente ou é cancelado | Gate agregador reprova |
| PR muda de head enquanto check antigo ainda está verde | Reprovar/aguardar verificação do SHA novo |
| Head está verde mas merge preview falha contra a base | Reprovar |
| Contexto requerido renomeado antes da atualização de ruleset | Detectar falta de check e interromper rollout |
| Testes de produto falham no perfil correspondente | Reprovar sem fallback silencioso |
| CI tenta chamar skill/IA/endpoint do Orquestrador | Reprovar inspeção estática e remover acoplamento |

## Rollout e rollback sem janela sem proteção

1. **Inventariar:** salvar HEAD, rulesets, required status contexts, workflows e gates legados antes da alteração; registrar baseline verde e lacunas como `UNKNOWN`, não como sucesso.
2. **Implementar em branch do produto:** criar classificador local e workflow neutros lado a lado; executar testes unitários do classificador e matriz negativa. Não apagar lock, pastas `.delivery-v2` ou dependências antigas ainda usadas.
3. **Validar PR:** exigir runs verdes na versão exata do HEAD e no merge preview, todas as suites de produto e revisão dos contextos publicados; verificar comportamento com um teste negativo deliberado.
4. **Trocar regras com segurança:** garantir que o novo check esteja sendo publicado e verificado **antes** de remover o antigo do ruleset. Preferir manter o mesmo contexto obrigatório estável quando viável; uma troca de nomes deve ser coordenada com branch protection e comprovada na PR.
5. **Limpar legado:** só depois de comprovada substituição e ausência de consumidores, remover locks, `.delivery-v2`, variáveis `DELIVERY_V2_*`, referências `refs/orchestrator/*` e workflows obsoletos; revisar documentação e confirmar novo run exato.
6. **Rollback:** se um required check sumir, um gate for dispensado incorretamente ou a CI não estabilizar, reverter os commits de migração ou restaurar o workflow/classificador anterior e os required contexts previamente registrados. Revalidar o HEAD restaurado e merge preview. Nunca desabilitar proteções para destravar merge.

Para registrar as evidências em cada projeto, copiar e preencher o [template de migração e testes negativos](./CI_MIGRATION_EVIDENCE_TEMPLATE.md); campos `UNKNOWN` e `NOT RUN` não autorizam a retirada de proteções.

## Evidência de required contexts reais

A matriz acima **não é inventário do estado atual**. Em cada PR consumidora, anexar dados da API do GitHub e da branch protection/rulesets com as colunas `context atual | workflow/job emissor | app | novo context | ruleset | SHA do check | data de troca | rollback`. Valor desconhecido é `UNKNOWN`; sem inventário e evidência de sucesso no SHA atual, não remover o contexto legado.

## Configuração administrativa verificável de rulesets

Para configurar os checks de uma branch, usar o utilitário versionado
`scripts/configurar_ruleset.py` em checkout confiável do repositório. Ele exige
autenticação **GitHub CLI da pessoa administradora**, com permissão
`Administration:write`, e não recebe tokens por argumento nem os imprime.
Seu modo padrão é somente leitura; `--apply` autoriza a única escrita após
conferir identidade, branch exata, checks observados no SHA informado e
aplicativo emissor. O PUT preserva todas as demais regras, bypasses e a
exigência `strict_required_status_checks_policy=true`; após escrever,
refaz a leitura autenticada e recusa divergências.

Exemplo **somente de preflight** para a issue #119 (não é prova de
implantação nem recomendação de executar sem conferência):

```bash
python scripts/configurar_ruleset.py \
  --repo crgasparoto-br/skill --branch develop \
  --ruleset-id 24821474 \
  --sample-sha 3189dbe5f407d7eeac7fa6966bf0e6680fc8e6f6 \
  --check 'Structure and tests' \
  --check 'Offline authorization tests' \
  --check 'collect / Require certified semantic handoff (exact SHA)'
```

Antes do `--apply`, comprovar que **todas** as PRs abrangidas pelo ruleset
produzem esses mesmos contexts. A branch `main` só poderá receber um check
de auditoria/release depois que existir um emissor independente e estável,
com prova no SHA de uma PR de promoção; o script recusa apenas checks
técnicos em `main`. Nunca supor que nome de workflow seja o context do job.

Após qualquer alteração, registrar o ruleset efetivo e seus bypasses,
executar uma PR com certificação propositalmente falha (merge bloqueado)
e outra integralmente aprovada (checks obrigatórios e política de release
atendidos). O script não pode substituir essas provas nem a auditoria
independente. Em erro de configuração, restaurar os contexts anteriores
com a mesma autenticação e repetir o read-back.

## Critério de encerramento

A issue #66 estabelece **somente o padrão compartilhado**. Cada issue consumidora permanece responsável por provar implantação local, testes negativos, inventário real de checks, proteção equivalente e caminho de rollback. Não declarar os três produtos migrados sem evidências independentes nas respectivas PRs.


## Gate de auditoria independente GitHub-native

O workflow `.github/workflows/independent-audit-gate.yml` introduz o contexto
`Verify independent audit (exact SHA)` para PRs destinadas a `develop` e `main`.
Ele executa a política da **base confiável**, sem checkout de código da PR e sem
token de escrita. Não realiza a auditoria: verifica um review GitHub `APPROVED`
de revisor distinto de todos os contribuidores do diff e um contrato explícito.

O review independente precisa trazer uma linha própria:

```text
SOLVERIT_AUDIT_JSON:{"schema":"solverit-audit-v1","audit_round":"<rodada>","head_sha":"<SHA>","finding_ids":["<finding>"],"verified_finding_ids":["<finding>"],"accepted_exclusions":[]}
```

Os achados declarados precisam estar todos verificados ou explicitamente excluídos
pelo auditor independente. A completude da lista contra o manifesto verdadeiro
exige inspeção do auditor, não é demonstrada por um JSON produzido pelo executor.
O gate reprova review revogado, SHA ultrapassado, autor/committer como revisor,
bot, coleção incompleta, check com aplicativo errado e controles técnicos falhos.

Em `develop`, exige `Structure and tests`, `Offline authorization tests` e
`collect / Require certified semantic handoff (exact SHA)` no HEAD real.
Em `main`, exige os dois checks técnicos e review independente específico
da PR de promoção. O evento `pull_request_review` reexecuta o gate após o
auditor aprovar, **depois** da CI técnica ficar verde. Novo commit invalida a
aprovação anterior.

### Ativação administrativa sem janela desprotegida

Publicar o workflow na base confiável e observar o nome de check emitido pelo
GitHub Actions **antes** de registrá-lo no ruleset. Um workflow só presente
na PR candidata ainda não cria um emissor confiável em `develop`/`main`.
Depois de verificar a emissão, usar `scripts/configurar_ruleset.py` com
`--apply` somente sob uma autenticação que tenha `Administration:write`,
preservando todos os contexts já requeridos. IDs inventariados:
`24821474` (`develop`) e `24821457` (`main`). Não afirmar ativação apenas
pela existência de script, commit ou check verde.

Obrigatório validar uma PR negativa (auditoria ausente ou CI falha => merge
bloqueado) e uma positiva (aprovação independente e checks verdes => permitido).
Registrar read-back de ambos os rulesets e seus bypasses, e rollback.

O utilitário preserva qualquer check já requerido e eleva `required_approving_review_count`
de zero para **um** na regra de PR existente, sem reduzir um limite mais estrito.
Antes de aplicar, confirmar o bypass real e a identidade da integração emissora.

O `--apply` exige que cada contexto da amostra exista na integração
GitHub Actions observada, com conclusão **terminal** (`success` ou `failure`),
e que os dois arquivos do emissor independente já estejam na branch-base
confiável. A conclusão `failure` **não** é aprovação: permite instalar a
proteção fail-closed, que impedirá merges até o check ser corrigido.
`queued`, sem conclusão, `skipped` e `cancelled` não servem como
amostras válidas. Antes de ativar, o administrador deve aceitar que PRs
com check vermelho ficarão bloqueadas; não remover contextos para liberá-las.
Apenas read-back autenticado e testes negativo/positivo de merge comprovam
proteção efetiva. O modo padrão sem `--apply` continua somente leitura.
