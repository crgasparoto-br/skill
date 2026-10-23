# Coleta e certificacao de handoff no GitHub Actions

## Quando ler este arquivo

Consultar ao coletar, certificar ou publicar evidencias de PRs com GitHub Actions em qualquer repositorio consumidor, especialmente para adaptar ferramentas de teste ou branch base.

## Índice

- [Objetivo](#objetivo)
- [Coleta autentica](#coleta-autentica)
- [Certificacao fail-closed](#certificacao-fail-closed)
- [Produtor de evidencias revisadas (Actions)](#produtor-de-evidencias-revisadas-actions)
- [Publicacao separada e autorizada](#publicacao-separada-e-autorizada)
- [Seguranca](#seguranca)
- [Reuso em repositorios consumidores](#reuso-em-repositorios-consumidores)
- [Publicador reutilizavel para repositorios consumidores](#publicador-reutilizavel-para-repositorios-consumidores)

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
   Antes dos testes, mover o checkout do tooling oficial para `$RUNNER_TEMP`:
   a arvore duplicada dentro do workspace contamina descoberta dinamica de testes,
   higiene, validacao de dependencias e generacidade do repositorio consumidor.
   Restaurar o checkout so apos os gates, para permitir o cleanup da Action.
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

## Produtor de evidencias revisadas (Actions)

O caller do repositorio `skill` executa
`scripts/produce_actions_handoff_evidence.py` apos a suite exact-SHA.
O produtor nao escolhe o perfil, nao infere historico de rejeicoes e nao marca
obrigacoes ou controles como aprovados. Sem dossie revisado, publica
`semantic-evidence-candidates.json` com candidatos factuais e
`handoff-producer-status.json` com `blocked`. O gate posterior permanece vermelho.

Para reutilizar em outros repositorios, configurar `evidence-command` no
caller `reusable-handoff.yml` com o mesmo comando e implementar o dossie
em `.github/handoff-evidence/issue-<N>/`, no SHA material da PR.
A pasta nao pode ter symlinks nem ser usada para executar codigo arbitrario.
Um dossie completo consiste em:

- `manifest.json` schema 1 com `repository`, `issue_number`,
  `pull_request_number`, `base_ref`, `head_ref`,
  `work_item_start_sha`, `evidence_profile`, `risk_justification`,
  `audit_history`, `audit_history_evidence`, `artifact_sha256`
  e `test_bindings`.
- `reviewed-closure.json` com `schema_version: 1`, `obligations`
  indexadas por `candidate_key` extraida do snapshot e `controls`
  com todas as familias canonicas. O overlay preserva campos
  imutaveis do snapshot corrente; um requisito nao registrado ou novo
  obriga revisao explicita, nunca ganha `covered` automaticamente.
- Relatorios aplicaveis (standard, matriz de ataque, saturacao, controles
  herdados, grounding, reauditoria e lineage) com hashes SHA-256 declarados
  individualmente em `artifact_sha256`. O produtor permite apenas
  nomes na allowlist e amarra campos `head_sha`/`subject_sha` e
  `base_sha` a identidades do runner; textos de prova nao podem
  conter placeholders.
- `test_bindings` associa cada requisito `covered` a casos JUnit
  positivos, negativos e de regressao **presentes e aprovados** no
  material HEAD. Isso valida apenas existencia/execucao: oraculo,
  falha discriminante e abrangencia exigem inspecao e validadores oficiais.

Exemplo de cabecalho do `manifest.json` (valores ilustrativos, nao
evidencias nem certificado):

```json
{
  "schema_version": 1,
  "repository": "owner/repository",
  "issue_number": 123,
  "pull_request_number": 124,
  "base_ref": "develop",
  "head_ref": "feat/123-example",
  "work_item_start_sha": "<SHA real ancestral da issue>",
  "evidence_profile": "critical",
  "risk_justification": "Fundamentacao revisada com referencias verificaveis.",
  "audit_history": "previous-rejection",
  "audit_history_evidence": "URL/ID da rejeicao independente e data verificada.",
  "artifact_sha256": {"reviewed-closure.json": "<SHA-256 real do arquivo>"},
  "test_bindings": {}
}
```

O exemplo e incompleto intencionalmente. O produtor rejeita
`test_bindings` faltantes, hash adulterado, caso JUnit ignorado,
perfil/historico ausente, branch/issue distintos e relatorios requeridos
ausentes. O `certification-inputs.json` so e emitido apos todas
as checagens formais do produtor; ainda nao e uma certificacao.
O veredito final permanece de `prepare_actions_handoff.py --phase certify`,
dos validadores semanticos existentes e do publicador confiavel.

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

O caller pode informar `evidence-command`: um comando do projeto consumidor,
executado apenas apos testes aprovados, sem `GITHUB_TOKEN`, para produzir
`$EVIDENCE_DIR/certification-inputs.json` e os relatorios assinados por
evidencias reais sob `$EVIDENCE_DIR/.audit/entregar-issue/`. Essa e a
interface para um produtor de evidencias especifico de tecnologia/negocio,
sem copiar validadores nem conceder privilegios de escrita. Sem produtor
configurado, o workflow preserva a coleta mas bloqueia a certificacao.

O indice de testes acelera o levantamento mas nao fecha requisitos.
`entregar-issue` deve conferir requisitos com provas positivas e negativas
autenticas. Na ausencia delas, registrar `UNKNOWN/BLOCK`, nunca `passed`.

## Publicador reutilizavel para repositorios consumidores

O publicador de fonte confiavel fica em `reusable-publish-handoff.yml`.
Cada consumidor cria um workflow chamado somente por `workflow_run` no
branch default; este e o **unico** workflow com `contents: write`.
Exemplo (arquivo versionado no branch default do consumidor):

```yaml
name: Publish certified handoff
on:
  workflow_run:
    workflows: ["Certified handoff"]
    types: [completed]
permissions:
  contents: write
  actions: read
  pull-requests: read
jobs:
  publish:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    uses: crgasparoto-br/skill/.github/workflows/reusable-publish-handoff.yml@<SHA_APROVADO>
    with:
      base-ref: develop
      producer-path: .github/workflows/certified-handoff.yml
      required-checks: "Certified handoff,CI"
```

O nome de check deve refletir workflows realmente requeridos e registrados;
todos os demais workflows de PR observados no mesmo material SHA tambem precisam
estar `completed/success`. O publicador executa validadores e `git` somente
a partir de codigo oficial vinculado ao SHA do workflow reutilizavel, checa
`workflow_run`, PR/base/head, allowlist, artefatos e hashes, simula o filho
direto de resultados e faz push fast-forward sem merge. A leitura remota
depois do push e obrigatoria. Nao executar este fluxo a partir de PR nem
habilita-lo antes de revisao e promocao autorizada ao default branch.

O pacote `certification-inputs.json`, `requirement-closure.json` e controles
adversariais continua sendo obrigatorio: indexar testes nao gera aprovacao
semantica. Ausencia de evidencia impede o workflow de producao e, portanto,
impede o publicador.
