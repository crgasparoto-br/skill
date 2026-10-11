# Gate de completude de pendências de auditoria

## Entrada e escopo

Ativar para "implementar pendências", "corrigir todos os achados", "finalizar auditoria" ou solicitação equivalente. Fixar repositório, PR, base, HEAD, rodada da auditoria e `rejection_id` quando existente. Consumir **todos** os achados da rodada, comentários de revisão materialmente relevantes e requisitos vinculados, não apenas o primeiro blocker. Diferenciar `blocking`, `actionable-recommendation`, `optional-recommendation`, `out-of-scope` e `invalid-finding`. Justificar com evidência qualquer exclusão; não ampliar unilateralmente o escopo da issue.

## Ledger obrigatório

Manter para cada achado: `finding_id`, fonte/rodada, requisito/critério de aceite, classificação de aplicabilidade, evidência reproduzível, arquivos/ação planejados, prova negativa (quando aplicável), teste/validação executada, status e HEAD exato. Estados: `open`, `implementing`, `implemented-unverified`, `verified`, `blocked`, `not-applicable`. Não transformar "implementado" em "verified" antes das verificações correspondentes. Se nova auditoria reabrir achado, retornar para `open` com nova evidência.

Reconciliar todos os itens do ledger depois de cada alteração material, antes de congelar e antes da resposta. Ausência de item da rodada anterior é falha de completude.

## Barreira de encerramento

É proibido responder `CONCLUÍDO` quando:
- houver qualquer item aplicável diferente de `verified`;
- houver pendência acionável ainda não justificada;
- o CI obrigatório do HEAD material estiver `queued`, `in_progress`, falho ou não observado;
- as evidências não corresponderem ao HEAD corrente;
- a auditoria independente exigida para aprovação final ainda não tiver ocorrido ou for desfavorável.

A saída `INTERNAMENTE VERIFICADO — AGUARDA AUDITORIA INDEPENDENTE` é permitida quando todos os achados aplicáveis estiverem verificados e o CI exact-HEAD estiver verde, mas sem independência comprovada. Não simular independência no mesmo contexto. A skill entregar-issue prepara e encaminha à auditar-issue; a confirmação de aprovação final pertence à auditoria em contexto separado.

## Continuidade e bloqueio legítimo

Quando o CI estiver pendente, respeitar ownership de `corrigir-ci` e `finalize-after-ci`, sem encerrar a entrega por impaciência. Após falha, corrigir e repetir o ciclo, dentro dos limites de segurança, permissão e orçamento do controlador. Não fazer polling infinito nem alegar trabalho em background. Se a execução não puder continuar por limitação real de ferramenta, autorização, custo, contexto ou dependência: saída `PARCIAL` ou `BLOQUEADO`, listando IDs remanescentes, tentativas, evidência e ação concreta necessária. Nenhum item desaparece do ledger.

## Teste adversarial mínimo

Reproduzir a regressão PR #1316: auditoria com três achados aplicáveis; implementar apenas um, publicar commit e iniciar CI. A barreira deve **rejeitar** `CONCLUÍDO` e manter os outros dois como `open`; se CI estiver pendente, também rejeitar `verified` terminal. Caso irmão: todos os achados verificados e CI verde, mas auditoria independente ausente -> apenas `INTERNAMENTE VERIFICADO`. Caso irmão: requisito de outra fase comprovadamente fora do escopo -> `not-applicable` justificado, não bloquear os itens realmente contratados.

## Validador determinístico e origem confiável

O ledger editável pelo implementador **não** é fonte confiável de completude, CI ou aprovação. O gate deve obter **independentemente**, por integração autenticada, antes da validação:
- manifesto da rodada de auditoria com `repository`, `pr_number`, `audit_round` e lista completa `finding_ids`; nunca construir esse manifesto a partir do ledger do implementador;
- atestação com os mesmos identificadores, `head_sha`, mapa `verified_findings` (ID -> SHA), `accepted_exclusions`, `ci` (`head_sha`, `conclusion=success`, `run_url`) e `independent_audit=approved`, `auditor`, `implementer`, `audit_url`.

O controlador deve verificar contra GitHub API autenticada os IDs/revisões de auditoria, os checks obrigatórios, o HEAD real da PR, os URLs de execução, a identidade do auditor e sua separação do implementador; verificar também a origem de cada evidência e se o review trata do HEAD exato. URLs e campos JSON não são prova por si só. Arquivos de atestação só podem ser fornecidos ao validador pelo componente de verificação independente, jamais por arquivos controlados pelo executor. Sem cadeia de confiança verificada, devolver `NAO_CONCLUIDO` ou `INTERNAMENTE VERIFICADO`, nunca aprovação final.

Executar após verificação externa:

```bash
python entregar-issue/scripts/validate_finding_completion.py ledger.json --manifest manifest-verificado.json --attestation atestacao-verificada.json
```

O validador executa apenas a reconciliação determinística; **não autentica** as fontes JSON. Seu exit code zero somente autoriza `CONCLUIDO` quando a procedência e todas as evidências tiverem sido verificadas fora do processo. Sem verificador operacional disponível, bloquear conclusão final. Nunca fabricar aprovação independente. Toda recomendação opcional fora da entrega exige status `not-applicable`, justificativa e aceitação do auditor.

## Verificador operacional GitHub

Usar `verify_github_completion.py` com `GH_TOKEN` de leitura autenticado e nomes reais dos required checks. O processo consulta a PR no GitHub, confirma `develop`, HEAD, autores de commits, aprovação em review separado e check-runs no SHA. O auditor independente deve publicar em review **APPROVED** no HEAD uma linha `SOLVERIT_AUDIT_JSON:{"schema":"solverit-audit-v1","audit_round":"...","head_sha":"...","finding_ids":["..."],"verified_finding_ids":["..."],"accepted_exclusions":[]}`. Não aceitar manifesto enviado pelo executor. Exemplo:

```bash
python entregar-issue/scripts/verify_github_completion.py ledger.json --required-check "Structure and tests" --required-check "Validate GitHub Audit MCP"
```

Usar os nomes efetivos de checks exigidos pela proteção da branch; não inferir que exemplos são as regras atuais. Quando a auditoria não contiver esse contrato ou não houver aprovação independente, a execução falha fechada. O contrato somente comprova decisão do reviewer, e o reviewer deve verificar as evidências substanciais antes de emitir a aprovação.
