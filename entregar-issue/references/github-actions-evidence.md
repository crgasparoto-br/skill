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

O certificado `certificate-generated` no artifact ainda NAO esta publicado.
O workflow `.github/workflows/publish-handoff.yml` usa `workflow_run` e
somente codigo carregado do default branch; sua primeira ativacao exige
que a alteracao seja aprovada e integrada ao default branch por um fluxo
de release autorizado. Ele nao executa codigo da PR com token de escrita.

A publicacao automatica exige: CI material terminal verde, leitura
fresca de PR e HEAD, validacao independente do artifact no runtime
confiavel, copia apenas de caminhos allowlisted, simulacao
`validate_terminal_handoff.py` do commit filho local, push fast-forward
sem force ou merge, releitura GitHub apos a escrita e gate terminal real.
O SHA do filho nao altera o SHA material certificado.

Enquanto a evidencia semantica ainda nao foi produzida, a certificacao
reprova e o `workflow_run` nao publica. Nao emitir `READY` nem
convocar `auditar-issue` apenas pelo status verde do coletor.

## Seguranca

- Runners GitHub-hosted, checkout do SHA material, nenhuma dependencia de VPS.
- Forks e identidade ambigua bloqueados; token usado apenas para ler a issue.
- Falha de download, teste, proveniencia, risco, auditoria ou certificado
  permanece `BLOCK/UNKNOWN`. Nunca introduzir credenciais de escrita no job PR.
- O certificado e um hash das provas, nao uma avaliacao independente.
- Nao registrar secrets, credenciais ou logs com dados sensiveis no artifact.

## Reuso em repositorios consumidores

O workflow `reusable-handoff.yml` e acionado com `workflow_call`; cada projeto
mantem apenas um caller, referenciando uma revisao aprovada do repositorio
oficial `skill`. A revisao do codigo dos validadores e vinculada ao
`job.workflow_sha`, enquanto o alvo auditado e o checkout do SHA da PR
do repositorio consumidor.

Exemplo Python:

```yaml
name: Certified handoff
on:
  pull_request:
    branches: [develop]
permissions:
  contents: read
  issues: read
  pull-requests: read
jobs:
  handoff:
    uses: crgasparoto-br/skill/.github/workflows/reusable-handoff.yml@<SHA_APROVADO>
    with:
      base-ref: develop
      install-command: "python -m pip install -r requirements.txt"
      test-command: 'python -m pytest -vv --junitxml="$EVIDENCE_DIR/pytest-exact-head.xml"'
```

Projetos Node/React podem configurar `install-command: npm ci` e executar
seus testes com um reporter JUnit apontando para
`$EVIDENCE_DIR/pytest-exact-head.xml`. O arquivo e contrato de resultado,
nao dependencia de pytest. O indice `test-candidate-index.json` contem
nomes, status e hash do JUnit, mas `requirement_mapping=UNKNOWN` ate
que controles discriminantes comprovem a cobertura de cada requisito.

`base-ref` e parametrizavel, com `develop` padrao na SolverIT. Nao
conceder tokens de escrita ao job do PR. O publicador atual e especifico
do repositorio `skill`: outro consumidor precisa configurar um processo
separado, de fonte confiavel, com seus checks obrigatorios e autorizacao
de release; nunca copiar uma credencial privilegiada para o workflow de PR.

O indice de testes acelera o levantamento mas nao fecha requisitos.
`entregar-issue` deve conferir requisitos com provas positivas e negativas
autenticas. Na ausencia delas, registrar `UNKNOWN/BLOCK`, nunca `passed`.
