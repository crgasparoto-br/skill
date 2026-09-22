# Gate de deriva semantica documental

## Objetivo

Impedir que uma entrega altere uma regra normativa executavel enquanto fontes canonicas versionadas continuem declarando a politica anterior. Este gate cobre `documentation-claim-drift` mesmo quando links, Markdown e CI documental estao verdes.

## Aplicabilidade

Ativar quando contrato, codigo, migration, seed, trigger, configuracao ou default alterar qualquer semantica normativa, incluindo:

- autorizacao, role, permissao, capability, entitlement, allow/deny ou escopo;
- default, preset, feature flag, fallback ou comportamento automatico;
- provisionamento, seed, trigger ou criacao futura que materialize politica;
- rota, redirect, disponibilidade, estado atual, nomenclatura, substituicao, aposentadoria ou compatibilidade;
- regra de dominio ou operacao que mude quem pode, deve, recebe, herda, exige, bloqueia ou permite algo.

Nao exigir mudanca textual literal na issue. Se o diff alterar uma dessas regras, a reconciliacao pos-diff deve ativar o gate.

## Controle obrigatorio `DOC-SEMANTIC-DRIFT-001`

1. Derivar a afirmacao normativa anterior e a nova afirmacao a partir de fontes canonicas + comportamento executavel.
2. Registrar `old_contract_terms` e `new_contract_terms`, incluindo sinonimos e formas negativas relevantes.
3. Executar busca repository-wide no **material head final**, fora do diff, em fontes versionadas de produto, arquitetura, banco, API, runbook, ajuda e exemplos aplicaveis.
4. Inventariar cada ocorrencia com caminho, linha, texto, termo e classificacao: `current-contract`, `historical`, `retired-legacy`, `compatibility`, `example` ou `contradiction`.
5. Tratar como normativa uma linha que use linguagem de obrigacao/permissao/default (`deve`, `pode`, `nao pode`, `exige`, `recebe`, `herda`, `automaticamente`, `por padrao`, `deny-by-default`, `allow`, `blocked`, equivalentes), salvo se a propria passagem marcar explicitamente contexto historico/aposentado/compatibilidade.
6. Bloquear enquanto `unresolved_contradictions` nao estiver vazio ou enquanto uma ocorrencia normativa do contrato antigo estiver classificada como historica sem marcador historico real.
7. Representar a superficie em `requirement-attack-matrix.json` como `risk_family=documentation`, normalmente `surface=canonical-claims`, com controle negativo `DOC-SEMANTIC-DRIFT-001`; a familia `documentation` deve ficar `applicable=true` em `risk-saturation.json`.

## Evidencia minima

- `documentation_consistency.status=passed`;
- termos antigos e novos nao vazios;
- `searched_outside_diff=true`;
- evidencia da busca no SHA final;
- inventario completo das ocorrencias antigas;
- `unresolved_contradictions=[]`;
- controle `documentation:canonical-claims` executado no material head.

## Casos de transferencia sinteticos

- **Politica de acesso:** `role_alpha` passa a receber `sensitive_action`, enquanto uma fonte canonica ainda afirma que a role nao recebe a acao automaticamente. O gate deve falhar.
- **Default operacional:** `feature_beta` passa de `disabled-by-default` para `enabled-by-default`, enquanto um runbook continua declarando o default antigo como regra vigente. O gate deve falhar.

O controle deve passar somente quando as alegacoes antigas restantes estiverem explicitamente historicas, aposentadas, de compatibilidade ou exemplo.
