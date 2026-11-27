# Parecer por critério de aceite

## Objetivo

Fazer o parecer representar, sem inferência por checkbox, todos os itens da
seção normativa de critérios de aceite. Esta fase é somente leitura; produzir
decisões e uma proposta de reconciliação não publica nada no GitHub.

## Inventário obrigatório

Rederivar os critérios diretamente das fontes canônicas congeladas, inclusive
quando o checkbox já estiver marcado. Para cada item registrar:

- ID estável e requisito correspondente;
- fonte, locator, linha e SHA-256 exatos;
- texto integral, sem normalizar obrigações distintas;
- estado inicial: `checked`, `unchecked` ou `not-present`;
- decisão: `verified`, `partial`, `failed`, `inconclusive` ou `not-applicable`;
- evidência exata no SHA auditado e limitação observada;
- justificativa verificável;
- estado de checkbox proposto.

Cada critério deve apontar para um requisito atômico distinto. Na linha de
`requirements`, usar `origin` igual a `source_id` do critério, `statement` igual
a `text`, e repetir `source_locator`, `source_sha256` e `source_line` exatos.
Evidências positivas de um critério verificado devem pertencer a `evidence`
desse mesmo requisito; não aceitar evidência de outro item.

Texto duplicado não identifica um critério: origem, locator e linha integram a
identidade. Se a fonte tiver mudado desde a captura, bloquear a decisão para
essa identidade em vez de associar o parecer a um contrato semelhante.

## Decisão e separação do veredito

Somente `verified` pode propor `checked`. `partial`, `failed`, `inconclusive` ou
qualquer ausência de prova propõe `unchecked`; `not-applicable` exige decisão e
justificativa canônicas prévias. Um checkbox já marcado não é evidência.

A matriz por critério e a ação proposta não são o veredito global. O veredito
continua dependente de todos os gates aplicáveis: implementação, testes, CI,
segurança, arquitetura, regressões, documentação e limitações do auditor. Uma aprovação exige que cada critério obrigatório esteja `verified`;
`not-applicable` só é admissível com requisito `Fora do escopo` e base
canônica explícita. Decisões parciais, falhas e inconclusões devem corresponder
aos estados do requisito e impedem aprovação global. Uma
matriz inteiramente verde não libera merge, fechamento ou release.

Registrar a cobertura das demais famílias com estado e justificativa de
aplicabilidade, mesmo quando o único contrato explícito seja um critério de
aceite. Gates não executados devem permanecer visíveis como limitação ou
finding conforme a origem e a responsabilidade comprovadas.

## Saída estruturada

Preencher `acceptance_criteria` em
`schemas/controller-audit-result.schema.json` e a tabela de critérios do
parecer. O resultado deve ser validado por
`scripts/validate_controller_audit_result.py`.

Não editar corpo, comentários, PR, branch, workflow ou banco. Publicação,
deduplicação, leitura remota autenticada e eventual espelhamento de checkbox
pertencem exclusivamente à etapa autorizada posterior de `entregar-issue`.
