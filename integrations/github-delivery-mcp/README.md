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

**Nota de confiança:** comparar o marcador `.solverit-expected-sha` com o SHA do job não prova, sozinho, que os bytes do snapshot vieram do Git remoto. O manifesto dentro do próprio snapshot também não é uma âncora independente de confiança. Antes da produção, é necessário ancorar o snapshot em um mirror e armazenamento protegidos, controlar TOCTOU e revisar o modelo de ameaça do usuário com acesso ao daemon Docker rootless. Evidências de checks não equivalem a CI aprovado, testes funcionais completos ou auditoria.

## Homologações realizadas na VPS

Ambiente reportado pelo operador: Ubuntu na OVH, usuário dedicado `solverit-worker` (UID 1004), Docker rootless em `/run/user/1004/docker.sock`; autenticação privilegiada da GitHub App mantida em usuário separado. Não ampliar privilégios do worker nem copiar credenciais.

- **Commit `c65cfc93`:** 5 testes de evidências aprovados; regressão **203/203**.
- **Commit `2b5099c6`:** 5 testes de exclusividade/ator/SHA aprovados; regressão **208/208**.
- **Commit `f497b0f2`:** 3 testes do controlador aprovados; regressão **211/211**, em **2026-10-11**, código de saída 0. Os avisos `usage: controller ... error:` são esperados em testes negativos.
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
