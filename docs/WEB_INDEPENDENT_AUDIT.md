# Revisao web para operador unico, sem API de IA

## Decisao de garantia

Uma conta GitHub nao comprova que duas pessoas diferentes revisaram o codigo. Um hash, uma chave gerada pelo implementador ou uma URL de conversa tambem nao comprovam essa separacao. O modo novo chama-se **operator-attested-session-review**, nunca auditoria criptograficamente independente.

A revisao e feita no ChatGPT web, em contexto separado. O operador declara essa separacao e responde por ela. O GitHub autentica a conta que depositou o parecer, verifica os vinculos das evidencias e registra um recibo no SHA exato. Nao ha API de IA, VPS, runner self-hosted, chave de API ou chave privada nesse modo.

Esta e uma alternativa **optativa de governanca**, nao um contorno do gate existente. A politica [.github/session-review-policy.json](../.github/session-review-policy.json) nasce desativada. O fluxo de review humano independente e a via Ed25519 existentes permanecem intactos. Nenhum check de nome "independent audit" recebe sucesso com uma declaracao de operador unico.

## Componentes

- [session_review.py](../scripts/session_review.py): contrato estrito, identidade, autoria, cobertura, provas e revogacao.
- [verify_session_review.py](../scripts/verify_session_review.py): coleta autenticada no GitHub, reuso dos validadores oficiais, JUnit real, fontes completas e publicacao do check `Verify session review (exact SHA)`.
- [session-review.yml](../.github/workflows/session-review.yml): execucao deterministica com permissao de leitura e escrita exclusivamente em Checks; nao executa codigo do candidato.
- [prepare-neutral-audit-packet.yml](../.github/workflows/prepare-neutral-audit-packet.yml): pacote neutro com issue canonica, obrigacoes, fontes de base/HEAD, diff recomposto dos blobs e testes efetivamente aprovados.

A coleta nao inclui a narrativa da PR ou comentarios do implementador. O diff e recomposto a partir dos blobs completos, em vez de aceitar patches truncados da API. Fontes removidas aparecem sob `base/`, fontes correntes sob `head/`.

## Fluxo sem dependencia circular

`Implementacao -> testes e dossie semantico -> certificado -> conversa revisora -> comentario de parecer -> verificador deterministico`.

O certificado nao depende do comentario de aprovacao. O comentario nao cria commit. O verificador nao chama IA, nao corrige codigo, nao dispara testes e nao pede outra auditoria para aprovar a primeira. Um recibo com o mesmo fingerprint pode ser reutilizado depois de revalidar as fontes mutaveis.

O executor e o coletor de pacote nao oferecem `workflow_dispatch`: uma branch selecionada no despacho nao pode escolher o codigo executado pelo publicador. Os eventos `issue_comment` e `workflow_run` carregam o workflow da branch default protegida; `pull_request_target` usa a base protegida e `push` se restringe a `develop`/`main`. Instalar a mesma versao revisada nas bases e na default continua sendo precondicao administrativa, anterior ao uso.

Depois de um run bem-sucedido de `Collect and certify exact-SHA handoff`, o workflow `Prepare neutral independent audit packet` gera o pacote. Para solicita-lo novamente pela interface web, publicar na PR um comentario contendo somente `/solverit-audit-packet`. Abrir o run correspondente em Actions e baixar o artifact do pacote; conferir nele repositorio, PR, issue e SHAs antes de entrega-lo a conversa revisora. O comentario solicita coleta, nao constitui parecer nem aprovacao. Falha de identidade, certificado ou politica impede produzir pacote apto.

O certificado de handoff emitido por GitHub Actions associa o merge preview
ao HEAD e a base materiais. O valor do evento pode estar atrasado durante a recomputacao do merge
ou ser explicitamente `null` no evento `pull_request.opened`.
Somente o modo de leitura confiavel, autenticado e com pais verificados
pode resolver esse `null`; campo ausente, valor nao nulo malformado
ou replay offline sem preview valido continuam bloqueando. Antes dos
testes do candidato, o produtor confiavel
ativa `SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW=1` com `GITHUB_TOKEN` somente
leitura, valida pela API autenticada a PR e o objeto Git de merge, e confirma
os pais ordenados (base, HEAD). Grava um evento minimo normalizado nas
evidencias, usado na certificacao material posterior sem repassar o token ao
passo que roda depois dos testes. O job confiavel separado de certificacao
exige novamente a consulta autenticada, a mesma identidade e o mesmo preview,
rejeitando adulteracao do evento normalizado pelo candidato, incluindo
titulo, corpo, numero, issue implicita, base e HEAD originais. As consultas
admitem ate quatro tentativas; ausencia, mudanca de alvo ou objeto antigo
bloqueiam. Replays historicos literais rodam com ambiente sanitizado e nao
reivindicam autoridade para publicar checks.
Se a base ou HEAD mudar, produzir novo certificado e parecer para a
identidade atual; nenhum preview antigo e prova transferivel.

O leitor confiavel recompõe o evento consultando a PR e os objetos Git autenticados.
O preview original do artifact continua sendo validado pelo certificador oficial.
No job de certificacao independente, o snapshot pre-testes conserva o preview
inicial; se o preview utilizado no certificado ou o preview atual diferirem,
o gate confiavel autentica os tres commits Git, os pais ordenados [base, HEAD]
e a tree identica, sem modificar o artifact bruto nem liberar CI incompleta.
Se o certificado tiver sido construido com um terceiro SHA de preview, o leitor
verifica tambem esse objeto Git contra base, HEAD e tree autenticados, sem
alterar o evento original do artifact: usa apenas uma copia temporaria para
o validador legado e registra as tres identidades no recibo.
Se o GitHub recriar o merge sintetico, a reconciliacao e admitida SOMENTE quando
os dois commits Git autenticados possuirem os mesmos dois pais ordenados
(base, HEAD) e exatamente a mesma tree. O SHA original permanece na
identidade do parecer; o pacote registra SHA original, SHA atual, tree,
pais ordenados, digest do evento original e digest ZIP do artifact. Outros
campos do evento normalizado devem coincidir sem substituicao. Base, HEAD,
issue, autor, certificado e testes permanecem exact-SHA, e o leitor reconsulta
o preview imediatamente antes de emitir sucesso. Um commit Git nao encontrado,
parentes invertidos, tree alterada ou base/HEAD movidos bloqueiam. A mudanca
exclusiva de timestamp do commit sintetico nao provoca recertificacao circular.

Somente uma alteracao material ou uma evidencia realmente diferente exige nova revisao. Findings sao consolidados na mesma rodada. Credencial, dossie ou permissao ausente gera BLOCK com causa concreta, nao um ciclo automatico de tentativa.

## Contrato do parecer

Depositar um comentario na PR cujo corpo comece com `SOLVERIT_SESSION_REVIEW_V1`, seguido de quebra de linha e um unico objeto JSON. Nao publicar esse marcador como parte de narrativas ou exemplos operacionais na propria PR.

O JSON usa `schema_version=1`, `identity`, `assurance`, `acknowledgement`, `sessions`, `conclusion`, `blocking_findings`, `limitations` e `requirements`.

Copiar `identity` do pacote autenticado: repositorio, PR, issue, base ref/SHA, HEAD, merge preview e digests de issue/politica. `assurance` e `operator-attested-session-review`; `acknowledgement` e `separate-context-declared-not-cryptographically-proven`.

No contrato v1 original, `sessions.implementation` e `sessions.audit` sao
referencias reais de conversas fornecidas pelo operador, diferentes entre si,
com `separate_context_attested=true`. O programa **nao autentica sessoes
ChatGPT**; sao declaracoes de processo. Nao inventar IDs de conversas.

### Recuperacao honesta da implementacao quando a conversa foi perdida

A alternativa opcional **nao recria a conversa original**. A politica
`.github/session-review-policy.json`, identica na default `main` e na base
confiavel da PR, precisa declarar explicitamente
`"implementation_provenance":{"mode":"enabled","type":"github-implementation-provenance"}`.
Campo ausente, `disabled` ou forma invalida recusam o novo tipo. A politica
editada na propria branch da PR nao autoriza sua revisao. O contrato de duas
referencias reais v1 permanece aceito, mesmo com a alternativa ativada.

Na revisao da PR cujo material original ainda esteja certificado, obter
`implementation_provenance` do **pacote neutro autenticado**, nao de um
comentario do implementador, e informar em `sessions`:

```json
{
  "implementation": {
    "type": "github-implementation-provenance",
    "original_session_unavailable": true,
    "github": "<copiar o objeto implementation_provenance do pacote neutro>"
  },
  "audit": "https://example.com/REFERENCIA-REAL-DA-CONVERSA-AUDITORA",
  "separate_context_attested": true
}
```

O valor de `github` no exemplo e um marcador documental, nao um objeto valido;
na publicacao deve ser substituido pelo objeto JSON completo autenticado.
O operador afirma honestamente que o chat original nao esta disponivel e
indica uma conversa auditora real, efetivamente separada, com referencia
fornecida por ele. A implementacao jamais emite a propria aprovacao.

O leitor reconsulta a PR/issue, a lista integral de commits materiais e cada
objeto Git de commit da base ao HEAD, exigindo cadeia linear ordenada,
sem lacunas ou pais divergentes, mais o artifact de handoff autenticado,
digest ZIP, certificados e checks tecnicos no SHA material. Merge commits ou
historico nao linear nao sao automaticamente aceitos por essa via restrita;
exigem uma evolucao explicitamente revisada da regra, nao inferencia.
Compara todos os campos do registro recuperado ao fato autenticado e repete
a leitura antes de emitir sucesso. Nao confundir a identidade GitHub do autor
com identidade de outro auditor, nem deduzir a existencia de sessao ChatGPT.
A garantia permanece `separate-context-declared-not-cryptographically-proven`.

A auditoria continua cobrindo **cada** obrigacao canonica com analise propria,
fontes `path/start_line/end_line/sha256` no HEAD/base e tres casos JUnit
distintos, aprovados no SHA material: positivo, negativo e regressao.
Ausencia de referencia auditora, falsa atestacao, comentário alterado/excluido,
issue/PR/HEAD incorretos ou handoff sem comprovacao deixam o check bloqueado.

Cada item de `requirements` deve ter o `candidate_key` canonico, uma `analysis` propria, `sources` e `controls`. Cada fonte aponta `path`, `start_line`, `end_line` e SHA-256 do trecho unido por `\n` sem quebra final. Cada controle informa `kind`, `test_case_id` e `rationale`. Exigem-se tres casos distintos: `positive`, `negative` e `regression`, presentes como passed no JUnit do SHA material. Isso verifica vinculos, nao substitui a avaliacao semantica do revisor.

O resultado aprovado exige `conclusion=approved`, `blocking_findings=[]` e `limitations=[]`. Parecer incompleto, anterior ao certificado, editado, de conta nao autorizada ou vinculado a outro alvo nao aprova. A edicao/exclusao revoga o parecer; publicar novo comentario em vez de alterar um aprovado. Um parecer rejeitado mais recente impede voltar a uma aprovacao antiga. Os eventos usam fila explicita `queue: max`, evitando a substituicao silenciosa do evento pendente pela politica padrao de concorrencia do GitHub. A fila da plataforma tem limite de 100 pendencias; cancelamento administrativo ou falha de entrega de eventos exige revalidacao operacional, nao uma alegacao de independencia criptografica.

Esse limite de eventos pendentes nao limita o historico de pareceres no mesmo SHA a 100 registros. O verificador pagina o historico e preserva a ordem das revisoes ao revalidar e reutilizar o check. O orcamento existente de coleta e de 25 paginas, com ate 2.500 registros; inventario maior, truncado ou alterado durante a leitura e recusado explicitamente, sem deixar um novo check pendente nem aceitar historico parcial. A identidade capturada no inicio, o pacote preparado, a leitura final e o SHA de publicacao devem coincidir; qualquer mudanca interrompe a aprovacao.

O comentario da PR e comparado por um snapshot semantico explicito entre a listagem e a consulta individual: ID, corpo integral, autor (ID, login, tipo), URLs REST canonicas de comentario e `issue_url` vinculado a PR autenticada, e timestamps de criacao/atualizacao. Os campos de apresentacao `pin`, `user.avatar_url` e detalhes de `performed_via_github_app` nao alteram a autoridade do parecer e podem diferir entre endpoints. O mesmo snapshot e conferido novamente depois da revalidacao de identidade, permissao, evidencias e ordem dos pareceres, imediatamente antes da publicacao do check. Alteracao material, edicao, exclusao, perda de permissao ou parecer posterior invalido mantem o bloqueio.

## Marcos de entrega e responsabilidades

| Marco | Evidencia de conclusao | Responsavel e limite |
| --- | --- | --- |
| M1 — implementacao certificada | Codigo, documentacao, testes positivos/negativos/regressoes, gates tecnicos e certificado semantico do SHA material | O implementador produz e valida a entrega. O certificado nao e parecer de uma conversa separada nem prova de instalacao. |
| M2 — adocao operacional | Revisao do SHA certificado em conversa separada; instalacao protegida; caso positivo e negativos reais; leitura das regras efetivas de `develop` e `main` | O operador declara a separacao da revisao; o proprietario autoriza a instalacao inicial e a mudanca administrativa das regras. |

A decisao de fase da issue autoriza adiar os requisitos de revisao operacional, instalacao e migracao de rulesets para depois do handoff M1. O dossie de M1 deve registra-los como `deferred`, citar a decisao e manter `parent_issue_must_remain_open=true` com o alvo da issue. Nao marcar essas obrigacoes como cumpridas por testes locais ou CI. A issue so pode ser encerrada depois das provas de M2.

## Politica e ativacao administrativa

A conta autorizada e definida por **ID numerico e login** na allowlist `operators`. A permissao e verificada novamente no momento da publicacao. O proprietario individual e reconhecido pelos metadados autenticados do repositorio, sem exigir outro usuario ou um segredo administrativo adicional.

Ativar requer alterar `mode` para `enabled` e cadastrar a conta **na base confiavel**, mantendo a declaracao explicita do limite de garantia. O candidato nao pode ativar sua propria politica; os bytes do executor/politica devem coincidir com os da base. As branches default e destino precisam conter as mesmas versoes desses arquivos.

O novo check nao substitui sozinho a regra nativa `required_approving_review_count=1`. A migracao administrativa, depois de aceitar este modelo de garantia, consiste em manter PR obrigatoria, remover a exigencia de outra conta (contagem 0), trocar o check de identidade independente pelo check de sessao e preservar os checks tecnicos, certificacao, atualizacao estrita, bloqueio de force-push e exclusao. Isso altera o modelo de confianca; nao e equivalente a uma aprovacao de terceiro.

O bootstrap e uma decisao administrativa unica: a politica antiga, que exige outra conta, nao pode aprovar sua propria substituicao por uma unica conta. Registrar essa decisao, o SHA revisado e as evidencias; nao fabricar check verde nem desativar indiscriminadamente todas as protecoes. A automacao nao altera rulesets e nao faz merge. Enquanto nao houver autorizacao e instalacao protegida, permanece o gate antigo.

### Instalacao sequencial da recuperacao de proveniencia (issue #171)

1. Validar a PR de correcao sobre `develop` com suite focada, suite canonica,
   testes adversariais, handoff e auditoria **realmente separada**. Congelar o
   SHA revisado. Se o gate antigo nao puder validar sua propria substituicao,
   a unica via e bootstrap administrativo **explicito e registrado** pelo
   proprietario com inventario anterior de rulesets, checks e SHAs; jamais
   um check artificial, bypass silencioso ou merge automatico.
2. Instalar os bytes revisados de `scripts/session_review.py`,
   `scripts/session_review_github.py`, `scripts/verify_session_review.py`
   e politica na base confiavel
   `develop`, preservando workflows/required checks/branch protection;
   conferir os SHAs e o comportamento negativo enquanto `main` ainda
   nao estiver sincronizada. Nessa janela, o leitor deve permanecer bloqueado.
3. Promover os mesmos bytes para `main` por release autorizada e
   conferir igualdade byte a byte entre runner/default/base; ler de volta
   regras efetivas em ambas as branches. O opt-in nao entra em vigor por
   existir somente numa branch candidata.
4. Depois da promocao para `develop`, a PR #170 **nao pode reutilizar**
   o HEAD `cddadea4...` ou a cadeia que comecava no parent `2ee50f7...`:
   o primeiro commit material continua apontando para a antiga base e
   `authenticated_implementation_provenance` exige que seu unico parent
   seja a **nova** base autenticada da PR. A equivalencia de merge preview
   nunca autoriza equivalencia de base/HEAD ou reutilizacao de certificados.
   Conferir a nova base de `develop`; atualizar a branch da PR #170 por
   **rebase linear sobre essa base** (com anuencia explicita para reescrever
   a branch material), preservando o diff e as regras de negocio. Se houver
   conflitos, resolve-los sem bypass; nao usar merge commit nao linear,
   force-push silencioso ou commit vazio. Publicar o novo HEAD apenas pelo
   procedimento autorizado, com CAS/lease e comprovacao dos novos pais Git.
5. No novo HEAD da PR #170, reexecutar testes, emitir **novo** handoff
   semantico e pacote neutro vinculados ao novo base/HEAD, invalidando os
   digests, evidencias e referencias exact-SHA anteriores. Em uma **nova
   conversa auditora separada**, confrontar as 20 obrigacoes canonicas,
   commits reescritos e controles reais; somente parecer completo do
   operador pode autorizar o check. Executar controles positivos e negativos
   reais de preview refeito, adulteracao/revogacao, issue/PR/HEAD, politica,
   historico Git e permissao antes de aceitar M2. Quando `develop` avancar
   novamente, repetir a certificacao em vez de reutilizar prova obsoleta.
   Nao fazer merge automatico da #170 nem fechar a #169 apenas por CI verde.

**Rollback:** conservar snapshot de codigo, politica, rulesets e certificados.
Se a recuperacao falhar, desabilitar o opt-in **nas duas bases** ou reinstalar
os bytes confiaveis anteriores por procedimento autorizado, mantendo os
checks obrigatorios atuais; nao desligar o check de sessao antes de restabelecer
a via anterior. Ler de volta `develop` e `main`, confirmar que a ausencia de
auditoria continua bloqueante e registrar os testes, SHAs e a autorizacao.
Uma reversao ainda bloqueada por falta de parecer e mais segura que aprovar
um resultado sem prova.

Antes da migracao M2, guardar o inventario anterior e o plano de retorno: JSON de rulesets e branch protection aplicaveis, regras efetivas, bypasses, nomes e apps dos required checks, contagem de reviews, revisoes de workflows e bytes/hash da politica em cada base. Registrar tambem o proprietario responsavel e os links da decisao, do certificado e dos runs. Esse snapshot e a referencia do rollback; exemplos de checks neste guia nao substituem as regras reais do repositorio.

### Preparacao da ativacao e observabilidade

Antes de exigir o check de sessao nos rulesets, publicar e revisar a mesma
politica `enabled` com operador explicito nas branches confiaveis `develop`
e `main` (default). Uma politica apenas na branch candidata nao concede
autoridade, e a instalacao inicial exige a decisao administrativa registrada
na issue vinculada e a preservacao dos checks tecnicos existentes.

O workflow de `push` avalia PRs abertas e pode registrar falhas de sessao
para PRs antigas sem o vinculo canonico ou com base ainda anterior a
instalacao. O vinculo deve ser uma linha isolada `Refs #<numero>`,
`Fixes #<numero>` ou `Closes #<numero>`; uma referencia solta no texto,
um ponto final ou varias issues ambiguas nao autorizam a revisao.
A falha deve continuar negando aprovacao, nunca virar `success` por
ausencia de prova. Diagnosticos do GitHub CLI mostram metodo, recurso sem
query e status HTTP quando presente; o corpo de erro e o token permanecem
ocultos.

O check `Verify session review (exact SHA)` so deve ser exigido depois
de prova positiva e negativa real em PR aberta e de read-back das regras
ativas em ambas as branches. Ate la, `mode=enabled` no codigo e apenas
preparacao tecnica: a adocao operacional M2 permanece pendente.

## Rollback do modo de sessao

O proprietario aciona o retorno quando a garantia atestada deixar de ser aceita, houver defeito no verificador ou as provas operacionais falharem. O retorno preserva PR obrigatoria, checks tecnicos, certificacao, atualizacao estrita e bloqueios de force-push/exclusao durante toda a transicao.

1. Suspender novas integracoes e registrar a causa, as PRs/SHAs afetados, os runs e os recibos existentes. Capturar novamente regras efetivas e politica de ambas as bases; conservar o historico de pareceres e certificados.
2. Conferir o snapshot anterior a M2. Se faltar origem verificavel para politica, workflows ou regras anteriores, manter o bloqueio e reconstruir essa evidencia com o proprietario; nao improvisar uma configuracao permissiva.
3. Reinstalar nas bases protegidas a versao revisada dos emissores legados quando necessario, pelo procedimento administrativo autorizado. Restaurar a exigencia de aprovacao humana independente e seus checks, com os mesmos apps/origens do snapshot, **antes de retirar** o required check de sessao. Manter o check de sessao exigido durante essa sobreposicao. Se a via antiga ainda nao puder produzir evidencia valida, a integracao permanece bloqueada.
4. Ler de volta os rulesets, branch protection e regras efetivas de `develop` e `main`. Provar que uma PR sem review humano ou sem check legado valido continua impedida de integrar. A via Ed25519 conserva seu registro, custodia e validacao proprios; o rollback nao a converte em atestacao do operador.
5. Somente depois da protecao anterior estar efetiva, retirar `Verify session review (exact SHA)` dos required checks e desabilitar a politica de sessao nas bases confiaveis/default. Publicar essas alteracoes de forma rastreavel e verificar a igualdade de versoes exigida pelo executor. Recibos antigos continuam historicos e nao concedem aprovacao sob a politica restaurada.
6. Encerrar a transicao apenas com leitura final das duas bases: PR obrigatoria, contagem de reviews restaurada, checks tecnicos e de auditoria/certificacao, atualizacao estrita, bloqueios de exclusao/force-push e bypasses conforme snapshot. Remover qualquer excecao temporaria usada na instalacao e registrar seu read-back. Anexar os resultados dos controles e a comparacao antes/depois a issue operacional.

Um rollback que mantem PRs bloqueadas por falta de revisor ou evidencia e um retorno seguro ainda pendente de operacao. Nao reduzir reviews, desligar rulesets globais, fabricar sucesso nem autorizar merge para tornar o retorno verde. Para readotar o modo de sessao, repetir M2 sobre o SHA certificado corrente; o recibo de uma instalacao anterior nao basta.

## develop, main e provas reais

O coletor de handoff suporta as duas bases. O modo de sessao exige certificado e testes no HEAD de cada PR, inclusive em main; nao aceita certificado de outro PR/issue nem de um commit anterior. A via humana legada conserva sua politica propria.

Antes de ativar o required check, comprovar em execucao real o caso positivo e os negativos de adulteracao, exclusao de parecer, mudanca de issue, base/HEAD e permissao. Os testes automatizados exercitam a implementacao, mas **nao sao evidencia de que um auditor real revisou esta PR**.

A issue permanece aberta ate completar a certificacao da entrega e a adocao operacional. O implementador desta migracao nao publica o proprio parecer como revisao separada. A PR nao e declarada aprovada por CI verde, pacote neutro ou recibo de pre-auditoria.

### Publicador confiavel com duas branches

O publicador do workflow `Publish certified handoff (trusted)` executa
exclusivamente codigo da `main` e, quando nenhum `--base-ref` explicito
e fornecido, seleciona `develop` ou `main` por meio do registro
**autenticado** da PR no GitHub, nao por campos manipulaveis do evento.
Depois, `target_from_event` revalida estado, SHA, origem, path do
workflow e a base selecionada; eventos antigos ou alterados bloqueiam.
Bases diferentes sao permitidas apenas na interface de configuracao
explicita para repositorios consumidores, nunca pela autodeteccao.

Esse ajuste e condicao de M2 para que PRs de release contra `main`
nao sejam interpretadas como PRs contra `develop`.


### Recuperacao de checks e staging de resultados

No reprocessamento de comentarios, uma tentativa de reabrir um check que
o GitHub ja registrou como `completed` pode conservar o estado terminal.
O emissor exige identidade exata do check antigo e, somente nessa condicao,
publica novo check `in_progress` para impedir que o resultado anterior
permaneça indevidamente como o mais recente. Mudanca de identidade bloqueia
sem fallback. O novo check depende de revisao real e evidencias: nunca e
marcado como `success` pela ausencia de review.

O publicador da `main` usa `git add -f --` exclusivamente nos caminhos
autorizados pelo certificado, porque `.audit/` esta corretamente no
`.gitignore` do repositorio. Nao se modifica o ignore global nem se
aceitam caminhos de codigo fora da allowlist. A CI de `main` isola
`GITHUB_REF_NAME` e `GITHUB_ACTIONS` nos testes de versionamento com
repositorio sintetico; o gate de release sobre o checkout real continua ativo.


### Estados retornados pela Checks API no bootstrap M2

O executor confere a identidade do check em `head_sha` e `id` autenticados,
mas o GitHub pode devolver `completed/failure` imediatamente apos uma
escrita de inicio. Esse resultado e **bloqueante**, nao uma aprovacao:
a verificacao prossegue e publica conclusao final somente apos as fontes
e o parecer atestado serem revalidados. `queued` e `in_progress` sao
permitidos apenas sem conclusao. Estados `completed/success`,
`completed/neutral`, `completed/skipped`, conclusoes antecipadas e
identidades divergentes sao sempre recusados. O diagnóstico expõe apenas
a classe do estado, nao corpo de API, token ou entrada do operador.


### Read-back pos-push do publicador confiavel

O GitHub pode devolver temporariamente o HEAD anterior da PR depois de um
`git push` concluido, enquanto os metadados de commit ja estao visiveis.
O publicador repete a leitura por um numero limitado de tentativas com
espera curta. O resultado so e aceito se a PR estiver aberta, na mesma base,
com o filho `result-only` exato, parent material exato e **todos** os arquivos
exatamente na allowlist. Um terceiro SHA, base alterada ou timeout bloqueiam
a publicacao. O guard terminal de pos-publicacao continua sendo executado
apos a leitura confirmada; a espera nao concede nenhuma aprovacao.


### Isolamento entre handoff legado e auditoria por sessao

Quando a politica `.github/session-review-policy.json` estiver `enabled` na
branch default **e com os mesmos bytes na base autenticada da PR**, o
publicador de `workflow_run` nao cria um novo commit `result-only`.
O workflow de certificacao continua obrigatorio e o auditor de sessao
consome diretamente o artefato e os checks do **HEAD material imutavel**.
Isso evita a corrida entre o coletor neutro e um novo commit que mudaria
o alvo enquanto o revisor ainda le os arquivos e faria falhar o exact-SHA.

A selecao da modalidade consulta a politica pela API autenticada no SHA da
base e exige coincidencia byte a byte com a politica do codigo confiavel da
default branch; nunca deriva de marcador ou conteudo da PR. Politica
invalida, identidade divergente, arquivo ausente apenas de um lado ou
erro de acesso bloqueiam em vez de degradar silenciosamente. Somente
repositorios sem politica nos dois lados ou com politica explicitamente
`disabled` preservam a publicacao do filho de resultados como antes.
O sucesso da etapa de roteamento nao emite parecer, certificado artificial
ou check aprovado. O fluxo de sessao permanece obrigado a verificar todo
o pacote real e a revisao em conversa separada.

## Ensaio de aceitacao M2 com HEAD estavel

Este ensaio de revisao web so e valido com a politica de sessao autenticada e
instalada com os mesmos bytes na default `main` e na base `develop`.
A certificacao semanticamente vinculada ao SHA material deve ficar verde
antes da coleta do pacote neutro. O pacote confirma os 16 candidatos e
controles reais, mas nao constitui o parecer de outra conversa.

O operador revisa o pacote em uma conversa ChatGPT realmente separada da
implementacao, declara a separacao com referencias reais e registra o
parecer `SOLVERIT_SESSION_REVIEW_V1` no GitHub. O emissor verifica fontes,
controles, conta GitHub e SHA; sucesso sem comentario autorizado continua
bloqueado. Depois do caso positivo, os ensaios reais de adulteracao,
revogacao e mudanca de alvo devem retirar a aprovacao. Revalidar todas
as regras antes da ativacao dos rulesets; nenhum ensaio desta secao
substitui o parecer independente.
