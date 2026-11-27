# Homologacao externa atestada exact-SHA — M1 (preparacao)

## Estado e garantia

Este contrato prepara a verificacao deterministica de evidencias de comportamento
real quando um servico externo impede a automacao autorizada. Nao e uma
autorizacao para substituir checks vigentes. O M1 e uma biblioteca somente leitura,
sem coletor autenticado, workflow, check publisher, segredo ou permissao adicional.
O M2 (integracao protegida e adocao por consumidor) ainda nao esta instalado.
A [politica de GitHub Actions](../entregar-issue/contracts/github-actions-policy.md)
continua integralmente vigente. Ausencia de prova = bloqueio.

Manter separados:

- teste deterministico: codigo, contratos, seguranca, fallback, regressao e demais
  gates tecnicos executados sobre o candidato exato;
- teste externo automatizado: PASS somente quando o comportamento real exigido foi
  observado; challenge, indisponibilidade e erro indeterminado nao sao PASS;
- homologacao humana atestada: comportamento observado por pessoa em navegador
  autorizado, revisado com evidencias; nao equivale a teste automatizado;
- revisao de terceiro e contexto separado declarado pelo mesmo operador: garantias
  distintas; nenhuma equivale automaticamente a auditoria independente ou release.

## Contrato executavel M1

[external_homologation.py](../scripts/external_homologation.py) expoe
`validate_external_homologation`. Os [testes](../tests/test_external_homologation.py)
usam fixtures sinteticas; executar
`python -m pytest -q tests/test_external_homologation.py`.
A funcao compara dados fornecidos pelo futuro coletor, nao autentica fontes.
O retorno de sucesso e exclusivamente `contract-valid`, com
`automated_live_pass=false`, `source_authentication_performed=false` e
`release_gate_satisfied=false`. Qualquer erro impede a aceitacao.
Nao usar o retorno como status de GitHub, certificado ou efeito de release.

Entradas:

1. `default_policy` e `base_policy`: bytes JSON iguais, de origens confiaveis
   distintas; ausencia, divergencia e modo disabled recusam. Campos exatos:
   schema_version=1, mode=enabled, repository literal, api_origin HTTPS canonica,
   assurance, owner, reviewer,
   scenarios. Owner e reviewer contem id numerico GitHub e login. Assurance
   `owner-attested-separated-context` exige o mesmo principal; a modalidade
   `owner-attested-third-party-review` exige IDs distintos. Esta forma nao prova
   separacao de pessoas ou sessoes. Cada scenario declara origin HTTPS canonica,
   lista nao vazia de controls unicos e technical_checks (nome -> app ID positivo).
2. `identity`: repository, pull_request, issue, base_ref, base_sha, head_sha,
   merge_preview_sha, issue_sha256 e policy_sha256. Valores coletados da fonte
   autenticada atual, nunca derivados do manifesto de evidencia.
3. `facts`: api_origin identica a da politica, environment (origin, head_sha, deployment_id, tls_verified),
   external_attempt (head_sha, run_id, run_attempt, result=blocked-external,
   diagnostic_sha256), technical_checks (por nome: id, app_id, head_sha, run_id,
   run_attempt, conclusion=success). O coletor deve resolver a origem e resultado
   reais; a mera presenca destes campos nao autentica nada.
4. `manifest_raw`: bytes JSON com schema_version=1, identity exata, scenario,
   kind=human-observed-external, simulated=false, facts_sha256 (SHA-256 da
   serializacao canonica de facts), files (basename -> SHA-256), observations
   (control ID -> result=observed-pass e files nao vazios). Todos os controles da
   politica devem estar presentes. Todos os arquivos precisam existir, estar
   referenciados e coincidir byte a byte com os digests; sem extras, traversal,
   arquivos vazios ou limites excedidos. A revisao humana precisa examinar o
   conteudo, pois a funcao nao determina se uma captura mostra o comportamento.
5. `comments`: inventario autenticado completo do PR com registros imutaveis,
   incluindo ID, autor (id, login, type=User), corpo, REST URL, issue_url e
   timestamps. O registro do operador usa o prefixo
   SOLVERIT_EXTERNAL_HOMOLOGATION_V1 seguido de quebra de linha e JSON com identity,
   manifest_sha256 e decision=observed-pass. O parecer usa
   SOLVERIT_EXTERNAL_HOMOLOGATION_REVIEW_V1 e JSON com os mesmos vinculos,
   decision=approved, owner_comment_id, owner_comment_sha256 (digest do corpo
   completo), assurance e separate_context_attested=true. O parecer deve suceder
   o registro do operador. A selecao nao recua apos rejeicao, edicao ou exclusao
   observada. `watermarks` (owner e reviewer) vem do journal protegido, nao do PR.
6. `files`: mapa de bytes reais dos anexos, recuperados de fonte autenticada;
   nao aceitar somente URL/hash ou referencias do proprio candidato. JSON limitado
   a 60 KB; no maximo 16 arquivos de ate 16 MiB cada e 32 MiB no total.

A serializacao canonica usa JSON com chaves ordenadas, separadores compactos,
UTF-8 e sem NaN/Infinity. Os hashes de politica, manifesto e corpo de comentario
incidem sobre bytes originais. Hashes provam integridade, nao veracidade nem
autoridade. Fixture positiva prova consistencia, nao homologacao real.

## M2 — precondicoes para uma implementacao operacional

Nao ativar a modalidade a partir da PR que propoe a mudanca. O contrato abaixo
define precondicoes; nao declara que existe hoje um publicador autorizado.

1. Inventariar gates obrigatorios, risco, criterios da issue, logs e artefatos
   exact-head. Classificar a falha no limite externo com prova bruta, sem inferir
   bloqueio do provedor a partir de qualquer timeout. Falha funcional ou tecnica
   do candidato continua bloqueante. Preservar os testes de integracao existentes.
2. Definir a politica opt-in no consumidor, inicialmente desativada. Coletor
   protegido deve resolver default e base protegida via Git/API autenticados,
   provar arquivo regular e bytes iguais, ausencia/404 bilateral, e recusar
   divergencia, erro de leitura ou autoridade fornecida pelo candidato. Reusar as
   invariantes do [contrato de seguranca](SECURITY.md) e do
   [gate de revisao por sessao](WEB_INDEPENDENT_AUDIT.md); nao confundir seus
   diferentes escopos de autoridade.
3. Coletar identidade atual do PR, issue e especificacao, merge preview, run
   attempt, check IDs, app, evento, workflow confiavel e artefatos. Consultar
   lista paginada e detalhe de cada registro e comprovar concordancia dos campos
   de seguranca e vincular a origem canonica da API do coletor a policy.
   Verificar que o run pertence ao SHA/projeto, a cobertura dos
   gates tecnicos e o diagnostico externo bruto. Rejeitar resposta incompleta,
   check homonimo de origem distinta, replay e duas PRs abertas no mesmo HEAD.
4. Homologar em deployment HTTPS isolado e representativo, vinculado ao SHA
   congelado por metadados autenticados de build/deploy (nao mera URL, hash no
   HTML ou branch mutavel). Provar certificado valido, comportamento real e
   controles discriminantes requeridos pela issue. Nao contornar protecoes do
   provider, nao automatizar credenciais pessoais, nao enviar dados de producao
   nem incluir cookies, tokens ou PII nas evidencias.
5. Depositar manifesto e anexos sanitizados em armazenamento autenticado,
   imutavel ou identificado por versao e digest, fora da arvore candidata.
   Atestacao por conta autorizada e parecer separado vinculam exatamente os bytes.
   Journal protegido registra watermark, revogacao e nova avaliacao por eventos
   autenticados; nao recuar para aceite antigo. Verificar autorizacao atual e
   repetir identidade, policy, artefatos, registros e escopo imediatamente antes
   de qualquer efeito. Revogacao, mudanca de base, candidato, policy, issue ou
   evidencia invalida o aceite. Nao confundir reavaliacao de registros com rerun
   de CI; nunca criar novo commit somente para anexar aceite.
6. Implementar somente mediante issue e autorizacao explicita de workflows um
   coletor/publicador confiavel no default protegido, sem executar codigo do PR
   com token privilegiado. O check externo tem nome e significado distintos do
   check tecnico e do resultado automatizado. Nao criar job dependente de
   aprovacao manual, environment gate, workflow_dispatch, duplicidade de check
   ou publicacao de sucesso por comentario avulso. A origem do check e o escopo
   por PR precisam ser demonstrados, inclusive concorrencia, invalidacao,
   exclusao, colisao de HEAD e falha do coletor. Limitar escrita a checks quando
   autorizada; nao alterar permissoes/protecoes remotamente pelo controlador.
7. Migrar em duas fases, seguindo o
   [padrao de CI do consumidor](CI_POST_ORQUESTRADOR.md). Instalar e provar os
   novos checks em paralelo, com os anteriores ativos. Antes de qualquer troca
   de semantica do agregador vigente, provar que a protecao efetiva exige
   simultaneamente os gates tecnicos e externos para cada PR em cada base
   protegida; obter autorizacao especifica, read-back e testes negativos.
   Se a plataforma nao garantir a conjuncao/escopo, manter o gate original e
   o bloqueio. Nenhum fallback temporario para PASS, nem janela desprotegida.
8. Somente apos CI tecnica, prova externa autenticamente revisada e enforcement
   comprovado, seguir o fluxo de auditoria independente e readiness existente.
   A homologacao nao encerra automaticamente criterios, findings, issue ou PR.

## Procedimento enquanto M2 nao existe

Preservar os checks atuais. Registrar blocked-external com evidencia do run,
distinguir resultado humano e automatizado, manter a linhagem dos achados
e nao publicar novos commits artificiais ou repetir testes bloqueados sem
mudanca material. Concluir os controles tecnicos executaveis e documentar
o impedimento real. Nao afirmar que o contrato M1 permite liberar a entrega.
