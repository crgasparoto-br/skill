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
4. Captura completa do ruleset, inclusive bypass_actors; resposta sem esse
   campo ou bypass nao vazio bloqueia o planejamento ate revisao administrativa.
5. Backup do estado anterior e autorizacao administrativa rastreavel.

## Gerar somente a previa em ambiente com GitHub CLI autenticado

    python3 scripts/plan_session_ruleset_m2.py --repo crgasparoto-br/skill --branch develop --ruleset-id 24821474
    python3 scripts/plan_session_ruleset_m2.py --repo crgasparoto-br/skill --branch main --ruleset-id 24821457

A proposta exige PR, strict status checks, protecao de exclusao e force-push,
check tecnico e origem GitHub Actions (app 15368). Somente o check
legado Verify independent audit (exact SHA) pode ser retirado e trocado
pelo check de sessao; os demais contextos e regras sao preservados.
Propoe 0 reviews humanos e enforcement active para ambas as branches.

A aplicacao e o read-back das regras efetivas devem ser realizados por
administrador apos a prova operacional M2. O script e intencionalmente
somente leitura, impedindo conclusoes e ativacoes autoatestadas.
