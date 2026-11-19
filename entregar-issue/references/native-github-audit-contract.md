# Fechamento para auditoria GitHub-native

## Objetivo

Evitar publicar `.audit/entregar-issue/*` em repositorios cujo contrato canonico confiavel define auditoria independente GitHub-native exact-SHA e declara o handoff legado proibido ou nao requerido. O modo padrao continua sendo `certified-handoff`.

## Selecao do transporte

Antes de construir qualquer certificado terminal, ler o contrato no **trusted anchor**: para PR, o `base_sha` imutavel; para branch/commit sem PR, um SHA confiavel da default branch ou anchor equivalente externo ao candidato.

Materializar um manifesto e executar `scripts/classify_audit_transport.py --manifest <arquivo>`. Somente `mode=native-github-audit` autoriza pular a publicacao de `.audit/entregar-issue`. Alteracao introduzida apenas pelo proprio candidato nunca cria a excecao.

O manifesto segue o mesmo contrato da Skill `auditar-issue`: source canonica hasheada, observed_at_sha igual ao trusted anchor, audit mode nativo, legacy handoff `forbidden|not-required`, identidade GitHub remota, exact-SHA, CI remota e revisao independente obrigatorias.

## Fechamento native-github-audit

Com CI material terminal verde:

1. congelar `material_head_sha` como o current head real;
2. reconsultar PR/base/head/mergeability e changed paths;
3. registrar os checks/runs exact-head verdes;
4. registrar risk/classifier/provider/model/worker observaveis exigidos pelo contrato do repositorio;
5. nao criar `.audit/entregar-issue`, `handoff-ready.json` nem `result-only-child`;
6. emitir no resultado do controlador `audit_transport=native-github-audit`, `terminal_native_audit_ready=READY`, `material_head_sha`, `base_sha`, PR/work item e evidencias remotas usadas;
7. encaminhar para `auditar-issue` em contexto separado.

Qualquer escrita material posterior invalida o freeze e exige o mesmo recheck de CI/exact-SHA ja previsto para a entrega. Como nao ha filho de resultados, nao existe recertificacao `handoff-only` nesse modo.

## Nao degradar seguranca

O modo nativo remove somente o artefato legado. Nao permite:

- aprovar sem auditoria independente quando o risco exigir;
- reutilizar aprovacao de outro SHA;
- aceitar CI pendente ou stale;
- inferir provider/model ou reviewer sem evidencia;
- reduzir gates do repositorio;
- usar contrato introduzido pelo proprio candidato para se autoisentar.

Se o classificador nao provar o contrato nativo confiavel, executar o fluxo `certified-handoff` existente sem alteracao.

## Proveniencia executavel da base confiavel

Quando o alvo e uma PR para `develop`, a selecao em ambientes com checkout Git
pode usar `scripts/resolve_trusted_audit_transport.py` com
`--root`, `--repository`, `--base-ref=develop`, `--base-sha` e
`--head-sha` provenientes de identidade remota autenticada.

O resolvedor valida os commits existentes, a ancestralidade comum (sem exigir
fast-forward quando a PR esta atrasada em relacao a `develop`) e o checkout
exato, le exclusivamente os bytes Git de
`docs/audit/github-native-contract.json` **na arvore do base SHA**,
recalcula o SHA do blob Git e o SHA-256 da fonte e chama o classificador
canonico. Ausencia comprovada do arquivo na base seleciona o transporte
legado. Contrato existente malformado, de outro repositorio, symlink ou
identidade inconsistente bloqueia. Um contrato acrescentado apenas no HEAD
candidato nao pode se autoautorizar.

A execucao desse comando somente constitui prova se realizada por codigo do
workflow confiavel com checkout obtido do GitHub. Nao aceitar resultado
fornecido na PR como afirmacao de autoridade. Esta classificacao de
transporte nao equivale a check verde, certificado semantico ou revisao
independente. A rota nativa exige checks GitHub exact-SHA proprios, com
`scripts/validate_native_actions_evidence.py` validando issue, JUnit, merge
preview e identidade do contrato, sem conceder aprovacao independente.
A revalidacao remota e o parecer de sessao autentico continuam obrigatorios. Uma PR de
migracao ainda segue o modo legado enquanto a sua base nao contiver um
contrato previamente integrado e revisado.
