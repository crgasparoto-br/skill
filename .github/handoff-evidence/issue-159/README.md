# Evidencias progressivas da issue #159 / PR #160

**Estado: INCOMPLETO — sem certificacao ou aprovacao independente.** Este dossie nao solicita nem concede check verde. O produtor oficial deve verificar os IDs canonicos e os testes JUnit de `manifest.json`; `review_state=incomplete` mantem o handoff bloqueado ate revisao formal de todos os requisitos e relatorios.

## Fonte e identidade da rodada

- Issue: https://github.com/crgasparoto-br/skill/issues/159
- PR: https://github.com/crgasparoto-br/skill/pull/160
- Referencia inicial de evidencia: material HEAD `7892b19723f37d52041e8b4685008418a0bba0d7`; nova escrita exige coleta no HEAD sucessor.
- Base anterior observada: `develop@3cd4b81e41fa8f726e7b3567a18c0f96c1fca741`.
- Suite: https://github.com/crgasparoto-br/skill/actions/runs/41075751524 (2886 passed; testes no HEAD anterior).
- Coleta factual: https://github.com/crgasparoto-br/skill/actions/runs/41075751763 (job tecnico verde, certificacao semantica vermelha).
- Auditoria legada: https://github.com/crgasparoto-br/skill/actions/runs/41075751533 (reprovada por falta de historico de revisao).
- REST observado: listagem de `/issues/155/comments` e GET de `/issues/comments/6525197234` retornam mesmo ID, corpo, autor e timestamps; diferem apenas em campos nao normativos como `pin`/avatar.

## Ledger: nove obrigacoes

| Obrigacao | Estado | Justificativa |
| --- | --- | --- |
| OBL-001 | Provisoriamente coberta | Causa raiz REST comparada com evidencias do comentario real e testes. |
| OBL-002 | Provisoriamente coberta | Diff do verificador remove comparacoes integrais nas quatro leituras. |
| OBL-003 | Provisoriamente coberta | Snapshot semantico, autorizacao, vinculo e watermarks preservados por testes. |
| OBL-004 | Pendente | Positivo real do check de sessao apos instalacao e revisao legitima nao observado. |
| OBL-005 | Provisoriamente coberta | Testes de adulteracao, revogacao, issue/autor e identidade. |
| OBL-006 | Provisoriamente coberta | Dupla releitura e prevalencia de rejeicao posterior testadas. |
| OBL-007 | Pendente | Certificacao semantica e auditoria GitHub exact-SHA ainda reprovadas. |
| OBL-008 | Pendente | Instalacao em develop/main so apos auditoria e autorizacao de merge. |
| OBL-009 | Pendente | Revisao da PR no contexto implementador nao equivale a parecer independente. |

Os controles provisoriamente cobertos sao apenas **rastreabilidade tecnica do HEAD anterior**, nao provas de conclusao final. Todos os campos de conclusao semantica em `reviewed-closure.json` continuam explicitamente `pending`.

## Dependencia real e ordem segura

O texto misto de OBL-004 e OBL-007 contem clausulas pre-handoff e post-integracao. O validador `reviewed_phase_decision.py` exige `scope_decision.pre_handoff_coverage` para diferir somente a parte operacional. O schema confiavel `entregar-issue/schemas/requirement-closure.schema.json` na base anterior ainda rejeita esse campo, enquanto a [PR #155](https://github.com/crgasparoto-br/skill/pull/155) o implementa e ainda esta aberta. Nao resolver essa dependencia reduzindo requisitos ou fabricando `covered`; a solucao requer integrar o ajuste validado por PR ou replanejar o fluxo de bootstrap com autorizacao explicita. A PR #155 nao e aprovada por uma reutilizacao indevida do parecer de sessao anterior.

Para encerrar: concluir dossie critico com matriz de risco, controles herdados, grounded code/test changes e hashes; obter certificado verificavel; auditoria nova em contexto separado do implementador; integrar sob autorizacao; validar sessao real sobre as bases confiaveis; manter a issue aberta ate a prova de pos-integracao.
