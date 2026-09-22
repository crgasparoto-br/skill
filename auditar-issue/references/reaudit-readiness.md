# Preflight de remediacao antes de nova auditoria independente

## Objetivo

Evitar gastar uma auditoria independente ampla apenas para descobrir que a remediacao do finding anterior ainda nao fechou a classe do escape ou deixou controles antigos sem execucao.


## Fast path: finding anterior ainda aberto

Antes de qualquer preflight pesado, verificar se a tentativa corrente realmente fechou o finding anterior. Quando o finding anterior for uma falha de gate deterministico, comparar `audit-remediation.json` com `failed_gate.command` do resultado anterior e exigir `closure_kind=deterministic-gate-replay`, o mesmo comando, `subject_sha` do novo material head, `exit_code=0` e evidencia hasheada.

Se essa prova estiver ausente, divergente ou o mesmo gate oficial continuar vermelho, encerrar em `blocker-bounded` como `remediation-incomplete`/`same-finding-still-open` sem consumir matriz de ataques, saturacao, browser ou suites caras nao relacionadas. Reutilizar o `rejection_id` e o finding ID anteriores; uma continuacao do mesmo finding nao cria uma nova rejeicao nem um novo evento de aprendizado. Gerar novo `rejection_id` somente quando houver finding materialmente novo ou quando a causa/fingerprint anterior tiver sido realmente fechada antes do novo finding.

## Aplicabilidade

Aplicar quando houver evidencia de auditoria independente anterior `REPROVADA` para a mesma issue, PR, branch ou familia de candidato e houver nova tentativa de auditoria apos remediacao.

Antes da descoberta ampla:

1. localizar o resultado estruturado anterior e `audit-remediation.json`; exigir fechamento 1:1 de todos os findings e recomendacoes acionaveis, nao apenas do ultimo blocker;
2. para `targeted-remediation`, nao exigir learning/audit-escape closure; para `systemic-remediation`, exigir `learning-closure.json` e `audit-escape-closure.json`, vinculados ao mesmo `rejection_id`;
3. para `targeted-remediation`, reexecutar apenas o caso literal e superficies diretamente impactadas; quando a origem for gate deterministico, aplicar o exact failed gate replay antes de qualquer prova ampla;
4. somente para `systemic-remediation`, verificar `escape_class`, implementacao errada plausivel, caso literal, no minimo dois casos irmaos, `prevention_change`, `detection_change` e `status=passed`;
5. somente para `systemic-remediation`, obter snapshots imutaveis anteriores de `audit-escape-closure.json` e `inherited-controls.json`, preservar lineage cumulativa e exigir controles ativos executados no novo SHA;
6. se qualquer prova obrigatoria da classe corrente estiver ausente, incompleta, `failed` ou `not-run`, interromper a auditoria ampla e devolver `remediation-incomplete`, listando exatamente os campos faltantes.

Esse preflight nao substitui a auditoria independente quando a remediacao estiver pronta. Ele impede que a auditoria seja usada como primeira execucao do ataque que a entrega ja deveria ter exercitado e impede regressao silenciosa de findings mais antigos.

Na auditoria normal, executar esse contrato pelo agregador `scripts/check_delivery_preflight.py`, passando os snapshots historicos via `--previous-closure ... --previous-inherited-controls ...`; o agregador resolve `audit-escape-closure.json` e `learning-closure.json` do certificado corrente e os encaminha ao validador. Para teste focado do subvalidador, usar `scripts/check_reaudit_readiness.py --closure ... --learning-closure ... --inherited-controls ... --head-sha ... --previous-closure ... --previous-inherited-controls ...`. Os snapshots anteriores devem vir de commit/handoff imutavel anterior, nunca ser reconstruidos a partir do pacote atual.
