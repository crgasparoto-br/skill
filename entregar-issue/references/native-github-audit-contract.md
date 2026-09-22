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
