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
