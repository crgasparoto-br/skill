# Publicação da reconciliação de critérios de aceite

## Autoridade e momento

O auditor independente produz e valida `acceptance_criteria`, mas nunca escreve
no GitHub. `entregar-issue` pode executar esta fase somente depois de receber
um parecer autenticado e validado, ainda vinculado à issue, ao repositório e ao
SHA exato.

Executar:

```bash
python <skill>/scripts/reconcile_issue_acceptance_criteria.py \
  --audit-report <controller-audit-report.json> \
  --repository <owner/repo> \
  --issue <n> \
  --head-sha <sha> \
  --audit-report-url <https-url> \
  --required-audit-check "Verify session review (exact SHA)" \
  --apply
```

O script valida o schema canônico completo, a identidade, o estado aberto da
issue/PR, o SHA remoto, o digest do corpo, o texto e a linha de cada origem. O
nome passado em `--required-audit-check` precisa corresponder a um check verde,
terminal e único no SHA exato; um nome histórico ou uma CI verde genérica não
substitui a atestação do parecer. O review atestado declara
`audit_report_sha256`; o `output.text` autenticado do check publica no recibo
um `publication_attestation` com schema, repositório, issue, HEAD, esse digest
canônico e `accepted=true`. A divergência entre check e parecer bloqueia.
Repetir a opção para gates adicionais. Sem `--apply`, somente produz o plano
depois das leituras autenticadas.

## Registro append-only

O comentário:

- contém todas as decisões por critério, inclusive negativas, parciais e
  inconclusivas, sem convertê-las em prova;
- vincula parecer, SHA auditado, digest do contrato e evidência;
- contém fingerprint lógico versionado;
- não apaga nem edita comentários anteriores;
- rejeita duplicata lógica já existente e confirma o comentário por nova leitura
  autenticada depois da publicação;
- repete a checagem de comentário entre a última leitura e o POST, reduzindo a
  janela concorrente, e reprova duplicatas detectadas no read-back final.

Se a mesma decisão já estiver publicada com fingerprint idêntico, o resultado
é `already-published`; isso é idempotência lógica, não nova aprovação. A API
GitHub não oferece CAS para POST de comentário: executar a publicação sob um
único owner/concorrência operacional confiável. O script não remove duplicatas:
se dois publishers ultrapassarem a última checagem, o read-back falha fechado,
preservando append-only e impedindo um recibo de sucesso ambíguo.

## Corpo da issue e concorrência

Preservar o corpo da issue. GitHub não oferece, de modo comprovado neste
contrato, CAS atômico para atualizar o texto com expectativa de corpo anterior.
`--update-checkboxes` é, portanto, fail-closed e a publicação registra que a
escrita do corpo não foi tentada.

Não futuramente habilitar essa opção apenas por uma leitura seguida de
`PATCH`: isso continua sujeito a sobrescrita concorrente. Exige operação de
escrita atômica condicional demonstrada e testes de stale write. Mesmo com
CAS, somente critérios `verified` podem ser marcados; todas as demais decisões
permanecem abertas.

## Efeito da reconciliação

Comentário ou checkbox não altera o veredito, a identidade do SHA, a
aprovação independente, os gates nem a autorização de merge/fechamento. Mudança
posterior do corpo ou do HEAD exige nova auditoria/reconciliação afetada; nunca
reaproveitar o comentário como prova do material novo.
