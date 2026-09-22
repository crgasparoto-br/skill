# Gate de invariantes estruturais e caminhos canonicos

## Objetivo

Impedir que um candidato passe apenas porque o caminho feliz funciona quando a especificacao tambem proibe uma arquitetura, precedencia, dependencia, fonte concorrente ou relacao semanticamente invalida entre registros ligados. Tratar `nao criar`, `nao manter`, `reutilizar`, `fonte canonica`, `fonte unica`, `nao depender`, `nao interceptar`, `nao cair no fallback`, `nao misturar sem conversao` e equivalentes como requisitos verificaveis de primeira classe.

## Taxonomia obrigatoria

Classificar obrigacoes aplicaveis com uma ou mais familias:

- `structural`: restricao sobre arquitetura, compartilhamento, acoplamento ou forma de implementacao;
- `forbidden-implementation`: uma implementacao plausivel e explicitamente proibida;
- `canonical-path`: um caminho especializado deve reutilizar ou permanecer semanticamente equivalente ao caminho canonico;
- `dependency-independence`: o comportamento deve continuar correto sem uma dependencia opcional/fallback/provider;
- `precedence`: ordem de parsers, handlers, fallbacks ou fontes altera a correcao;
- `relational-integrity`: dois ou mais registros ligados carregam a mesma dimensao semantica ou participam da mesma quantidade de dominio, e o resultado so e valido se essa relacao for compativel.

Nao considerar requisito estrutural fechado apenas porque um teste end-to-end termina com a resposta correta ou porque fixtures felizes usam valores coerentes entre si.

## `CANON-DIVERGENCE-001`

Aplicar quando coexistirem caminho especializado e caminho canonico para a mesma intencao/acao.

1. Escolher uma entrada que ambos reconhecem ou deveriam reconhecer.
2. Executar a mesma entrada nos dois caminhos antes da compensacao posterior.
3. Comparar todos os campos de dominio materialmente relevantes, inclusive ausencia/presenca, normalizacao e destino.
4. A implementacao errada plausivel e: o caminho especializado produz representacao mais pobre e um handler posterior mascara a perda reexecutando o caminho canonico.
5. O controle falha se o especializado perder, inventar ou contradizer qualquer campo que o canonico preserve, mesmo que o resultado publico final seja corrigido depois.
6. Repetir pelo menos dois casos irmaos variando dimensoes que causam divergencia, como verbo/preposicao, alias/acentuacao, ordem ou fallback.
7. Se houver vocabulario/regex/enum equivalente duplicado em mais de um caminho, exigir uma unica fonte compartilhada ou evidencia de que a duplicacao e deliberadamente gerada e testada contra divergencia.

## `REL-SEM-001`

Aplicar quando um calculo, agregado, projecao, saldo, quota, limite, classificacao ou outro resultado depende de uma dimensao semantica repetida ou derivada em registros relacionados.

Exemplos transferiveis: unidade no item e no recipiente; moeda no movimento e na conta; timezone no evento e no calendario; tipo de recurso no pedido e no objeto referenciado. O gate protege a **classe relacional**, nao esses dominios especificos.

1. Inventariar onde a dimensao nasce, onde e copiada/derivada e quais produtores podem altera-la (`create`, `update`, importacao, reconciliacao, migracao, backfill, adapter ou produtor equivalente).
2. Formular a implementacao errada plausivel: o consumidor particiona/rotula corretamente, mas o produtor aceita valores semanticamente incompatíveis entre registros ligados.
3. Criar valores deliberadamente incompatíveis nos registros relacionados e atravessar o **entrypoint canonico de escrita/mutacao**, nao apenas um helper ou o consumidor agregado.
4. Exigir uma destas saidas contratuais antes de qualquer efeito downstream:
   - rejeicao fail-closed sem escrita/efeito parcial; ou
   - transformacao/conversao explicita com representacao suficiente para cada lado da relacao.
5. Releitura ou consumidor downstream deve confirmar que a relacao invalida nao foi persistida nem reinterpretada silenciosamente.
6. Cobrir pelo menos dois casos irmaos em dimensoes distintas de produtor/lifecycle, por exemplo criacao versus atualizacao, origem versus destino, produtor principal versus importador/backfill.
7. Se o modelo persistente permite estado incompatível por design historico, o candidato deve definir como esse estado e detectado/isolado antes do agregado; confiar apenas que "dados novos serao coerentes" nao fecha o gate.

Fixture em que os dois lados usam o mesmo valor nao discrimina essa classe. Teste apenas do `GROUP BY`, serializer, formatter ou label tambem nao fecha a superficie.

## Fechamento

`structural_invariant_closures.status=passed` somente quando:

- toda obrigacao estrutural coberta estiver ligada a uma entrada;
- cada entrada declarar a implementacao errada plausivel;
- houver evidencia positiva e controle negativo discriminante;
- `REL-SEM-001` estiver presente sempre que a mesma dimensao material atravessar registros ligados ou produtor + consumidor;
- cenarios irmaos tiverem sido exercitados quando houver dimensoes equivalentes baratas;
- `unresolved_invariants=[]`.

Usar `not-applicable` somente quando nenhuma obrigacao da especificacao nem arquitetura tocada possuir familia estrutural.
