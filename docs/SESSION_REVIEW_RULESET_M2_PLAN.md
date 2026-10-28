# Planejamento seguro da migracao M2 (issue #127)

A PR #140 continua com seu HEAD material certificado. Este planejamento nao
constitui a revisao de sessao exigida para M2.

O script scripts/plan_session_ruleset_m2.py apenas prepara um JSON.
Ele nao executa PUT/PATCH, altera regras, registra parecer nem faz merge.

## Condicoes para aplicar depois do ensaio

1. Parecer SOLVERIT_SESSION_REVIEW_V1 autentico, produzido em contexto
   realmente separado para o SHA da PR #140.
2. Check Verify session review (exact SHA) verde no SHA auditado.
3. Runs reais de sucesso e negativos: adulteracao, revogacao e mudanca
   de issue/base/HEAD, com links e logs autenticados.
4. Captura administrativa completa dos rulesets aplicaveis, inclusive herdados
   e bypass_actors, mais a branch protection classica quando existir. Resposta
   sem bypass visivel ou protecao concorrente nao reconciliada bloqueia M2.
5. Backup do estado anterior e autorizacao administrativa rastreavel.

## Gerar somente a previa em ambiente com GitHub CLI autenticado

    python3 scripts/plan_session_ruleset_m2.py --repo crgasparoto-br/skill --branch develop --ruleset-id 24821474
    python3 scripts/plan_session_ruleset_m2.py --repo crgasparoto-br/skill --branch main --ruleset-id 24821457

A proposta exige PR, strict status checks, protecao de exclusao e force-push,
checks tecnicos, autorizacao offline, certificado exact-SHA e origem
GitHub Actions (app 15368) em ambas as branches. Somente o check
legado Verify independent audit (exact SHA) pode ser retirado e trocado
pelo check de sessao; os demais contextos e regras sao preservados.
Propoe 0 reviews humanos e enforcement active para ambas as branches.

A aplicacao e o read-back das regras efetivas devem ser realizados por
administrador apos a prova operacional M2. O script e intencionalmente
somente leitura, impedindo conclusoes e ativacoes autoatestadas.

## Verificacao de regras efetivas apos aplicacao pelo administrador

Quando o administrador tiver aplicado a proposta e restaurado a protecao de
ambas as branches, executar novamente leituras autenticadas:

    python3 scripts/plan_session_ruleset_m2.py --repo crgasparoto-br/skill --branch develop --ruleset-id 24821474 --readback
    python3 scripts/plan_session_ruleset_m2.py --repo crgasparoto-br/skill --branch main --ruleset-id 24821457 --readback

O modo readback nao valida apenas o ruleset informado. Ele consulta o inventario
de rulesets com parents, obtem os detalhes de cada ruleset para exigir
visibilidade de bypass_actors, valida o ruleset-alvo ativo, recusa qualquer
outro ruleset ativo aplicavel a mesma branch e verifica a branch protection
classica quando presente. Protecao classica que reintroduza review humano,
code-owner/last-push review, bypass, check legado, origem inesperada, force-push
ou exclusao e bloqueante.

O status devolvido comprova somente a estrutura administrativa efetiva observada;
NAO comprova revisao de sessao, negativos operacionais ou satisfacao integral de
R127-12/R127-13. Nunca aplicar uma proposta para forcar teste verde ou sem antes
conferir os ensaios M2.

## Integridade da coleta e disponibilidade dos checks

O inventario administrativo e coletado com `gh api --paginate --slurp` e
`includes_parents=true&per_page=100`. A listagem completa e obrigatoria;
objetos malformados, IDs duplicados, sumarios divergentes e bypasses ocultos
bloqueiam, assim como checks legados presentes apenas em `checks` da protecao
classica. HTTP 404 sem permissao administrativa comprovada nao prova ausencia
de branch protection.

Antes de aplicar uma proposta a `main`, o administrador deve comprovar em
uma PR real contra `main` que `Offline authorization tests` e
`collect / Require certified semantic handoff (exact SHA)` sao emitidos pela
aplicacao GitHub Actions exigida e podem concluir com sucesso. O ruleset
atual da `main` nao exige esses dois checks. Sem provas operacionais,
nao aplicar a proposta nem ativar as regras: manter a configuracao anterior.
