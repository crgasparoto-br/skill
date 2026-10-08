# Padrão reutilizável de CI para repositórios de software

**Status:** proposta de padrão para adoção por repositórios consumidores.  
**Issue de origem:** [skill #66](https://github.com/crgasparoto-br/skill/issues/66).  
**Escopo:** validação de pull requests e branches em GitHub Actions; adaptação por stack.

## 1. Objetivo e fronteira de responsabilidades

Todo repositório deve dispor de um pipeline de integração contínua **autônomo, determinístico, reproduzível e independente de agentes de IA**. O repositório `skill` fornece instruções para agentes (`entregar-issue`, `corrigir-ci`, `auditar-issue`), **não** um serviço executado pelo CI.

| Responsável | Pode fazer | Não pode pressupor |
| --- | --- | --- |
| CI do produto | Classificar risco, instalar dependências pinadas, executar validações/testes, publicar status e artefatos | Acesso ao `skill`, ao `delivery-orchestrator`, à sessão da IA ou a tokens de LLM |
| `entregar-issue` | Preparar mudança, fazer push, observar resultado no SHA e delegar correção de CI | Que CI pendente significa sucesso; autoridade para merge |
| `corrigir-ci` | Investigar logs, corrigir regressão e revalidar o SHA publicado | Permissão para dispensar um gate a fim de ficar verde |
| `auditar-issue` | Examinar evidências em contexto independente | Substituir required checks por parecer textual |

**Invariante:** fluxo automatizado não instala nem invoca o orquestrador legado, nem uma skill como requisito runtime. Documentação e políticas do catálogo podem ser consultadas em tempo de desenvolvimento, mas não devem ser uma dependência transitória em jobs do produto.

## 2. Contrato mínimo de CI

1. **Eventos:** validar `pull_request` para branch de integração e `push` nas branches protegidas. Incluir `merge_group` caso merge queue esteja habilitada. Configurar os eventos conforme a estratégia de branch do projeto.
2. **Menor privilégio:** `permissions: contents: read` como padrão; permissões adicionais por job e justificadas. Não expor secrets a PRs externas. Fixar actions por SHA imutável, conforme política de segurança do projeto.
3. **Identidade:** registrar `base_sha`, `head_sha`, `checkout_sha`, tipo de evento e perfil de risco. Não usar como prova um resultado de commit anterior. Para PR, validar o merge resultante quando disponível; para aceitação, exigir evidência vinculada ao material atualmente candidato.
4. **Fail-closed:** entrada ausente, diff incompleto, arquivos desconhecidos, classificação inválida ou falha do classificador promovem ao perfil de maior rigor ou falham explicitamente; jamais seguem como FAST silenciosamente.
5. **Determinismo:** versões de runtime fixadas, gerenciador e lockfile verificados, banco/serviços em versões controladas, cache apenas como aceleração, sem pular teste obrigatório.
6. **Observabilidade:** nome estável dos jobs, logs concisos, resultado terminal explícito, artefatos de falha sem credenciais e identificação do SHA.
7. **Required checks:** o nome completo do check exigido pelo ruleset é interface pública; conservar o status antigo durante uma migração ou alterar o ruleset de forma coordenada e verificável. Job que muda de nome pode bloquear merge mesmo estando verde.
8. **Independência:** um CI verde não representa aprovação de auditoria independente, nem concede merge automático.

## 3. Perfis de risco

Os nomes FAST, STANDARD e CRITICAL são perfis de validação e **não** autorização para ignorar segurança.

| Perfil | Indícios de entrada | Gates mínimos |
| --- | --- | --- |
| FAST | Arquivos de documentação ou mudança comprovadamente sem efeito runtime | Lint/validadores de documentação, conformidade estrutural e verificações essenciais do repositório |
| STANDARD | Código de aplicação, UI, regra de negócio, testes comuns | FAST + lint, typecheck, testes unitários/focados, build, testes de integração relevantes |
| CRITICAL | Auth, permissões, pagamentos, banco/schema, migrações, infra, dependências, workflows de CI, secrets, política de segurança, paths desconhecidos | STANDARD + suíte expandida, testes de integração reais e verificações de segurança/arquitetura aplicáveis |

A classificação deve partir do diff confiável entre base e candidato, ser testada com cenários positivos e negativos e usar a regra de precedência **CRITICAL > STANDARD > FAST**. Paths desconhecidos, falha de diff ou mudança no próprio mecanismo de classificação são CRITICAL. **Não inferir FAST** apenas por extensão de arquivo: documentações executáveis, scripts e templates podem impactar runtime. O classificador é código **local** do projeto, por exemplo `scripts/ci/classify-change.mjs`, não importado do antigo orquestrador.

## 4. Arquitetura recomendada

```text
.github/workflows/validate-pr.yml
scripts/ci/classify-change.*       # classificação local, testável e fail-closed
scripts/ci/classify-change.test.*  # testes de promoção de risco e entradas inválidas
docs/ci-validation.md              # gates reais, matriz, required checks e rollback
```

Fluxo:

1. Descobrir os SHAs e o diff sem confiar em input não autenticado.
2. Executar classificador e seus testes; falha deve impedir sucesso.
3. Resolver matriz de gates por perfil; gates adicionais só aumentam cobertura.
4. Executar validação em ambiente reprodutível, incluindo merge preview quando suportado.
5. Publicar **um status estável e obrigatório** que falhe se qualquer gate aplicável falhar ou for cancelado.
6. Salvar logs e metadados exact-SHA; tratar timeout como falha, não como aprovação.
7. Agente externo observa status terminal e, se necessário, usa `corrigir-ci` para remediar em novo commit.

### Exemplo base de workflow

Adapte scripts e versões à stack. **Exemplo ilustrativo, não é um workflow pronto para copiar sem implementar o classificador e os gates.** O exemplo usa um único job obrigatório, sempre executa o perfil escolhido e mantém o nome público `Validate repository`.

```yaml
name: Validate PR
on:
  pull_request:
  push:
    branches: [main]
  # merge_group: {} # ativar somente quando a merge queue for usada

permissions:
  contents: read

concurrency:
  group: validate-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  validate:
    name: Validate repository
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - name: Checkout candidate
        uses: actions/checkout@<PINNED_ACTION_SHA>
        with:
          fetch-depth: 0
          persist-credentials: false

      - name: Setup runtime
        uses: actions/setup-node@<PINNED_ACTION_SHA>
        with:
          node-version-file: .nvmrc
          cache: npm

      - name: Install locked dependencies
        run: npm ci

      - name: Test risk classifier
        run: npm run ci:classify:test

      - name: Classify trusted diff
        id: risk
        run: npm run ci:classify -- --github-output "$GITHUB_OUTPUT"

      - name: Baseline checks
        run: npm run ci:baseline

      - name: Standard checks
        if: steps.risk.outputs.profile == 'STANDARD' || steps.risk.outputs.profile == 'CRITICAL'
        run: npm run ci:standard

      - name: Critical checks
        if: steps.risk.outputs.profile == 'CRITICAL'
        run: npm run ci:critical

      - name: Record candidate identity
        if: always()
        run: |
          echo "event=${{ github.event_name }}"
          echo "checkout_sha=${{ github.sha }}"
          echo "run_id=${{ github.run_id }}"
```

**Obrigatório antes do uso:** substituir os placeholders de SHA por digests oficiais verificados; adicionar `ci:classify:test`, `ci:classify`, `ci:baseline`, `ci:standard` e `ci:critical` ao projeto; assegurar que o output `profile` seja sempre exatamente FAST, STANDARD ou CRITICAL e falhe para valor inválido; garantir que o diff cubra toda a mudança. Em GitHub Actions, `github.sha` pode identificar um commit de merge sintético em PR e não deve ser confundido com o head SHA do autor. A estratégia exata de comparação depende do evento e precisa de testes.

**Atenção:** a otimização FAST não pode tornar invisível um teste requerido pelo ruleset. Se um check for condicional, agregar seus resultados em um status estável e verificar que não foi pulado indevidamente. Não usar `continue-on-error` em gates obrigatórios.

## 5. Matriz de adaptação por solução

Preencher antes de migrar ou implantar em novo repositório:

| Campo | Decisão exigida |
| --- | --- |
| Linguagem/runtime | Versão fixa; instalação reproduzível e lockfile |
| Branches e eventos | PR, push, merge queue e forks |
| Status público obrigatório | Nome exato e configuração do ruleset |
| Paths críticos | Arquivos e diretórios com potencial de segurança, integridade e deploy |
| FAST / STANDARD / CRITICAL | Comandos reais e orçamento máximo de duração |
| Banco e serviços | Containers ou ambiente efêmero, schema/migrações, limpeza |
| Testes e build | Testes unitários, integração, E2E, visual, contratos, artefatos |
| Identidade do candidato | base/head, merge preview, checks exact-SHA |
| Segurança | Permissões, action pinning, secrets, Dependabot e supply chain |
| Diagnósticos | Retenção e tratamento seguro de logs e artefatos |
| Migração | Comparativo antes/depois e rollback |

As aplicações não têm obrigação de compartilhar o mesmo YAML: compartilham **invariantes verificáveis** e especializam a implementação pelo risco da solução.

## 6. Procedimento de implantação em repositório novo

1. Inventariar stack, comandos locais, fluxos PR/push, regras de proteção e integração necessária.
2. Registrar a matriz de adaptação em `docs/ci-validation.md`.
3. Criar classificador **local** com casos de teste FAST, STANDARD, CRITICAL, path desconhecido, falha de diff, entrada inválida e alteração do próprio classificador.
4. Implementar primeiro os gates completos de STANDARD/CRITICAL; habilitar FAST somente quando sua redução de cobertura estiver formalmente justificada.
5. Criar workflow com nomes de check estáveis, permissões mínimas e dependências pinadas. Validar em PR real; testar quebra proposital de lint, teste, build, integração e classificador.
6. Verificar branch protection/ruleset e o SHA associado a cada status. Não aceitar `skipped`, `neutral` ou status de SHA antigo como substituto de gate obrigatório.
7. Documentar owner, processo de correção, troubleshooting e rollback. Após aprovação independente, adotar como padrão do projeto.

### Critérios de aceite para implantação

- [ ] Todos os eventos pertinentes produzem o check obrigatório no candidato correto.
- [ ] Entradas desconhecidas e falhas de classificação não reduzem risco.
- [ ] Cada perfil executa todos os gates previstos e CRITICAL contém STANDARD.
- [ ] Testes negativos demonstram falha real dos gates.
- [ ] Dependências e actions têm pinning e versões controladas.
- [ ] Segredos não são liberados a código não confiável.
- [ ] Não há import, download nem execução do `delivery-orchestrator` ou de agentes de IA.
- [ ] A configuração do ruleset corresponde aos status publicados.
- [ ] O procedimento de rollback foi testado ou operacionalmente ensaiado.
- [ ] O arquivo `docs/ci-validation.md` contém comandos reproduzíveis e responsáveis.

## 7. Migração de CI legado

**Não apagar `.delivery-v2/` antes de mapear seus consumidores.** Primeiro copiar a **semântica** da política e do classificador para os arquivos locais neutros, portar os testes, comparar decisões por diffs de regressão e verificar required checks. Somente então remover lock, referência SHA, diretórios e variáveis legados ainda efetivamente sem consumidores. Arquivos históricos de evidência não devem ser apagados indiscriminadamente.

Migrar em PR isolada, com rollback que reverta o diff de forma atômica. Proteger a janela de troca de required checks: preservar o nome existente até atualizar e verificar ruleset, ou coordenar a alteração sem permitir merge desprotegido. Nenhuma migração deve enfraquecer gates por redução de duração.

### Situação dos três projetos de referência

- **SolverFin:** migrar `.github/workflows/delivery-v2-ci.yml` e classificador; conservar testes Prisma/PostgreSQL, build e a validação visual do extrato.
- **controle_calorias:** migrar `.github/workflows/agent-check.yml` e nomenclatura de risco; conservar sharding Vitest, TiDB, arquitetura, artefatos e validação exact-head.
- **training-system:** migrar `.github/workflows/validate-pr.yml`, preservando especificamente o contexto obrigatório **`Validate repository`**.

As especificações detalhadas e o estado real de cada migração pertencem às issues [SolverFin #704](https://github.com/crgasparoto-br/SolverFin/issues/704), [controle_calorias #1317](https://github.com/crgasparoto-br/controle_calorias/issues/1317) e [training-system #499](https://github.com/crgasparoto-br/training-system/issues/499).

## 8. Evidência e revisão do padrão

Antes de declarar um projeto conforme, apresentar: matriz preenchida, comparação de decisões de risco, run real de PR com status no SHA esperado, evidências positivas e negativas dos gates, verificação do ruleset e plano de rollback. O padrão documentado **não prova**, por si só, conformidade de um repositório. Mudanças nos perfis, nos checks ou nas garantias de segurança requerem revisão documental e testes correspondentes.
