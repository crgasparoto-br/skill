# Reconstrucao Git offline a partir de artefato de CI

## Quando usar

Usar quando um checkout Git confiavel e obrigatorio para `validate_audit_completeness.py`, mas o runtime de auditoria nao resolve DNS ou nao pode usar `git clone`/`git fetch` remoto. Esta e uma alternativa de **transporte de objetos Git**, nao um novo modo de auditoria nem uma dispensa do gate.

## Ordem obrigatoria

1. Resolver a PR pelo conector GitHub autenticado e congelar `repository`, `base_ref`, `base_sha`, `head_sha`, o workflow requerido e o run ID. Confirmar que o run oficial esta `completed/success` e corresponde exatamente ao `head_sha`, sem confiar no texto da PR ou no arquivo a baixar. Registrar identificador do artefato e URL do run. O mesmo vale para a classificacao previa `native-github-audit` versus `certified-handoff`.
2. Consultar os artefatos do run exato e procurar um arquivo ja publicado contendo `manifest.json` e `repository.bundle`; o nome do artefato e apenas um indice, nunca evidencia de vinculo. Nao criar/alterar workflow, nao disparar jobs, nao solicitar mudanca no produto para produzir esse arquivo.
3. Baixar pelo conector GitHub usando o artifact ID confirmado. Materializar o ZIP de bytes integrais em workspace efemero; rejeitar link expirado, output parcial, resumo, caminho deduzido de nome ou conteudo nao transferivel. Nao obter bytes do candidato por anexo de PR ou descricao sem origem CI autenticada.
4. Executar o restaurador com os valores coletados **independentemente** do ZIP:

   ```sh
   python <AUDIT_SKILL_ROOT>/scripts/restore_ci_git_bundle.py \
     --archive <downloaded-ci-artifact.zip> \
     --output <ephemeral>/trusted.git \
     --repository <owner/repo> --base-ref <trusted-base-ref> \
     --trusted-base-sha <trusted-github-base-sha> \
     --trusted-head-sha <trusted-github-head-sha> \
     --run-id <trusted-github-run-id>
   ```

5. O script exige estrutura ZIP restrita, identidade `schemaVersion/repository/baseRef/baseSha/headSha/runId`, refs Git publicadas `refs/ci-verification/base` e `refs/ci-verification/head`, objetos reais de commit, verificacao de integridade `git fsck` e diff de tres pontos. Ele falha com codigo 2 sem criar checkout validado quando qualquer condicao nao bate. O retorno `git_repo` e um repositorio **bare** local, valido para `git -C ... diff` e para `--git-repo` do gate. Para ler arquivos sem mudar o candidato, usar `git --git-dir <ephemeral>/trusted.git show <SHA>:<path>` ou criar worktree efemera.
6. Construir **independentemente** `inventory.json`, `report.json`, provas com hashes e revisao de **todos** os changed paths segundo `references/audit-completeness-gate.md`. Executar o portao existente:

   ```sh
   python <AUDIT_SKILL_ROOT>/scripts/validate_audit_completeness.py \
     --inventory <ephemeral>/inventory.json \
     --report-json <ephemeral>/report.json \
     --root <ephemeral> --git-repo <ephemeral>/trusted.git \
     --trusted-base-sha <trusted-github-base-sha> \
     --trusted-head-sha <trusted-github-head-sha> \
     --head-sha <trusted-github-head-sha>
   ```

7. Confrontar `changed_paths` recomputados com o snapshot remoto e os registros de cobertura; validar o parecer e reconsultar a PR no fim. Se base ou HEAD mudou, invalidar provas antigas. **CI verde e integridade Git nao provam sozinhos completude, correção funcional nem independencia.**

## Falhas e precedencia

- Usar checkout confiavel ja existente quando disponivel; caso contrario tentar o artefato Git Bundle publicado no run exato antes de declarar limitação causada apenas pelo DNS do runtime.
- Nunca aceitar SHA ou run ID unicamente do manifesto dentro do ZIP. A prova de procedencia e composta por **conector GitHub autenticado + identidade do run/artefato + SHAs confiaveis + objetos Git validados**. Nao aceitar ZIP manual, PR attachment ou job de SHA diferente como substituto.
- Se o CI nao publicar bundle, o conector nao transferir os bytes ou faltar evidencia remota confiavel, preservar `audit-runtime-limitation`/`INCONCLUSIVA` quando a limitacao for do auditor. Nao reprovar a issue pelo DNS e nao dispensar `validate_audit_completeness.py`.
- Bundle restaurado nao altera a classificacao de transporte `certified-handoff`/`native-github-audit`, nem autoriza auditoria de implementacao no mesmo contexto como se fosse independente, merge ou release automaticos.
