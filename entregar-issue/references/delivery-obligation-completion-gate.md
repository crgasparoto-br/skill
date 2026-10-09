# Barreira deterministica de fechamento

Antes de qualquer resposta terminal, construir um snapshot de fechamento em workspace efemero contendo `status`, `material_head_sha`, `obligations[]` (id/state), `ci.state/subject_sha`, `completion_gate`, `checkpoint.work_item_fingerprint/observed_head` e, se bloqueado, `blocker.operation/failure/evidence/recovery`. Executar `scripts/validate_delivery_obligations.py <snapshot.json>` **apos** `scripts/validate_delivery_completion.py` e antes de declarar sucesso. O segundo validador permanece autoridade sobre a consistencia do transporte terminal; o novo validador adiciona o fechamento atomico dos requisitos.

- `DELIVERY-COMPLETE-001`: nenhum requisito executavel `pending`, `partial`, `failed` ou sem estado pode acompanhar um resultado de sucesso; `deferred-by-scope` exige justificativa verificavel e nao pode encobrir requisito do target.
- `DELIVERY-CI-002`: CI nao terminal ou SHA diferente do material HEAD impede sucesso. Transferir ownership para `corrigir-ci` conforme protocolo existente.
- `DELIVERY-REENTRY-003`: checkpoint e fingerprint do trabalho devem apontar ao HEAD atual para retomar sem reaplicar commits.
- `DELIVERY-BLOCKER-004`: retorno bloqueado exige operacao, falha observada, evidencia bruta e estrategia de recuperacao; mera falta de tempo, resposta longa ou ciclos incompletos nao sao impedimento comprovado.
- `DELIVERY-HANDOFF-005`: `completion_gate=READY` somente quando o guard terminal do transporte correspondente passou no SHA correto.
- `DELIVERY-EXECUTABLE-007`: quando o retorno for bloqueado, cada obrigacao em `pending`, `partial`, `failed` ou sem estado deve conter `blocker` proprio com operacao, falha, evidencia e recuperacao. Bloqueio na CI nao prova bloqueio em ajustes independentes. Dois commits com cinco itens executaveis restantes nao autorizam encerrar.
- `DELIVERY-REPORT-006`: relatorio final deve refletir literalmente um dos estados permitidos; nunca substituir `pending` por `passed` apenas para passar o guard.

Se o guard reprovar, preservar o checkpoint e executar a proxima fase pendente no mesmo controlador, se tecnicamente possivel; nunca encerrar com aparencia de sucesso. Nao usar este guard como substituto dos testes da aplicacao, da validacao visual ou da auditoria independente. Regressao obrigatoria: `tests/test_validate_delivery_obligations.py`, incluindo sete requisitos parcialmente atendidos e CI pendente.


## Loop anti-encerramento prematuro

Antes de cada resposta final, percorrer todas as obrigacoes abertas, identificar o proximo patch executavel e continuar a implementacao na mesma invocacao. Nao tratar quantidade de commits, testes focados ou progresso parcial como criterio de parada. Quando CI estiver pendente, seguir com alteracoes independentes sem reescrever o material sob congelamento; delegar apenas a coleta/remediacao de CI conforme ownership. Se houver impedimento real, preencher o bloqueio individual de cada obrigacao ainda aberta; na falta dele, o guard reprova o encerramento. Nao criar loops infinitos: quando nao for possivel progredir por limite da plataforma, relatar concretamente o trabalho remanescente sem alegar conclusao ou inventar um bloqueio.
