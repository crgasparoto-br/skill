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

Somente uma alteracao material ou uma evidencia realmente diferente exige nova revisao. Findings sao consolidados na mesma rodada. Credencial, dossie ou permissao ausente gera BLOCK com causa concreta, nao um ciclo automatico de tentativa.

## Contrato do parecer

Depositar um comentario na PR cujo corpo comece com `SOLVERIT_SESSION_REVIEW_V1`, seguido de quebra de linha e um unico objeto JSON. Nao publicar esse marcador como parte de narrativas ou exemplos operacionais na propria PR.

O JSON usa `schema_version=1`, `identity`, `assurance`, `acknowledgement`, `sessions`, `conclusion`, `blocking_findings`, `limitations` e `requirements`.

Copiar `identity` do pacote autenticado: repositorio, PR, issue, base ref/SHA, HEAD, merge preview e digests de issue/politica. `assurance` e `operator-attested-session-review`; `acknowledgement` e `separate-context-declared-not-cryptographically-proven`.

Em `sessions`, informar referencias reais fornecidas pelo operador para `implementation` e `audit`, diferentes entre si, e `separate_context_attested=true`. O programa **nao autentica uma sessao ChatGPT**; esses campos sao uma declaracao de processo. Nao inventar IDs ou assinar essa declaracao como terceiro.

Cada item de `requirements` deve ter o `candidate_key` canonico, uma `analysis` propria, `sources` e `controls`. Cada fonte aponta `path`, `start_line`, `end_line` e SHA-256 do trecho unido por `\n` sem quebra final. Cada controle informa `kind`, `test_case_id` e `rationale`. Exigem-se tres casos distintos: `positive`, `negative` e `regression`, presentes como passed no JUnit do SHA material. Isso verifica vinculos, nao substitui a avaliacao semantica do revisor.

O resultado aprovado exige `conclusion=approved`, `blocking_findings=[]` e `limitations=[]`. Parecer incompleto, anterior ao certificado, editado, de conta nao autorizada ou vinculado a outro alvo nao aprova. A edicao/exclusao revoga o parecer; publicar novo comentario em vez de alterar um aprovado. Um parecer rejeitado mais recente impede voltar a uma aprovacao antiga.

## Politica e ativacao administrativa

A conta autorizada e definida por **ID numerico e login** na allowlist `operators`. A permissao e verificada novamente no momento da publicacao. O proprietario individual e reconhecido pelos metadados autenticados do repositorio, sem exigir outro usuario ou um segredo administrativo adicional.

Ativar requer alterar `mode` para `enabled` e cadastrar a conta **na base confiavel**, mantendo a declaracao explicita do limite de garantia. O candidato nao pode ativar sua propria politica; os bytes do executor/politica devem coincidir com os da base. As branches default e destino precisam conter as mesmas versoes desses arquivos.

O novo check nao substitui sozinho a regra nativa `required_approving_review_count=1`. A migracao administrativa, depois de aceitar este modelo de garantia, consiste em manter PR obrigatoria, remover a exigencia de outra conta (contagem 0), trocar o check de identidade independente pelo check de sessao e preservar os checks tecnicos, certificacao, atualizacao estrita, bloqueio de force-push e exclusao. Isso altera o modelo de confianca; nao e equivalente a uma aprovacao de terceiro.

O bootstrap e uma decisao administrativa unica: a politica antiga, que exige outra conta, nao pode aprovar sua propria substituicao por uma unica conta. Registrar essa decisao, o SHA revisado e as evidencias; nao fabricar check verde nem desativar indiscriminadamente todas as protecoes. A automacao nao altera rulesets e nao faz merge. Enquanto nao houver autorizacao e instalacao protegida, permanece o gate antigo.

## develop, main e provas reais

O coletor de handoff suporta as duas bases. O modo de sessao exige certificado e testes no HEAD de cada PR, inclusive em main; nao aceita certificado de outro PR/issue nem de um commit anterior. A via humana legada conserva sua politica propria.

Antes de ativar o required check, comprovar em execucao real o caso positivo e os negativos de adulteracao, exclusao de parecer, mudanca de issue, base/HEAD e permissao. Os testes automatizados exercitam a implementacao, mas **nao sao evidencia de que um auditor real revisou esta PR**.

A issue permanece aberta ate completar a certificacao da entrega e a adocao operacional. O implementador desta migracao nao publica o proprio parecer como revisao separada. A PR nao e declarada aprovada por CI verde, pacote neutro ou recibo de pre-auditoria.
