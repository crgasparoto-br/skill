# Varredura de contratos concorrentes

## Aplicabilidade

Executar quando a mudanca alterar qualquer regra normativa, incluindo rota, arquitetura, nomenclatura, estado atual, disponibilidade, fluxo principal, redirect, aposentadoria, substituicao ou compatibilidade legada; autorizacao, role, permissao, capability, entitlement, allow/deny, escopo; default, preset, feature flag; seed, provisionamento, trigger ou comportamento automatico para entidades futuras.

## Inventario

Registrar:

- termos, rotas e frases do contrato anterior;
- termos, rotas e frases do contrato novo;
- sinonimos e expressoes de transicao (`ainda nao`, `futuro`, `pendente`, `parcial`, `experimental`, `somente`, `atual`, `operacional`, `disponivel`);
- linguagem normativa (`deve`, `pode`, `nao pode`, `exige`, `recebe`, `herda`, `automaticamente`, `por padrao`, `allow`, `deny`, `deny-by-default`) e suas formas negativas;
- comando ou mecanismo de busca executado no SHA final;
- raiz, inclusoes e exclusoes da busca;
- ocorrencias encontradas em todo o repositorio, inclusive fora do diff;
- classificacao de cada ocorrencia: contrato atual, historica, legado aposentado, compatibilidade, exemplo ou contradicao;
- contradicoes corrigidas e nova busca sem pendencias.

## Regra discriminante

Uma ocorrencia do comportamento antigo que contenha marcadores de estado atual **ou linguagem normativa** (`deve`, `pode`, `nao pode`, `exige`, `recebe`, `herda`, `automaticamente`, `por padrao`, equivalentes) deve ser tratada como contradicao, salvo quando a propria passagem declarar claramente que o comportamento e historico, aposentado, de compatibilidade ou exemplo.

Quando uma capacidade muda de ausente, futura, parcial ou experimental para operacional, a busca global e obrigatoria mesmo que os documentos especializados tenham sido atualizados. README, indice central, matriz de status, ajuda e runbook devem ser comparados entre si.

Markdown valido, link correto, CI verde, descricao de PR ou atualizacao de outro documento nao compensam uma fonte canonica concorrente.


## Controle reutilizavel

Aplicar `DOC-SEMANTIC-DRIFT-001`: busca repository-wide no SHA final, inventario completo de alegacoes antigas, classificacao reproduzivel e `unresolved_contradictions=[]`. CI documental verde, Markdown valido ou descricao de PR nao substituem este controle.
