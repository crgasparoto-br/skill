# Fechamento semântico de requisitos

## Objetivo

Impedir que a implementação satisfaça apenas o substantivo principal, perca qualificadores, reduza verbos ou escolha a própria lista de requisitos. O contrato é derivado do snapshot canônico, não da PR, do código ou do resumo da implementação.

## Artefato obrigatório

Construir primeiro `specification-snapshot.json` conforme [specification-snapshot.md](specification-snapshot.md). Depois executar:

```bash
python <skill>/scripts/init_requirement_closure.py \
  --specification-snapshot <audit-dir>/specification-snapshot.json \
  --out <audit-dir>/requirement-closure.json
```

O inicializador extrai candidatos de todas as fontes textuais, preserva fonte, hash, linha, texto e `candidate_key` e cria `source_coverage`. Itens de lista Markdown sob secoes normativas (`Escopo/Scope`, `Requisitos/Requirements`, `Criterios de aceite/Acceptance criteria`, `Invariantes/Invariants`) sao candidatos obrigatorios mesmo quando o verbo inicial nao constar da heuristica lexical; secoes explicitamente nao normativas (`Fora de escopo/Out of scope`, `Referencias/References`) sao excluidas. O validador recompõe os candidatos no gate; remover, alterar, fundir ou inventar obrigação reprova.

## Flags de fechamento

O gerador identifica:

- `exhaustive`: todos, cada, suportados, integralmente, equivalente;
- `observable`: resumido, claro, visível, distinto, acessível, imediatamente;
- `negative`: não, nunca, somente, sem;
- `temporal`: antes, depois, durante, imediatamente, reload;
- `isolation`: outro paciente, usuário, tenant ou contexto;
- `freshness`: vigente, atual, revisado, aprovado, versão;
- `atomicity`: transação, concorrência, deduplicação, único, canônico;
- `aftermath`: confirmação, próximas ações, filtro, localização;
- `review-surface`: identificação, contato, origem, responsável, histórico;
- `source-catalog`: equivalente, catálogo, siglas, métodos, planilha, aba, lista ou parâmetros da fonte;
- `semantic-effect`: referenciar, consumir, alimentar, impactar, gerar ou derivar.

Nenhum candidato pode permanecer `pending`.

## Disposições

- `covered`: exige requisito atômico e evidências correspondentes. Se varias obrigacoes apontarem ao mesmo `requirement_id`, isso e apenas agrupamento editorial: cada obrigacao continua exigindo controle adversarial primario proprio em `requirement-attack-matrix.obligation_control_map`; agregacao nunca reduz a quantidade de provas.
- `deferred`: exige decisão canônica, issue de destino, hash, locator e manutenção da issue pai aberta.
- `not-applicable`: exige decisão canônica e justificativa objetiva.

Não existe `out-of-scope` livre. Documentação ou PR produzidas pela implementação não são decisão de escopo.

Quando houver `deferred`, o handoff deve declarar `issue_completion=partial`, listar todas as `remaining_issue_ids` e marcar `parent_issue_must_remain_open=true`.

## Inventário fechado de domínio

Obrigações `exhaustive` ou `source-catalog` exigem `domain_inventory`:

1. localizar produtores, persistências, enums, schemas, migrations e caminhos legados;
2. localizar consumidores, serializers, renderizadores, routers e fallbacks;
3. enumerar cada valor canônico da fonte, inclusive planilha ou catálogo;
4. vincular cada valor a evidência de produção, consumo e cenário executado;
5. manter `unmapped_values` vazio;
6. não usar fallback genérico para valor conhecido.

Pesquisar produtores e consumidores fora do diff.

## Cobertura de cenarios explicitamente exigidos

Quando uma obrigacao canonica enumerar cenarios que os testes devem cobrir, preservar a lista literalmente na matriz de ataques. Nao converter uma clausula `testes cobrem A, B, C` em uma unica evidencia `suite passou`. Cada caso enumerado deve resultar em entrada de `test_coverage_contract` e controle `test` discriminante proprio; casos de fronteira HTTP/UI, variantes de estado inicial e isolamento continuam distintos mesmo quando executados pelo mesmo arquivo de teste.

## Asserção observável e efeito semântico

Obrigações `observable` ou `semantic-effect` exigem `observable_assertion` com cenário real e controle negativo discriminante.

Para verbos semânticos, comprovar o efeito exato:

- guardar vínculo não prova consumo;
- ler a origem não prova que ela alimenta decisão;
- aceitar alerta do cliente não prova derivação no backend;
- persistir dado não prova que ele impacta resultado.

O controle negativo deve falhar quando o efeito é substituído pela aproximação plausível.

## Cobertura das fontes

`source_coverage` deve coincidir exatamente com todas as fontes textuais do snapshot. Para cada fonte, a contagem e os IDs das obrigações devem ser recompostos e `unmapped_candidate_keys` deve permanecer vazio.

Fonte binária citada exige extração textual vinculada; sem extração, o snapshot é inválido.

## Revisão de redução de escopo

`scope_reduction_review` é recomposto do diff congelado. Frases como `fora do escopo`, `próxima evolução`, `não implementa`, `interface pendente`, `apenas backend`, `fundação backend` e `seed mínimo` devem aparecer exatamente no inventário.

Cada ocorrência deve ser:

- `canonical-decision`, ligada a fonte canônica do snapshot; ou
- `not-a-reduction`, com justificativa específica de por que o texto não retira obrigação.

Ocorrência omitida ou inventada reprova.

## Passagem C — auditor sombra

Executar depois da implementacao e do gate final interno e antes do handoff:

1. ignorar descrição da PR, checklist e resumo da implementação;
2. reler todas as fontes do snapshot;
3. comparar cada substantivo, verbo e qualificador com evidência observável;
4. enumerar produtores e consumidores de domínios fechados;
5. procurar fallbacks, maps fechados, `default`, serializers implícitos e caminhos antigos;
6. confirmar que todos os requisitos têm obrigação de origem e todas as obrigações têm disposição válida;
7. revisar `scope_reduction_review` no SHA final;
8. preencher `reviewed_all_specification_sources=true` somente após concluir a revisão.

A Passagem C é pré-auditoria interna e deve tentar reproduzir a disciplina da auditoria externa.

## Fechamento de contratos transitivos de runtime

Quando o contrato ou o diff contiver sinais de `runtime_policy`, `adapter_contract`, `request_translation`, `legacy_compatibility` ou `documentation_claims`, preencher no `risk_profile` e comprovar nas famílias F28 a F33 de [runtime-contract-gates.md](runtime-contract-gates.md):

- `execution_state_boundaries`;
- `control_propagation_paths`;
- `capability_operation_mappings`;
- `request_translation_mappings`;
- `legacy_compatibility_matrix`;
- `documentation_claim_inventory`.

Cada inventário começa vazio e bloqueia o handoff quando o sinal correspondente estiver ativo. Não aceitar como fechamento resolvedor que apenas retorna `invalid` sem impedir execução, timeout testado só com callback mockado, operação declarada sem método, campo ignorado pelo provider, compatibilidade inferida de arquivo não alterado ou documentação usada como prova de si mesma.

## Aprendizado de escapes

Após achado externo:

1. importar o achado em `later_findings_imported`;
2. classificar a causa: fonte omitida, atomização, qualificador, verbo reduzido, inventário, fronteira errada, fallback, evidência não discriminante, caminho transitivo, `execution-state-gap`, `control-propagation-gap`, `capability-operation-drift`, `adapter-support-drift`, `silent-translation-loss`, `legacy-variant-gap` ou `documentation-claim-drift`;
3. adicionar o caso literal e dois casos irmãos;
4. procurar o padrão em subissues e superfícies relacionadas;
5. criar teste de regressão da skill quando o escape puder ser bloqueado deterministicamente;
6. gerar novo handoff somente após repetir implementação, gate final e Passagem C no novo SHA.

## Fechamentos adicionais obrigatórios

Além de `domain_inventories` e `observable_assertions`, preencher os três portões fail-closed (F25 a F27 de [critical-closure-gates.md](critical-closure-gates.md)):

- `read_model_closures`: prova campo a campo de produtor, projeção pública, consumidor e superfície visível;
- `canonical_source_consistency`: prova que todas as superfícies usam a mesma fonte com fixture divergente;
- `documentation_consistency`: inventário global de termos antigos e novos, inclusive fora do diff.

Todos começam como `pending`. `not-applicable` só é válido com justificativa objetiva e quando o contrato não contém os sinais correspondentes. Os validadores recusam `not-applicable` quando a fonte canônica menciona histórico/versionamento, coerência/fonte canônica ou transição de rota/legado.


## Fechamento de entrada nao confiavel

Quando o contrato ou o diff envolver entrada nao confiavel ou parser, preencher `risk_profile.input_parser_contract` e comprovar F34 conforme [input-parser-gate.md](input-parser-gate.md). O fechamento deve atomizar representacao bruta, ordem de validacao, modos aceitos, campos consumidos, posicionamentos estruturais, codigo de erro e ausencia de efeitos; “arquivo invalido” ou “parser suporta XML/SGML” nao sao requisitos atomicos suficientes.
