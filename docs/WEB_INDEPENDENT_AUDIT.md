# Auditoria independente 100% web — issue #127

## Decisao arquitetural

Toda execucao acontece no GitHub Actions, em runners hospedados pelo GitHub, sem VPS, servico local, DNS proprio ou runner self-hosted. A PR #126 foi certificada mas o gate atual `Verify independent audit (exact SHA)` exige GitHub review de outro colaborador. A conta pessoal unica nao pode satisfazer esse contrato. **Nao** converter o usuario implementador em aprovador e nao marcar sucesso com um artefato gerado pelo candidato.

## Limite de confianca

Uma GitHub App instalada no mesmo repositorio nao cria, sozinha, independencia: o administrador unico pode editar workflows, variables, environments e secrets. O fluxo deve distinguir:
- `technical_pass`: GitHub Actions authenticado no SHA exato.
- `certified`: evidencia semantica revisada e certificado verificavel no SHA exato.
- `independent_approved`: analise separada, somente leitura, com relatorio assinado por chave nao controlada pela implementacao e auditoria autenticada.
- `release_eligible`: todos os gates e protecoes efetivamente ativos, sem bypass.

## Arquitetura-alvo

1. Checkout da policy pelo base SHA confiavel, nao pelo HEAD da PR. GitHub Actions `ubuntu-latest` com `permissions: contents: read, pull-requests: read, checks: read, actions: read`.
2. O coletor existente gera snapshot da issue, diff, fonte, JUnit, hashes e certificado exact-SHA. O auditor nao recebe a narrativa nem resultados de conclusao do implementador.
3. Um **auditor externo isolado** (GitHub-hosted job distinto, identidade de servico ou API de modelo configurada na UI do GitHub) examina os bytes reais e publica findings estruturados. Segredos de assinatura nao podem estar no workspace do HEAD da PR, nem nos logs, nem ser acessiveis por job de codigo nao confiavel.
4. O relatorio de auditoria e assinado com Ed25519; reutilizar `auditar-issue/references/external-audit-contract.md`. A chave publica e o registro de confianca pertencem a politica confiavel preestabelecida, fora do HEAD candidato. Verificar escopo, assinatura, revogacao, origem, identidade do contexto, base, SHA e resultado.
5. O workflow de gate deve aceitar **ou** review humano independente com contrato atual **ou** auditoria externa assinada com a mesma exigencia de testes e certificado. Se faltar chave, executor, atestacao ou prova, resultado `failure` — nunca `success` ou `skipped`.
6. Em cada verificacao, consultar novamente PR, SHAs, checks e identidade de auditor para evitar TOCTOU. Um push invalida o resultado anterior.
7. Corrida paralela da via nova e atual, controles positivos e negativos reais, migracao de required checks somente depois da prova. Reativar regras `develop` e `main` e validar efetividade antes de qualquer merge.

## Provisionamento exclusivamente web

- Criar configuracao do auditor e credenciais pela UI de GitHub Actions Secrets/Variables, nao em VPS.
- Preferir assinador com chave nao exportavel/armazenada fora da superficie que executa codigo da PR. GitHub Actions Secrets sozinho **nao comprova** independencia de um administrador unico.
- Habilitar a app/servico e registrar a chave publica antes do primeiro ciclo. Incluir rotacao e revogacao.
- A documentacao e a CI nao devem fingir que esse provisionamento ocorreu. **Sem identidade/segredo real e atestacao, a etapa final permanece bloqueada.**

## Plano de migracao de PR #126

- Preservar `be63a610027743ce0a440429410e2511fac34668` como historico, mas usar o HEAD real no momento do teste.
- Verificar `Structure and tests`, `Offline authorization tests`, `collect / Require certified semantic handoff (exact SHA)`.
- Executar um parecer externo real de `auditar-issue`, independente do implementador, sem claims fabricados; confirmar o mesmo SHA.
- Validar que injetar assinatura falsa, self-review, usuario bot/implementador, mudar SHA ou alterar o proprio workflow nao libera.
- Somente apos validar o novo gate e restaurar rulesets, promover mudancas. Nao fazer merge automatico.

## Criterios de evidencia

Para cada PR, armazenar identificador do run, SHA, hash dos artefatos, chave publica/key ID, origem do veredito, contrato assinado e resultado da verificacao. Relatorios e logs nao podem conter tokens ou chave privada. Registro de falha deve mostrar qual requisito faltou, evitando loops de auditoria sobre evidencia ja certificada.


## Componentes web implementados

O produtor .github/workflows/produce-independent-audit.yml utiliza workflow_run de uma coleta exact-SHA certificada, faz leitura somente de issue/diff/fontes pinadas via GitHub API, chama modelo de IA independente e emite parecer Ed25519. O publicador .github/workflows/publish-independent-audit-check.yml revalida o workflow de origem, a assinatura, alvo material e checks tecnicos antes de publicar o check Verify independent web audit (exact SHA) associado ao commit material. A verificacao manual verify-signed-external-audit.yml nao substitui esse check.

Todos usam GitHub-hosted ubuntu-latest. Nenhuma VPS, DNS proprio ou runner self-hosted e necessario.

## Configuracao web do ambiente independent-auditor

Pela interface GitHub Settings > Environments > independent-auditor, cadastrar:
- Secret OPENAI_AUDITOR_API_KEY: chave do provedor de inferencia; pode gerar custo por token.
- Variable OPENAI_AUDITOR_MODEL: modelo com suporte a resposta estruturada JSON.
- Secret AUDITOR_PRIVATE_KEY_PEM: chave privada Ed25519, nunca versionada ou compartilhada com implementador.
- Variable AUDITOR_KEY_ID: identificador da chave confiavel.
- Secret TRUSTED_AUDITORS_JSON: registro publico de auditores ja confiados e autorizado para o repositorio. Disponibilizar tambem ao workflow publicador.

Gerar par e registro pelo contrato oficial auditar-issue/references/external-audit-contract.md. Configuracao de Secrets na mesma conta protege contra codigo de PR, mas NAO garante independencia administrativa absoluta contra o unico administrador. Para essa garantia e necessaria custodia separada.

## Migracao controlada

1. Concluir CI, certificacao e auditoria dos proprios componentes. Falta de dossie exige fechamento real, nunca marcar passed por reflexo da CI.
2. Publicar os workflows de policy na branch default de forma autorizada. Enquanto permanecerem apenas na PR, nao sao workflows de producao acionaveis.
3. Configurar os Secrets/Variables e realizar um teste de auditoria real, mais controles negativos: assinatura alterada, chave sem confianca, SHA/base/merge divergentes, artifact adulterado, workflow de origem estrangeiro e findings pendentes.
4. Confirmar check no SHA exato e comparar com o gate antigo. So entao substituir no ruleset a revisao incompatível com operador unico pelo check independente autenticado, preservando os demais checks tecnicos e protecao contra exclusoes/force push.
5. Confirmar regras efetivas em develop/main antes de liberar merge. Nao executar merge automatico.

Falhas de credenciais, origem, evidencias ou validacoes devem retornar BLOCK sem nova auditoria recursiva. Apenas nova evidencia, configuracao ou novo SHA justificam outra tentativa.
