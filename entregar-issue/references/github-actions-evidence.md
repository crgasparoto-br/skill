# Coleta e certificacao de handoff no GitHub Actions

## Objetivo

Usar runners hospedados `ubuntu-latest` para obter a especificacao original e fatos
de testes no SHA material da PR. A VPS nao e dependencia. O workflow
`.github/workflows/handoff-evidence.yml` executa com credenciais de leitura,
sem `workflow_dispatch` ou `pull_request_target`.

## Coleta autentica

1. Conferir PR, issue, branch base `develop` e SHA original da PR.
2. Ler o corpo da issue usando a API oficial e gerar o snapshot com
   `build_specification_snapshot.py`; iniciar `requirement-closure.json` como pendente.
3. Rodar a suite no material HEAD, gravar JUnit, log, exit code e SHA-256 do log.
4. Exportar `handoff-preflight.json` e o pacote completo em Actions artifact.
   CI verde nao comprova cobertura semantica por requisito.

## Certificacao fail-closed

O modo `--phase certify` de `scripts/prepare_actions_handoff.py` valida identidade,
log e digest e exige, no mesmo diretorio efemero de evidencias,
`certification-inputs.json` mais todos os relatorios autenticos aplicaveis
em `.audit/entregar-issue/`. A coleta padrao NAO fabrica essas provas:
um produtor de entrega deve materializa-las previamente no runner da Action.

`certification-inputs.json` possui a forma:

```json
{
  "subject_sha": "<40 hex do HEAD material>",
  "work_item_start_sha": "<40 hex anterior ao trabalho>",
  "base_ref": "develop",
  "head_ref": "<branch da PR>",
  "evidence_profile": "critical",
  "audit_history": "previous-rejection",
  "remediation_mode": "targeted-remediation"
}
```

O perfil deve refletir o risco real, nao um valor escolhido para liberar o gate.
Para cada perfil, entregar `specification-snapshot.json` e `requirement-closure.json`;
no `standard`, tambem `standard-evidence.json`; no `critical`, a matriz
de ataques, saturacao e controles herdados. Mudancas de codigo/testes exigem
`codebase-grounding.json` e, para codigo, `code-growth.json` de `CODE-GROWTH-001`.
Quando houver rejeicao independente, anexar `audit-remediation.json`,
`audit-source-result.json`, `learning-closure.json`, `audit-escape-closure.json`
e snapshot historico imutavel. Remediacao sistemica exige tambem a historia
de controles herdados, nos termos de `handoff-certificate.md`.

O gate executa `build_handoff_certificate.py` e
`validate_handoff_certificate.py` SOMENTE apos confirmar
identidade e precondicoes. Nunca marcar requisitos automaticamente
como `passed`, converter `UNKNOWN` em `not-applicable` nem usar
somente log/contagem de testes como prova discriminante.

Enquanto faltarem provas, o passo de certificacao reprova a Action, mas
a etapa de upload `if: always()` preserva `handoff-certification-status.json`
com o bloqueio explicito e os logs para remediacao no mesmo SHA.

## Publicacao separada e autorizada

Um certificado `certificate-generated` no artifact AINDA NAO esta publicado.
O token com `contents:write` nao pode ser passado ao job de PR que executa
codigo do head; usar publicador isolado de fonte confiavel, revalidando os
bytes do artifact, a identidade remota fresca, o filho direto
`result-only-child`, a allowlist e `validate_terminal_handoff.py`.
Nao emitir `READY` nem convocar `auditar-issue` antes da verificacao
pos-publicacao em chamada remota independente.

## Seguranca

- Runners GitHub-hosted, checkout do SHA material, nenhuma dependencia de VPS.
- Forks e identidade ambigua bloqueados; token usado apenas para ler a issue.
- Falha de download, teste, proveniencia, risco, auditoria ou certificado
  permanece `BLOCK/UNKNOWN`. Nunca introduzir credenciais de escrita no job PR.
- O certificado e um hash das provas, nao uma avaliacao independente.
- Nao registrar secrets, credenciais ou logs com dados sensiveis no artifact.
