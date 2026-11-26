# Publicação da reconciliação de critérios de aceite

## Autoridade e momento

O auditor independente produz e valida `acceptance_criteria`, mas nunca escreve
no GitHub. `entregar-issue` pode executar esta fase somente depois de receber
um parecer autenticado e validado, ainda vinculado à issue, ao repositório e ao
SHA exato.

Executar:

```bash
python <skill>/scripts/reconcile_issue_acceptance_criteria.py \
  --audit-report <controller-audit-report.json> \
  --repository <owner/repo> \
  --issue <n> \
  --head-sha <sha> \
  --apply
```

O script valida o schema e executa o validador semântico canônico do auditor,
incluindo suas evidências locais. Exige issue aberta, PR não-draft do mesmo
repositório contra `develop` ou `main` protegida e HEAD/base exatos.
O relatório e a revisão mantêm o SHA do preview certificado. Se o GitHub
regenerar o preview, o CLI exige que ambos os objetos Git autenticados tenham
os mesmos pais ordenados `[base, HEAD]` e a mesma árvore; ausência ou divergência bloqueia.
O CLI também confere o
snapshot da issue e a seção normativa `## Critérios de aceite` (ou
`## Acceptance criteria`) em cada origem usada. Uma linha de item é localizada
junto com o texto de suas continuações, sem contar listas em código/HTML
inerte como critérios. Identifique itens filhos separadamente. Blocos inertes
em listas terminam no limite do seu contêiner, inclusive sem cerca explícita.
O validador compartilhado exige vínculo individual de origem, texto, digest,
locator, linha e evidência com o requisito atômico correspondente, e rejeita
aprovação global com critérios obrigatórios não verificados antes do POST.
O inventário de linhas deve coincidir para cada fonte: o corpo da issue e
os comentários selecionados pelo inventário de requisitos atestado no
parecer, com locator explícito `issue-comment:<id>`, digest exato e confirmação
de que o comentário pertence à issue. Um comentário selecionado com critérios
não pode ter todas as decisões omitidas. Comentários não selecionados não
adquirem força normativa por conterem um cabeçalho de aceite. Sem seleção
autenticada, o CLI não infere fontes que estejam ausentes tanto do inventário
de requisitos quanto dos critérios.

A autoridade não é selecionável: o CLI exige o check canônico
`Verify session review (exact SHA)`, do app GitHub Actions, e o workflow canônico
`.github/workflows/session-review.yml` autenticado. Confere separadamente o
check suite do HEAD material e o suite do workflow que roda na branch
confiada; esses suites não precisam ser iguais. Confere o conteúdo da cadeia
executável no SHA protegido do run contra o da base, validando as duas
suites nas suas respectivas âncoras Git. O recibo oficial V2 identifica
a execução e sua tentativa. O artefato único `session-review-origin-v2-attempt-N`
da tentativa corrente concluída, não expirado e com digest autenticado,
pode conter vários registros, um por check publicado na mesma tentativa.
O ZIP tem limites de tamanho e cardinalidade. Cada membro deve ser regular,
com nome canônico único e registro da mesma tentativa. O membro do check alvo
deve registrar o seu ID, sua suite e SHA-256 do recibo exato; os registros
irmãos não substituem essa prova nem atestam outros alvos neste consumo.
Tanto o URL
direto `/actions/runs/<run-id>` como `/runs/<check-id>` são conferidos contra
essas identidades; o ID do check nunca é usado para adivinhar o run. Sem
recibo V2 ou artefato registrado pelo emissor protegido, não publica.

Antes de registrar a revisão, o operador autorizado coloca **uma** linha
`AUDIT_REPORT_SHA256=<64 hex minúsculos>` no campo `analysis` de uma
das linhas existentes em `requirements`, sem substituir o seu parecer
textual. O hash é SHA-256 da serialização JSON canônica (UTF-8, chaves
ordenadas, sem espaços de separador, Unicode não escapado) do relatório
completo. Nenhum campo novo é exigido pelo gate confiado. O publisher lê o
recibo canônico do check e o comentário original autenticado, verificando
política da base protegida, identidade SHA/issue/PR/base/preview, autor
permitido, timestamps iguais, revisão vigente e hash dos bytes exatos do
comentário atestado pelo recibo. A listagem e a consulta direta devem
coincidir no ID, login e tipo do autor, além da identidade, do conteúdo e dos
timestamps do comentário. Metadados de exibição, como URL do avatar, não
identificam a conta. A referência no comentário publicado é
o URL estável desse comentário autenticado; se `--audit-report-url` for
informado, deve ser exatamente essa referência. Revisão por sessão continua
declarada pelo operador, não identidade independente criptográfica.

`Parcial`, `Reprovado`, inconclusões que impeçam aprovação ou check sem
readback confiável não podem passar por essa via. Preserve a classificação
local e não transforme o relatório negativo num recibo de aprovação. Sem
`--apply`, só produz plano após as mesmas leituras. O consumidor
não modifica o gate. Pareceres anteriores ao emissor V2 precisam de nova
verificação oficial do alvo ainda vigente; não há fallback permissivo.

## Registro append-only

O comentário:

- contém todas as decisões por critério, inclusive negativas, parciais e
  inconclusivas, sem convertê-las em prova;
- vincula parecer, SHA auditado, digest do contrato e evidência;
- contém fingerprint lógico versionado;
- não apaga nem edita comentários anteriores;
- rejeita duplicata lógica já existente e confirma o comentário por nova leitura
  autenticada depois da publicação;
- repete a checagem de comentário entre a última leitura e o POST, reduzindo a
  janela concorrente, e reprova duplicatas detectadas no read-back final.

Se a mesma decisão já estiver publicada com fingerprint idêntico, o resultado
é `already-published`; isso é idempotência lógica, não nova aprovação. A API
GitHub não oferece CAS para POST de comentário: executar a publicação sob um
único owner/concorrência operacional confiável. O script não remove duplicatas:
se dois publishers ultrapassarem a última checagem, o read-back falha fechado,
preservando append-only e impedindo um recibo de sucesso ambíguo.

## Corpo da issue e concorrência

Preservar o corpo da issue. GitHub não oferece, de modo comprovado neste
contrato, CAS atômico para atualizar o texto com expectativa de corpo anterior.
`--update-checkboxes` é, portanto, fail-closed e a publicação registra que a
escrita do corpo não foi tentada.

Não futuramente habilitar essa opção apenas por uma leitura seguida de
`PATCH`: isso continua sujeito a sobrescrita concorrente. Exige operação de
escrita atômica condicional demonstrada e testes de stale write. Mesmo com
CAS, somente critérios `verified` podem ser marcados; todas as demais decisões
permanecem abertas.

## Efeito da reconciliação

Comentário ou checkbox não altera o veredito, a identidade do SHA, a
aprovação independente, os gates nem a autorização de merge/fechamento. Mudança
posterior do corpo ou do HEAD exige nova auditoria/reconciliação afetada; nunca
reaproveitar o comentário como prova do material novo.
