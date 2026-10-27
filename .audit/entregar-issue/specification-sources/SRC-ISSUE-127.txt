## Contexto e decisão aprovada

Modelo: `operator-attested-session-review`. Operador: `crgasparoto-br` (GitHub ID 255721831). Bases: `develop` e `main`. PR de implementação: #128.

Decisão do proprietário em 26/10/2026, 21:13:07 UTC: “Prossiga com a implantação da sua sugestão”. Registro e transição do contrato: https://github.com/crgasparoto-br/skill/issues/127#issuecomment-6427516623.

A garantia deste modelo é revisão em contexto declarado como separado, com evidências autenticadas pelo GitHub. Não é autenticação criptográfica da identidade de outra pessoa ou da sessão ChatGPT.

## Escopo

- R127-01: Implementar o modo de sessão com declaração explícita do limite de garantia, sem confundir seu resultado com aprovação humana independente ou assinatura Ed25519.
- R127-02: Validar política optativa e conta autorizada por ID e login; política ausente, desabilitada, malformada ou conta sem autorização reprova.
- R127-03: Validar repositório, PR, issue, base ref/SHA, HEAD, merge preview e digests da issue e da política contra fontes confiáveis.
- R127-04: Reconciliar todas as obrigações extraídas pelo parser oficial com análise do revisor e trechos de fonte existentes, vinculados por linha e SHA-256.
- R127-05: Exigir controles positivos, negativos e de regressão distintos e realmente aprovados no JUnit do HEAD exato; evidência ausente, falha ou ignorada reprova.
- R127-06: Revogar parecer editado, excluído, rejeitado ou supersedido; impedir retorno silencioso a aprovação antiga; conservar fingerprint e ordem das revisões.
- R127-07: Revalidar conta, parecer, alvo, certificado e checks confiáveis antes de publicar o check específico de sessão, sem executar código da PR no verificador.
- R127-08: Produzir pacote neutro com issue, obrigações, blobs completos da base e do HEAD, diff e testes executados; rejeitar truncamento, caminhos inseguros e arquivo de evidência adulterado.
- R127-09: Executar o fluxo no ChatGPT web e em GitHub-hosted Actions, sem API de IA, VPS, runner self-hosted, segredo de IA, merge automático ou alteração automática de rulesets.
- R127-10: Documentar ativação, responsabilidades, limites de confiança, bootstrap, rollback e dois marcos de entrega; preservar as vias humana independente e Ed25519 fora do modo de sessão.

## Critérios de aceite da implementação — M1

- R127-11: Aprovar testes de contrato, controles adversariais e regressões das duas bases, análise estática, higiene e certificação exact-SHA da implementação, sem aumentar limites nem inventar provas.

## Requisitos de adoção operacional posterior ao handoff — M2

- R127-12: Executar revisão em conversa separada do SHA certificado, instalar a política nas bases confiáveis e demonstrar o novo check em um caso positivo real e negativos de adulteração, revogação e mudança de alvo.
- R127-13: Migrar develop/main para o check de sessão e contagem de reviews humanos igual a zero, preservando PR obrigatória, checks técnicos, certificação, atualização estrita e proteção contra force-push/exclusão; confirmar regras efetivas e retirar qualquer exceção temporária.

## Decisão de fase

R127-12 e R127-13 são adoção posterior ao handoff M1, autorizada pelo proprietário. Seu fechamento é `deferred` no certificado de implementação, com referência a esta decisão e `parent_issue_must_remain_open=true`, alvo #127. O certificado M1 não afirma que M2 ocorreu e não autoriza o encerramento desta issue. O proprietário conserva a decisão administrativa de instalação inicial do SHA revisado; a automação não cria seu próprio parecer nem executa merge.

## Referências e histórico

A arquitetura anterior de identidade externa/custódia obrigatória foi substituída por decisão aprovada, não declarada implementada. O contrato anterior está preservado no comentário de decisão e no artifact 12689431281 do run 40400481350. Evidências anteriores continuam históricas e não são reancoradas alterando seu SHA.

Fontes: `docs/WEB_INDEPENDENT_AUDIT.md`, `docs/SECURITY.md`, `scripts/session_review.py`, `scripts/verify_session_review.py`, `.github/workflows/session-review.yml`, `.github/session-review-policy.json`. A issue permanece aberta até adoção operacional comprovada.