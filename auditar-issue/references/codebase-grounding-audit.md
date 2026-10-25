# Auditoria de ancoragem no codigo

## Objetivo

Refutar `GROUND-REUSE-001`, `GROUND-EXIST-001` e `GROUND-DEAD-001` sem aceitar `codebase-grounding.json` como conclusao. O relatorio da entrega prova apenas o que declarou; a auditoria procura o que ele omitiu.

## Limite entre automacao e semantica

O validador da entrega confere registro, cobertura formal do diff, SHA e paths; nao aceita similaridade nominal como prova de equivalencia. O auditor deve ler os oraculos e exercitar variantes capazes de refutar a decisao de reuso, criacao ou remocao; nao reutilizar a justificativa do implementador como evidencia. Se runner/arvore nao forem acessiveis, declarar UNKNOWN e nao concluir cobertura integral.

## Refutacao independente

Refazer a classificacao de testes contra as configuracoes reais do runner nas revisoes base/HEAD, nao apenas caminhos convencionais. Para pytest verificar `python_files` em pytest.ini, pyproject.toml, tox.ini e setup.cfg; executar controle de coleta independente quando o padrao nao for convencional. Distinguir manifestos com mudanca no teste de metadata ordinaria. Plugins e descoberta dinamica que nao puderem ser inspecionados permanecem `UNKNOWN`, nao `not-applicable`. Refutar regressao de removidos/renomeados e autenticidade do log antes de marcar cobertura.

Com checkout e base disponiveis, usando buscas proprias sobre o `material_head_sha`:

1. **Duplicidade:** para cada arquivo, simbolo publico, endpoint, tabela ou dependencia adicionada no diff da issue, buscar por comportamento equivalente ja existente com termos diferentes dos registrados pela entrega. Equivalente nao citado como candidato e finding.
2. **Existencia:** extrair do diff imports, chamadas, comandos, caminhos e chaves de configuracao novos e confrontar com definicoes e manifestos do head. Referencia sem definicao, sem dependencia declarada ou ausente do relatorio e finding.
3. **Sobra:** para cada comportamento substituido, procurar o caminho antigo, flags, aliases e documentacao que ainda o descrevam. Codigo sem consumidor ou dois caminhos ativos para o mesmo comportamento e finding.
4. **Testes:** refazer busca por nivel, setup e oraculo nos testes alterados, inclusive renomeacoes e remocoes. Confrontar controles discriminantes anteriores com os posteriores, descobrir runner dinamico quando aplicavel, confirmar suites executadas no SHA exato e investigar skip, mock obsoleto ou remocao. Sem prova, preservar e reportar UNKNOWN; auditoria nunca apaga testes.

Quando o gate era aplicavel e o relatorio estiver ausente ou stale para o SHA auditado, tratar como `delivery-not-ready` antes de provas caras. Finding em SHA aprovado internamente e `audit_escape`.

Sem checkout executavel, declarar a verificacao `UNKNOWN`; nao aprovar por inferencia.

## Controle de diffs de testes no gate independente

`validate_audit_completeness.py` reconcilia os caminhos alterados com objetos Git imutáveis. Para caminhos reconhecidos por convenções usuais de testes e arquivos explícitos de configuração de runner (inclusive diffs só de testes, adições e exclusões), a revisão do caminho não pode ser `not-applicable`: exigir superfície `risk_family=test-lifecycle`, motivo substantivo e evidência com hash. Isso impede omissão formal e rotulagem como código comum, mas não comprova equivalência de oráculos ou preservação de cobertura. O auditor continua obrigado a conferir antes/depois, controles positivos/negativos/regressão e descoberta do runner. Convenções de nome são indícios conservadores: padrões personalizados, plugins e descoberta dinâmica não reconhecidos continuam `UNKNOWN` até inspeção do runner; não declarar inexistência de testes com base apenas na heurística.
