# Ativação controlada do transporte de auditoria GitHub-native

## Escopo e autoridade

O contrato `docs/audit/github-native-contract.json` é uma **seleção de transporte**, não um certificado de execução nem uma aprovação independente. O repositório `crgasparoto-br/skill` usa `develop` como base para PRs de issue. O arquivo na PR candidata não altera o modo dessa própria PR: somente os bytes do contrato já presentes no SHA autenticado da **base confiável** podem selecionar `native-github-audit`.

Esta implantação requer controle explícito de bootstrap porque a própria PR que introduz o contrato ainda é avaliada no modo `certified-handoff`. Um check vermelho de certificação legada **não** pode ser reclassificado como verde, nem um job `skipped` pode atender um required check.

## Inventário e plano de ativação

1. Verificar a implementação na base: `entregar-issue/scripts/resolve_trusted_audit_transport.py`, `validate_native_actions_evidence.py`, `.github/workflows/reusable-handoff.yml`, `scripts/verify_session_review.py`, `scripts/session_review_github.py`, `scripts/verify_independent_pr_audit.py`. Corrigir e validar qualquer alteração de segurança ou proveniência **antes** do bootstrap. Conferir o caminho do caller `.github/workflows/handoff-evidence.yml`.
2. Na PR de bootstrap, exigir `Validate skills` e `Validate GitHub Audit MCP` sobre seu HEAD, conferir manualmente o contrato contra o SHA Git e o escopo do diff, e produzir dossiê semântico e revisão em contexto separado exigidos pelo transporte **vigente** da base. Falha ou indisponibilidade da certificação continua sendo bloqueio operacional, a ser resolvido legitimamente; nenhuma implantação tem exceção de autopromoção.
3. Somente depois da integração autorizada, ler novamente `develop` e confirmar que `docs/audit/github-native-contract.json` existe na **árvore do SHA corrente** com `repository`, `base_ref`, `schema_version` e todos os quatro controles de garantia, e digest Git real. Não presumir ativação a partir do título, corpo ou comentários da PR.
4. Criar PR nova **baseada após** esse SHA de `develop` (não aproveitar aprovações, pacotes ou checks de PR anterior). Verificar na CI do HEAD exato:
   - `collect / Collect exact-SHA technical evidence`: passou, possui JUnit e evidências autenticadas;
   - `collect / Require native GitHub audit evidence (exact SHA)`: passou como job **executado**, com identidade da issue/PR/base/HEAD e verificação real;
   - `collect / Require certified semantic handoff (exact SHA)`: `skipped` somente quando a origem confiável validou a rota nativa, sem ser requerido nem apresentado como sucesso;
   - `Validate skills` e `Validate GitHub Audit MCP`: passaram no mesmo HEAD.
5. Em contexto distinto, produzir parecer `SOLVERIT_SESSION_REVIEW_V1` autenticado no GitHub, com evidências por obrigação e controles positivos/negativos/regressão. Exigir `Verify operator-attested session review` favorável e revalidar sua identidade. Operador único não prova independência criptográfica, e CI técnica nunca assina o parecer.
6. Inspecionar regras efetivas e rulesets por API antes de alterar required checks. Os nomes legados e nativos diferem; para modo nativo, exigir o **job nativo realmente executado**, nunca job ausente ou `skipped`. Em `main`, preservar o contrato próprio de release e não transportar automaticamente o check de PR de issue para promoção. Ativar os rulesets somente por operação autorizada, com read-back e prova positiva/negativa no novo modo.
7. Após qualquer mudança de base/HEAD, issue, pacote, revisão ou workflow, invalidar a evidência stale e repetir os checks aplicáveis. Marcar checkboxes da issue apenas por executor autorizado, com prova por critério, CAS/read-back e sem declarar auditoria aprovada a partir dos checkboxes.

## Critérios de interrupção e rollback

- Contrato ausente, malformado, origem candidata ou digest divergente: **não** escolher o transporte nativo. Falha detectada em contrato existente não deve ser mascarada pelo fallback.
- CI falha, checkout de tooling não confiável, JUnit ausente ou modificado, issue/PR/base/HEAD/merge preview em drift, revisão não autenticada, check de evidência nativa `skipped` ou ausência de prova independente: **não realizar merge ou fechamento**.
- Na reversão, usar PR revisada para alterar/remover o contrato na base confiável; revisar os required checks e reexecutar testes/CI. Preservar comentários, rejeições e artifacts históricos. Nunca corrigir falha alterando status por escrito ou desativando um gate.

Fontes canônicas: `entregar-issue/references/native-github-audit-contract.md`, `auditar-issue/references/native-github-audit-contract.md`, `docs/WEB_INDEPENDENT_AUDIT.md` e `entregar-issue/references/github-actions-evidence.md`.
