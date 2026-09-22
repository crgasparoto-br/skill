# Vinculo do pacote de entrega ao alvo atual

> **Escopo:** as regras de `.audit/entregar-issue` e `result-only-child` deste documento aplicam-se somente a `audit_transport=certified-handoff`. Em `native-github-audit`, vincular o alvo diretamente por identidade remota exact-SHA e pelo contrato canonico confiavel, sem pacote `.audit`.

## Objetivo

Impedir reuso acidental de `.audit/entregar-issue` herdado da base, de outra issue, PR ou branch. Artefato internamente consistente nao pertence automaticamente ao trabalho atual.

## Preflight obrigatorio

Depois de resolver repositorio, issue/PR, base e branch e **antes de reutilizar qualquer artefato de entrega**, executar `scripts/delivery_target_binding.py` ou consumir a classificacao `artifact_reuse` criada por `controller_cli.py init-context`.

Comparar, quando conhecidos:

- `repository`;
- `issue_number` contra `specification-snapshot.issue`;
- `pull_request_number` contra a PR remota;
- `work_item_kind` e `work_item_number` apenas como identidade da invocacao/compatibilidade, sem substituir os dois numeros canonicos acima;
- `pull_request` como alias legado de `pull_request_number`;
- `base_ref`;
- `head_ref`;
- `specification-snapshot.repository` e `specification-snapshot.issue`.

## Estados

- `fresh`: nao existe pacote anterior utilizavel. Construir todos os artefatos correntes.
- `current-target`: o pacote existente pertence semanticamente ao alvo atual. E apenas candidato a reuso; fingerprints, SHA e gates ainda decidem validade.
- `inherited-base-artifact`: os artefatos de identidade observados pertencem a outro alvo **e sao byte-identicos aos mesmos paths no `base_sha` exato** (ou aos bytes da base materializada em runtime connector-only). Tratar como historico herdado da base, nunca como saida da entrega corrente. **Zero reuso** e novo handoff obrigatorio.
- `foreign-target`: pelo menos uma identidade observada pertence a outro alvo e nao foi provada como byte-identica a base. **Zero reuso** de snapshot, closure, attack matrix, saturation, inherited controls, evidence, certificate ou handoff.
- `partial-current-target`: existe snapshot corrente sem certificado corrente. Continuar a entrega, mas exigir novo handoff.
- `unbound-or-invalid`: pacote legado, invalido ou sem subject verificavel. Tratar como nao reutilizavel.

O exit code `3` do classificador significa `reset-required`, nao finding do produto e nao bloqueio da issue. O controlador deve continuar com estado corrente novo. A classificacao nao e eterna: sempre que `base_ref`, `head_ref`/branch ou `pull_request` mudarem, reexecutar a classificacao antes de qualquer reuso; depois de reconstruir o pacote atual, reexecutar novamente para provar a transicao para `current-target`.

## Regra de reset sem destruicao

Nao apagar historico apenas para limpar o workspace. Em `inherited-base-artifact`, `foreign-target`, `partial-current-target` ou `unbound-or-invalid`:

1. ignorar o pacote anterior como evidencia da entrega atual;
2. reconstruir `source-manifest`, `specification-snapshot`, requirement closure, attack matrix, risk saturation e demais artefatos necessarios a partir das fontes atuais;
3. sobrescrever somente os artefatos canonicos da entrega atual quando forem produzidos;
4. publicar um novo `result-only-child` atual; um `handoff-ready.json` herdado da base nunca satisfaz o terminal gate;
5. nunca selecionar `handoff-only` apenas porque existe um certificado stale de **outro** alvo.

Arquivos antigos que permanecam na base sao historicos e neutros enquanto nao forem usados como evidencia nem incluidos como resultados atuais. O certificado final deve listar/hash apenas artefatos atuais e o terminal guard deve confirmar o subject atual.

## Connector-only

Quando nao houver checkout, materializar no workspace efemero, se existirem no head remoto, `handoff-ready.json` e `specification-snapshot.json` antes da classificacao. Para distinguir heranca da base, materializar tambem os mesmos paths no **base SHA remoto exato** e passar `--base-audit-dir`; o classificador compara bytes. Nao inferir ausencia apenas porque o workspace local iniciou vazio e nao usar nome de branch como substituto do SHA remoto.

## Controle discriminante canonico

Cenario: uma branch nova para issue B nasce de uma base que contem `.audit/entregar-issue` de issue/PR A.

Implementacao errada plausivel: tratar o handoff de A como pronto para B porque os arquivos existem e seus hashes internos sao validos.

Esperado: quando os arquivos de identidade de A forem byte-identicos ao `base_sha`, classificar `inherited-base-artifact`, `reuse_allowed=false`, reconstruir o pacote de B e exigir novo result-only child antes de qualquer `Libera auditoria: SIM`. Se a branch tiver alterado qualquer artefato estrangeiro, manter `foreign-target`; nunca mascarar escrita no head como heranca da base.

## Fronteira de escopo da issue

A identidade do target nao prova autoria de todo o diff acumulado da PR. Capturar `work_item_start_sha` antes da primeira escrita material e certificar `work_item_start_sha..material_head_sha` como `issue_changed_paths`. Um path presente apenas em `base_ref..PR head` e ausente do issue-local diff e `inherited-pr-delta`: contexto historico, nao alteracao da issue corrente.
