# Issue #88 — plano de controle de entregas (em desenvolvimento)

**Estado em 2026-10-11: IMPLEMENTAÇÃO PARCIAL; NÃO APTO PARA PRODUÇÃO.**
**Repositório:** `crgasparoto-br/skill`; **base:** `develop`; **PR:** [#89](https://github.com/crgasparoto-br/skill/pull/89) (draft, sem merge).
Este documento registra resultados **reportados pelo operador da VPS**, distintos dos testes unitários e de uma auditoria independente.

## Arquitetura prevista

```text
ChatGPT -> MCP de entrega -> Keycloak/OAuth + autorização por repositório/ação
  -> controlador persistente (lock, SQLite, recuperação)
  -> snapshot Git da develop fixado por SHA -> Docker rootless isolado
  -> edição e testes funcionais -> broker GitHub App separado
  -> commit + PR para develop -> CI no HEAD exato -> auditoria independente
```

A auditoria de GitHub existente continua **somente leitura** e separada do serviço de entrega.
O MCP de entrega autenticado ainda **não** possui ferramentas de escrita habilitadas neste fluxo.
Nunca transferir chave privada da App, tokens de publicação ou socket Docker do host para código de repositório não confiável.

## Implementado e testado até aqui

| Componente | Evidência / limite |
| --- | --- |
| Política de autorização deny-by-default | Implementação e testes offline; integração OAuth por operação pendente |
| `jobs.py` | Jobs SQLite, idempotência, ownership por ator, estados e recuperação conservadora |
| `controller_lock.py` | `flock` exclusivo; todos os caminhos concorrentes devem usar o mesmo lock |
| `snapshot_export.py` | Snapshot do Git mirror com SHA fixado, seleção restrita de arquivos, manifesto SHA-256 e marcador de commit |
| `workspace_container_check.py` | Perfis fixos `integrity-v1`, `posix-shell-syntax-v1` e `bash-syntax-v1`, sem shell arbitrário fornecido por MCP |
| `check_evidence.py` | Evidências SQLite imutáveis por (job, check), ligadas a ator, base SHA e imagem de verificação |
| `verified_check_runner.py` | Encadeia execuções rootless e registros de evidência, falhando fechado em erro |
| `locked_check_dispatch.py` | Valida estado `prepared`, marcador do snapshot e bloqueio exclusivo durante verificações |
| `local_controller.py` | CLI local: recuperação sob lock e despacho explícito para job preparado; **não** é endpoint MCP |
| `controller_loop.py` | Loop interrompível de recuperação; testado, não implantado como serviço contínuo |
| `github_evidence_validation.py` | Validação estrutural da identidade PR, SHA e checks; não autentica a origem |
| `github_evidence_reader.py` | Adaptador de leitura GitHub com rejeição conservadora; sem homologação de rede real |
| `pr_binding.py` | Registro SQLite imutável e idempotente job–PR; não valida publicação sem broker |
| `delivery_finalization.py` | Bloqueio explícito de conclusão na ausência de CI e auditoria independentes |

**Nota de confiança:** comparar o marcador `.solverit-expected-sha` com o SHA do job não prova, sozinho, que os bytes do snapshot vieram do Git remoto. O manifesto dentro do próprio snapshot também não é uma âncora independente de confiança. Antes da produção, é necessário ancorar o snapshot em um mirror e armazenamento protegidos, controlar TOCTOU e revisar o modelo de ameaça do usuário com acesso ao daemon Docker rootless. Evidências de checks não equivalem a CI aprovado, testes funcionais completos ou auditoria.

## Homologações realizadas na VPS

Ambiente reportado pelo operador: Ubuntu na OVH, usuário dedicado `solverit-worker` (UID 1004), Docker rootless em `/run/user/1004/docker.sock`; autenticação privilegiada da GitHub App mantida em usuário separado. Não ampliar privilégios do worker nem copiar credenciais.

- **Commit `c65cfc93`:** 5 testes de evidências aprovados; regressão **203/203**.
- **Commit `2b5099c6`:** 5 testes de exclusividade/ator/SHA aprovados; regressão **208/208**.
- **Commit `f497b0f2`:** 3 testes do controlador aprovados; regressão **211/211**, em **2026-10-11**, código de saída 0. Os avisos `usage: controller ... error:` são esperados em testes negativos.
- **Commit `d4dbdafd`:** regressão **215/215**, incluindo 4 testes do loop de recuperação.
- **Commit `9d44bbd9`:** regressão **216/216** após correção da guarda de conclusão.
- **Commit `3ce0fed4`:** regressão **217/217** com rejeição de marcador smoke falsificado.
- **Commit `d4fec687`:** regressão **220/220** com bloqueio explícito de finalização.
- **Commit `0dadba31`:** regressão **229/229** com validação estrutural de evidências GitHub.
- **Commit `5d8dd69e`:** regressão **234/234** com adaptador read-only de consulta GitHub (respostas simuladas).
- **Commit `3864aeb4`:** **5/5** testes de vínculo job–PR e regressão completa **239/239**, código de saída **0**, conforme execução reportada pelo operador em **2026-10-11**. Testes de persistência, isolamento entre atores, divergência do SHA e rejeição de reassociação conflitante aprovados.
- **Execução rootless integrada real** reportada após `2b5099c6`: job `d6c4e992-eff1-4541-8a1c-ef3ec7a5ea07`, banco `/home/solverit-worker/issue88-homologacao/integrated-3c07c684f577435e96fbe430a4fb4af1.sqlite3`, base SHA `c10136fe8335a04aea3d2d9a959d42aa6223dd8a`. Foram persistidas **3/3** evidências `passed=True`, `timed_out=False`; job permaneceu `prepared`; código 0; nenhum contêiner remanescente listado.
- Snapshot usado na homologação: `/home/solverit-worker/issue88-homologacao/runtime-snapshots/solverit-issue88-0ef9cca3eba44d1194588083fed2e087`, manifesto de **557** entradas. O snapshot pertence ao worker: inspecionar arquivos protegidos com `sudo -u solverit-worker`; **não** alterar permissões para contornar erros.

Essas homologações **não** validam a inicialização do `solverit-issue-delivery.service`, o fluxo E2E via ChatGPT/Keycloak/MCP, a publicação de PR, CI exact-head nem auditoria independente.

## Operação local restrita

Testes automatizados do módulo (sem segredos GitHub):

```bash
cd integrations/github-delivery-mcp
python -m unittest discover -p 'test_*.py'
```

O controlador aceita `--database`, `--lock`, `--check-job`, `--check-actor` e `--check-snapshot`; os três `--check-*` são obrigatórios em conjunto, incompatíveis com `--smoke-key`. Requer execução como UID 1004 e job `prepared` **sem evidências anteriores**; tentativas repetidas não substituem evidências automaticamente. Um mesmo lock persistente deve ser empregado em todo despacho e recuperação. **Não usar esses argumentos como entrada pública de um cliente MCP** nem executar contra banco de produção durante a homologação.

Exemplo de invocação **apenas para um novo job de laboratório previamente preparado**:

```bash
sudo -u solverit-worker -H /usr/bin/python3 local_controller.py \
  --database /caminho/protegido/jobs.sqlite3 \
  --lock /caminho/protegido/controller.lock \
  --check-job ID_DO_JOB --check-actor ATOR_CONFIAVEL \
  --check-snapshot /caminho/protegido/snapshot
```

A recuperação e o despacho ocorrem em seções protegidas pelo mesmo arquivo de lock, mas o controlador atual **libera e readquire** o lock entre recuperação e despacho; a validação é refeita ao despachar. Isso não constitui uma transação atômica entre as duas etapas. O serviço contínuo ainda precisa de integração própria.

## Restrições e pendências obrigatórias

1. Implementar o servidor MCP de entrega com validação independente de token OIDC (issuer, audience, assinatura e expiração), permissões server-side por ferramenta e reautorização; jamais confiar em `actor` fornecido pelo cliente.
2. Projetar a fronteira do executor de código não confiável: snapshots protegidos, proveniência Git, separação de permissões, quotas de disco, isolamento de egress, recuperação e cancelamento seguros.
3. Implementar edição autorizada, testes funcionais específicos do projeto e tratamento determinístico de falhas; checks de sintaxe não substituem a suíte funcional.
4. Implementar broker privilegiado de GitHub App separado do worker, CAS no SHA esperado da branch, commits e PRs **somente contra `develop`**, sem force push, merge ou alteração direta de `main`.
5. Integrar serviço `systemd`, política de logs redigidos, idempotência ponta a ponta e recuperação de falhas sem duplicar efeitos.
6. Exigir CI no HEAD exato, confirmação de branch/PR e auditoria independente com veredito explícito na primeira linha; não marcar `succeeded` até que evidências necessárias sejam verificadas.
7. Executar homologação E2E com repositório alvo autorizado, testes negativos de segurança e auditoria independente; atualizar esta documentação com links aos artefatos.

**Não fazer merge da PR #89 nem encerrar a Issue #88 apenas com os testes e a homologação acima.**

## Serviço systemd: unidade de recuperação em staging (não ativada)

O arquivo [`ops/solverit-issue88-recovery.service`](./ops/solverit-issue88-recovery.service)
é um exemplo **oneshot**, limitado à recuperação conservadora de jobs locais.
Foi versionado após a homologação manual do controlador em 2026-10-11
(job `aac25a8e-fdb0-43de-a730-140d8aef8c3b`: 3 verificações aprovadas,
3 evidências persistidas, status final `prepared`, exit code 0).
A unidade **não** é um daemon contínuo, não executa o MCP e não publica código.
Não tem seção `[Install]`, não foi instalada nem ativada na VPS.

Antes de instalar, revisão independente deve confirmar compatibilidade das
diretivas systemd com Ubuntu/daemon Docker rootless, permissões das pastas,
separação da unidade `solverit-issue-delivery.service` já existente e
segurança do banco `controller-service.sqlite3` em staging.
Ela não deve ser copiada para a unidade de produção sem aceite explícito.

## Loop de recuperação preparado (ainda não ativado)

O módulo `controller_loop.py` implementa um laço interrompível por SIGTERM/SIGINT,
com intervalo configurável entre 10 e 3600 segundos, e usa o mesmo `flock`
exclusivo por ciclo. Após reconciliação, libera o lock antes de aguardar.
O módulo **não despacha jobs preparados**, não expõe MCP e não publica código.
Não substitui ainda o `solverit-issue-delivery.service` oneshot na VPS.
Testes de shutdown, exclusividade e identidade devem passar antes de uma
implantação piloto; não iniciar um segundo controlador simultâneo sem verificar
que ambos usam exatamente o mesmo banco e lock.

## Proteção de conclusão de jobs reais

`JobStore.transition(..., 'succeeded')` bloqueia todos os jobs de entrega; a exceção preserva apenas o smoke offline legado, exigindo simultaneamente ator `local-smoke-operator`, repositório `crgasparoto-br/training-system`, issue 88, branch `develop` e os marcadores de base/HEAD `offline-smoke-no-repo-operation`. Um marcador isolado não autoriza sucesso. Essa é uma proteção provisória **fail-closed**, não uma API de conclusão. A futura finalização deverá verificar evidências imutáveis de publicação, CI no HEAD exato e auditoria independente antes de alterar o estado. Jobs anteriores já concluídos continuam legíveis e não são migrados.

## Finalização: bloqueio explícito até haver verificador confiável

O módulo `delivery_finalization.py` introduz a fronteira de verificação de conclusão,
mas **não finaliza jobs**: recusa inclusive jobs `prepared` enquanto não houver
consulta autenticada e independente às evidências de publicação da PR, CI no
HEAD exato e auditoria. Não aceita resultado de check, booleano nem parecer
fornecido pelo worker, texto de issue ou argumento MCP. `jobs.py` continua
impedindo a transição comum dos jobs reais para `succeeded`.

A futura implementação deve recuperar evidências diretamente de GitHub e do
canal independente de auditoria, conferir owner/repo, issue, PR, base
`develop`, HEAD e integridade temporal, e registrar a conclusão de forma
atômica e idempotente. A presença deste módulo não comprova a finalização E2E.

## Validação estrutural de evidências GitHub (ainda não conectada)

O módulo `github_evidence_validation.py` compara PR e checks com repositório,
issue, branch e base `develop`, HEAD esperado do job, conclusões `success`
e lista não vazia de checks obrigatórios. Rejeita registros ausentes, duplicados,
pendentes ou associados a outro SHA. É um **validador puro**; o campo `source`
nos registros não autentica origem e **não** deve ser aceito de entrada MCP/worker.
O catálogo de required checks precisa vir de política protegida. O adaptador de
consulta read-only GitHub, a auditoria independente e a finalização atômica
continuam pendentes. Passar nesses testes não libera `succeeded`.

## Adaptador read-only de consultas GitHub (staging, sem liberação)

`github_evidence_reader.py` consulta a API oficial GitHub por HTTPS com token
de instalação **somente leitura e duração curta**, fornecido exclusivamente por
um broker separado. Rejeita redirects, respostas grandes, paginação incompleta,
forks e divergência do SHA/branch. Não registra tokens ou conteúdos de headers.

**Bloqueio intencional:** uma PR que mencione a issue no título ou no corpo não
constitui vínculo verificável. O campo de issue permanece `None` até haver
uma estratégia autoritativa de associação job→PR→issue; assim, o adaptador
sempre recusa a conclusão, mesmo quando o CI é verde. Ele não foi integrado ao
serviço da VPS e não autentica MCP, não finaliza jobs ou executa auditoria.

## Vínculo persistente job–PR (staging)

`pr_binding.py` adiciona `job_pr_bindings` ao mesmo SQLite, sem alterar
o schema legado de `jobs`. O vínculo é imutável e idempotente: um job
`prepared` pode associar apenas uma PR e o `expected_head` da entrega.
Outro ator, HEAD divergente, branch `main`/`develop` ou nova PR para o
mesmo job são rejeitados. A gravação não modifica o estado do job.

**Fronteira de confiança:** o método `bind_published_pr` só pode ser chamado
pelo futuro broker privilegiado, apos obter e conferir a resposta autenticada
do GitHub e a autorização do solicitante. O método não executa por conta
própria essas consultas. Portanto, a entrada do worker/MCP **não** pode
escrever nesse banco nem invocar a associação. Não há vínculo autoritativo
em produção ainda, e `github_evidence_reader.py` continua recusando a
finalização por falta de verificação independente da issue e auditoria.

## Marco de validação em 2026-10-11: 239 testes aprovados

A regressão **239/239** corresponde ao checkout da PR #89 no SHA `3864aeb4bfb5561f7d4889a0a077400e86ee8549`; não equivale a CI GitHub exact-head verde ou auditoria independente. O serviço `solverit-issue-delivery.service` foi homologado anteriormente como `oneshot` com `Result=success` e dois jobs históricos `succeeded` preservados. Os componentes adicionados posteriormente (`controller_loop.py`, `pr_binding.py`, adaptadores de evidência e novas guardas de `jobs.py`) **não foram implantados ou homologados como serviços ativos** nesta etapa.

A associação SQLite job–PR é apenas um dado correlacionado; ela não comprova publicação GitHub nem autentica o vínculo com a issue. Permanecem bloqueantes: broker confiável, consultas GitHub reais, política de required checks, confirmação independente de issue/PR, auditoria exact-head, finalização atômica, autorização MCP/Keycloak e execução funcional ponta a ponta em sandbox.

**Decisão operacional:** manter a PR #89 em draft para `develop`, sem merge e sem fechar a Issue #88. Não iniciar uma segunda unidade de recuperação em paralelo ao serviço já instalado.

## Vinculo de PR e consulta GitHub (atualizacao de 2026-10-12)

O `github_evidence_reader.fetch_and_validate_github` exige agora um
`PRBinding` coerente com `job_id`, numero da PR e SHA esperado antes da
consulta de rede. Depois confere PR real e checks do mesmo SHA atraves da API
GitHub. O teste usa respostas simuladas; **nao ha homologacao com token real**.

**Restricao crucial:** a funcao nao autentica a origem do objeto `binding`.
Somente um processo privilegiado separado, com SQLite protegido de escrita
pelo executor e do MCP, pode recuperar esse vinculo. Entrada do usuario/worker
nunca pode ocupar esse parametro. A verificacao de auditoria independente,
a autorizacao do broker e a finalizacao atomica ainda nao existem.

A implementacao substitui o bloqueio provisório de `issue_number=None`
pela correlacao persistente do job. O vinculo **nao e evidencia suficiente**
para autorizar `succeeded`, e a API de finalizacao continua bloqueada.

## Leitura confiável do vínculo persistido (2026-10-12)

`trusted_github_verification.py` conecta os componentes existentes:
recupera o job do SQLite, exige estado `prepared`, lê o número da PR
e SHA pelo `PRBindingStore` usando a identidade do proprietário e chama
o leitor autenticado do GitHub. Não recebe número de PR ou vínculo como
argumento externo. Seus testes impedem a consulta de rede quando o job
não está preparado, não pertence ao ator ou não possui vínculo.

**Ainda não autoriza sucesso:** essa função deve executar apenas em processo
confiável com banco protegido do worker/MCP. A implantação das permissões,
obtenção de token de leitura via broker, required checks normativos,
auditoria independente, serviço autorizado e conclusão atômica estão pendentes.
Os testes usam simulação da consulta GitHub.

## Broker GitHub App no verificador protegido (2026-10-12)

`trusted_github_verification.verify_with_github_app` reutiliza
`app_token_broker.mint_token` com operação `read-checks`, somente após
confirmar repositório na allowlist, job `prepared` e vínculo PR persistido.
Não aceita token nem número de PR do solicitante; a credencial permanece na
memória do processo privilegiado durante a consulta. Testes negativos verificam
que repositórios não permitidos e vínculos ausentes não disparam emissão.

**Ainda não implantado:** este é código de integração, não um serviço seguro
pronto. A identidade UID 997, permissões de acesso ao SQLite, autenticação
da chamada ao broker, política de checks obrigatórios e consulta de rede real
precisam ser homologadas separadamente. `server_authorized=True` só pode ser
usado após autorização externa efetiva; o parâmetro não implementa autorização.
Nunca executar o módulo sob a identidade do worker ou em uma rota pública.
Não habilitar `succeeded` antes de auditoria independente e persistência
atômica verificadas.

## Smoke read-only real da GitHub App (2026-10-12)

`github_app_readonly_smoke.py` é um diagnóstico independente do fluxo de
finalização. Executado como o usuário dedicado `solverit-github-auth`,
emite token restrito à operação `read-checks` do repositório
`crgasparoto-br/training-system`; consulta `develop` e seus check runs.
Saída permitida: repositório, branch, SHA, quantidade de checks e flag
`read_only`. Nunca imprime token, chave, cabeçalhos ou exceção original.
Rejeita paginação incompleta ou SHA inválido. O smoke não cria PR e não
modifica jobs, branches nem checks.

A preparação requer copiar apenas os quatro arquivos Python de leitura
(`app_token_broker.py`, `github_evidence_validation.py`,
`github_evidence_reader.py` e `github_app_readonly_smoke.py`) a um
diretório de código somente leitura, de propriedade root, acessível à
identidade autenticadora. Não executar o teste via diretório editável pelo
worker, não modificar permissões de secrets nem imprimir tokens.

**Estado atualizado (2026-10-12):** o operador executou o smoke real com sucesso
na VPS, sob a identidade dedicada. O teste não autentica o vínculo job–PR
nem constitui entrega fim a fim.

## Evidência de homologação — GitHub App read-only (2026-10-12)

Execução informada pelo operador na VPS, após validação do commit
`9b6ab6b6e7200c0f035b3cac88d38df662139462`:

| Verificação | Evidência | Resultado |
| --- | --- | --- |
| Testes específicos de smoke | 5/5 aprovados | PASS |
| Regressão completa | 252/252 aprovados, duração 6,660 s | PASS |
| Processo autenticador | UID 997 `solverit-github-auth`, grupo `solverit-app-key` | Confirmado |
| Código de leitura | Instalado em `/opt/solverit/github-readonly-smoke`, proprietário `root` | Preparado |
| Consulta GitHub real | `crgasparoto-br/training-system` / `develop` | PASS |
| SHA retornado | `fa6b1842e8e30199e3e7efa3b75c47daf7b2abc2` | Observado |
| Checks retornados | 5 check runs | Contagem, não aprovação |
| Saída do smoke | `read_only: true` | PASS |
| Código de saída | `0` | PASS |
| Sessão SSH | Terminal preservado | Confirmado |

A evidência comprova **autenticação real da GitHub App e leitura de metadados da
branch `develop` e seus check runs** no momento do teste. Não comprova que os
cinco checks foram aprovados, não valida uma PR real nem o SHA de sua HEAD, e
não comprova isolamento efetivo entre broker e worker. Nenhum token, PEM ou
cabeçalho confidencial foi incluído no resultado apresentado.

**Critérios de liberação ainda pendentes:** estabelecer o processo privilegiado
com autenticação de chamadas e acesso protegido ao SQLite; vincular publicação
confiável à issue e PR; avaliar o catálogo normativo de checks no SHA exato da
PR; executar auditoria independente nesse SHA; integrar o MCP com OAuth/
Keycloak e autorização por repo/operação; comprovar execução real de issue,
publicação de PR, recuperação/retries e conclusão atômica. A entrega permanece
bloqueada para `succeeded` e a PR #89 segue draft para `develop`, sem merge.


## Fronteira IPC privilegiada adicionada em 2026-10-13 (staging)

A implementacao inicial de `protected_broker_server.py` adiciona socket Unix
local, verificacao de UID por `SO_PEERCRED`, consulta read-only a SQLite
protegido, token GitHub `read-checks` somente em memoria e unica operacao
`verify_bound_ci`. Tentativas de publicaçao, merge, exclusao, impersonacao
e fornecimento de credenciais pelo chamador sao rejeitadas. A resposta
nunca finaliza jobs nem certifica auditoria independente.

Consultar [BROKER_STAGING.md](./BROKER_STAGING.md) para pre-requisitos de
identidade, permissao de arquivos e testes de seguranca. A unit
`systemd/solverit-issue88-github-broker.service` **nao esta instalada ou
ativada**: exige controlador OAuth confiavel, banco protegido (nao o SQLite
editavel pelo worker), provisionamento de grupo e revisao de isolamento.
Estes arquivos versionados **nao constituem homologacao VPS** ou prova de CI
verde no HEAD. A PR #89 segue draft, sem merge automatico.

### Defesa em profundidade do broker — 2026-10-13

O broker IPC de staging passou a exigir duas identidades independentemente:
(1) UID real do controlador, comprovado por `SO_PEERCRED`; (2) token JWT
Keycloak revalidado pelo próprio broker, com issuer/JWKS confiáveis,
audiencia MCP exata, escopo dedicado `solverit:deliver` e allowlist `sub`.
O `sub` criptograficamente verificado deve corresponder ao `actor`
do job no SQLite privilegiado. A identidade OAuth **não** vem de um parâmetro
`actor` enviado pelo MCP. Sem token válido, vínculo PR persistido, HEAD exato
e check GitHub obrigatório, a operação `verify_bound_ci` falha fechada.

O novo `controller_broker_client.py` valida o UID da outra ponta do socket
antes de transmitir o token Keycloak e exige resposta sem credenciais,
`audit_verified=false`. As mensagens são versionadas e rejeitam campos
JSON duplicados e respostas ambíguas. O SQLite deve pertencer ao UID 997
com modo privado (0600 ou mais restritivo); nunca reutilizar diretamente
os bancos editáveis pelo worker. Os testes adicionados exercitam estes gates
apenas **offline** com mocks; não há homologação real ou CI atestada.

O ambiente Keycloak deve provisionar `solverit:deliver` separadamente de
`solverit:read` antes de iniciar qualquer serviço novo; consultar
[BROKER_STAGING.md](./BROKER_STAGING.md). Não foi feito deploy na VPS.
