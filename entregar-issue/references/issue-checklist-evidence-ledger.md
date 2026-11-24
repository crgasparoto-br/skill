# Registro pós-auditoria de critérios de aceite em comentários GitHub

## Quando ler este arquivo

Ler quando o parecer autenticado por gate confiável tiver decisões individuais comprovadas, mas a issue não possuir escrita atômica condicional para atualizar os checkboxes no corpo. Complementa, sem substituir, `issue-checklist-reconciliation.md`.

## Contrato do registro

`entregar-issue` é o executor; `auditar-issue` permanece somente leitura. O comentário na issue é um **registro de evidências, não uma aprovação**: não cria gate, não autoriza merge/fechamento, não modifica os checkboxes Markdown e não altera o texto normativo. O gate de auditoria independente ou atestação solo formalmente aceita continua sendo a fonte da decisão. A publicação é permitida mesmo se o parecer global reprovou, desde que cada critério marcado `verified` tenha prova suficiente autenticada.

Antes de preparar qualquer comentário, ler a issue no GitHub, revalidar identidade da PR/base/material SHA, evidências e gates afetados e obter o review/atestação realmente aceito pelo gate confiável do repositório. Jamais confiar somente em `validity`, `audit_url` ou outro campo do JSON entregue pelo implementador.

## Renderização sem rede

Reutilizar integralmente o validador e parser canônicos da reconciliação. Gerar comentário determinístico com todos os critérios, texto integral, posição, status observado, prova e SHAs/digests:

```bash
python entregar-issue/scripts/record_issue_acceptance.py \
  --audited-body audited-issue.md --current-body current-issue.md \
  --audit verified-criteria.json --material-sha <40-hex> \
  --repository owner/repo --issue-number 123 --pull-request-number 456 \
  --output acceptance-comment.md
```

`acceptance-comment.md` contém exatamente um marcador `SOLVERIT_ACCEPTANCE_RECORD_V1`, seguido de JSON. O registro deixa explícitos `approval_granted=false`, `issue_body_modified=false` e `audit_authenticated=CONTROLLER_MUST_VERIFY`. Script offline **não** autentica a origem e **não** possui rede, token ou publicação.

## Publicação autorizada e idempotência

1. Reconsultar issue/PR/review antes do POST. Rejeitar drift de corpo normativo, material SHA, evidência ou origem. Obter a listagem **completa** de comentários da issue por API autenticada; fornecer esses comentários como JSON ao script com `--prior-comments` para obter `publication_decision`: `publish` ou `already-recorded`. Antes de aceitar `already-recorded`, revalidar no GitHub o autor e a permissão de publicação do comentário encontrado, além da origem confiável do parecer vinculado: comentário de ator não autorizado não pode satisfazer a reconciliação, ainda que possua corpo idêntico. Conflito de conteúdo para mesmo repositório/issue/PR/SHA/digest contratual bloqueia; não editar nem apagar registros anteriores.
2. No estado `publish`, o executor autorizado pode fazer POST de **novo comentário** na issue usando a integração GitHub. Nunca editar o corpo sem CAS atômico comprovado; nunca criar comment no lugar da revisão confiável. O comentário não tem chave de idempotência garantida no servidor: consultas prévias evitam repetição normal, mas publicações simultâneas podem gerar comentários idênticos. Tratar duplicatas idênticas como **uma decisão lógica**, nunca votos/aprovações extras.
3. Reconsultar imediatamente comentário **pelo ID retornado**, issue e identidade material. Verificar autor/permissão/conta pelo GitHub autenticado, corpo exato, head/base, issue digest, link do parecer aceito e revogação/conflito. Para comparar bytes, passar os valores obtidos do GitHub:

```bash
python entregar-issue/scripts/record_issue_acceptance.py \
  --audited-body audited-issue.md --current-body current-issue.md \
  --audit verified-criteria.json --material-sha <40-hex> \
  --repository owner/repo --issue-number 123 --pull-request-number 456 \
  --output acceptance-comment.md --readback-comment observed-comment.md \
  --readback-issue-body observed-issue.md --observed-material-sha <40-hex> \
  --observed-comment-id 123456
```

`check_comment_readback` compara bytes e identidade, mas **não autentica que o GitHub foi consultado** nem prova exclusão de corrida: isso é obrigação separada do executor. Registro com nova identidade ou revisão semanticamente alterada exige nova rodada, nunca alterar comentário antigo para parecer vigente. A consulta ao resultado deve exigir correspondência com contrato, SHA e review confiável atuais; registro antigo não vira estado vigente só por estar no histórico.

## Independência e validação

Exigir testes positivos/negativos/regressão, checks exact-SHA e review realmente separado antes de publicar decisões como comprovadas. O script pode renderizar registros e validar fixtures offline durante desenvolvimento, mas não autoriza postagem de evidências de auditoria não autenticada. Critérios sem prova permanecem abertos; comentários e checkboxes não equivalem à aprovação global. Atualização do Markdown permanece opcional e bloqueada enquanto o endpoint não expuser compare-and-swap atômico confiável. Não acrescentar nova Skill nem novo gate de CI.

Validar com `python -m pytest -q entregar-issue/tests/test_issue_acceptance_record.py entregar-issue/tests/test_issue_checklist_reconciliation.py` e validadores existentes.
