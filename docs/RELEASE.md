# Política de releases e compatibilidade

## Superfícies de versão

| Superfície | Exemplo | Finalidade |
| --- | --- | --- |
| `VERSION` | `0.3.1` | Versão pública SemVer do conjunto de skills e adaptadores. |
| `config/skills-catalog.json.catalog_version` | `2026-10-08.2` | Snapshot temporal do catálogo e da governança interna. |
| `config/skill-system-requirements.json.system_version` | `2026-10-08.2` | Versão das invariantes globais do sistema. |
| `contracts/version.json.contract_version` | `2026-08-20.3` | Linhagem interna legada dos contratos já consumidos pelas skills. |
| `config/compatibility.json.contract_policy.public_contract_version` | `1.0.0` | Versão pública SemVer do contrato de composição. |

A skill `higienizar-repositorio` foi declarada com `min_release` `0.2.0` enquanto a release pública corrente era a `0.2.0`, porque o manifesto de compatibilidade não aceita declarar release futura. A v0.3.0 elevou o campo para `0.3.0` no mesmo change set que atualizou `VERSION`, e a divergência é verificada por `scripts/validate_versioning.py`.

A versão pública é a referência para consumidores externos. A linhagem interna não deve ser alterada silenciosamente: durante a transição, uma entrada explícita em `config/compatibility.json` mapeia cada versão pública para a linhagem interna suportada.

## Regras SemVer

- **MAJOR:** quebra de schema, mudança de semântica, remoção de campo, mudança de autoridade ou incompatibilidade que exige migração.
- **MINOR:** capacidade, campo, adapter, skill ou comportamento aditivo compatível.
- **PATCH:** correção compatível, documentação, validação mais precisa ou correção de erro sem mudança de contrato.

Alterar apenas a data de catalogação ou uma implementação interna não autoriza esconder uma quebra de contrato. Se consumidores precisarem alterar o modo de carregamento ou de interpretação, a versão pública deve refletir isso.

## Checklist de release

1. Atualizar `VERSION` conforme SemVer.
2. Atualizar `catalog_version` e `system_version` no mesmo change set.
3. Atualizar `config/compatibility.json`, incluindo `min_release`, `migration` e o mapeamento de contrato.
4. Adicionar a entrada correspondente em `CHANGELOG.md`.
5. Executar `python scripts/validate_versioning.py`.
6. Executar `python scripts/validate_repository.py`, a suíte de testes e os checks do CI.
7. Após o merge, criar uma tag anotada `v<VERSION>` apontando para o commit final revisado.
8. Nunca reutilizar uma tag ou publicar uma release com manifesto diferente do commit tagueado.

A criação da tag e da release é deliberadamente posterior ao merge; uma pull request não cria uma release imutável.

## Limites declarados da v0.3.0

A promoção da v0.3.0 foi decidida pelo responsável com seis critérios de aceite declarados como abertos, para que a
publicação não dependesse de trabalho fora do escopo das entregas concluídas. A mesma lista está no
`docs/ROADMAP.md`, e as notas a publicar e o changelog desta release repetem os seis itens:

- **licença:** não escolhida, por decisão explícita do responsável neste momento; a ausência é intencional e
  rastreável;
- **varredura de segredos:** sem decisão registrada; depende de configuração da conta, não do repositório;
- **revisão de dependências em pull request:** não habilitada; a auditoria de dependências do passo 4 de `V030-003`
  existe e roda em `.github/workflows/dependency-audit.yml`, com `UNKNOWN` em vez de sucesso quando não consegue
  verificar, e é ela que cobre esse lado da cadeia de suprimentos;
- **matriz de Python:** a suíte roda em uma única versão do interpretador; adotar matriz exigiria um lockfile por
  versão, que é exatamente a decisão do passo 6 de `V030-003`;
- **pinagem de Actions por SHA completo:** a sequência obrigatória já pina as actions que usa, e o workflow de
  auditoria de dependências ainda referencia `actions/checkout` e `actions/setup-python` por etiqueta de versão;
- **contrato `transitional`:** a compatibilidade segue mapeada para a linhagem `2026-08-20.3` sem inventário e plano
  de migração amplos.

Os casos de prompt injection não estão entre os itens abertos: a matriz `V030-002` os cobre em `evals/cases/V030-002-authority-001.json`, `-002.json`, `-003.json` e `-004.json`,
com conteúdo hostil vindo de README, de issue, de fixture e de contrato, na mesma ordem.

## Handoff de release

Promover `develop` a `main` segue um contrato verificável, e não uma decisão de memória. `scripts/release_handoff.py`
recebe a evidência declarada e reprova quando falta item obrigatório, quando um identificador é desconhecido,
quando o commit não é hexadecimal de 40 caracteres, quando `develop` e `main` estão no mesmo commit ou quando a
auditoria independente não consta como aprovada. A política em `config/release-handoff.json` declara cada item
obrigatório com o motivo pelo qual ele existe.

O contrato **não** tem autoridade de merge, de tag ou de publicação: ele reúne e verifica evidência, e promover a
release continua sendo ato de quem opera o repositório.

A prova de ausência de autoridade é semântica sobre o texto do contrato: importação fora da lista permitida é
recusada, nome proibido é recusado como variável, como atributo — inclusive dunder, a via de introspecção — e como
texto exato. O limite é declarado: quem tem permissão de escrita no contrato tem igual permissão no gate, então o
contrato protege contra aquisição **acidental** de autoridade num commit revisado, e não contra autor com escrita
no repositório, que poderia alterar as duas peças. Por isso a revisão de código continua sendo o controle de
último recurso, e o contrato apenas a torna verificável. A execução da sequência de validação também não é
terceirizada ao contrato: ele consome o resultado da sequência como evidência declarada, com a origem registrada
no relatório.

```bash
python scripts/release_handoff.py --root . --evidence evidencia.json --develop "$(git rev-parse develop)" --main "$(git rev-parse main)"
```

O contrato falha fechado e de forma legível: toda entrada inválida — tipo, formato, identificador, parecer, destino de
relatório ou argumento de linha de comando — resulta em recusa declarada, nunca em exceção não tratada. O relatório
usa arquivo temporário exclusivo, de nome imprevisível, e troca atômica: a escrita não pode ser desviada por um link
criado entre a conferência e a abertura. O destino é recusado quando é relativo, quando fica fora da raiz, quando não
é arquivo regular, quando passa por link simbólico, quando é diretório ou link físico, quando já existe um caminho
temporário reservado ou quando Markdown e JSON colidem. Um destino ainda inexistente é criado, desde que o diretório
pai exista. O contrato nunca sobrescreve o contrato executável da raiz auditada, a política ou a própria evidência. O
diretório de destino ainda é reconferido pela identidade do inode imediatamente antes da substituição, para que a
troca do próprio diretório durante a escrita seja detectada. O limite é declarado: a proteção cobre os artefatos do
handoff e pressupõe que nenhum outro processo escreve na árvore auditada durante a verificação, premissa já assumida
pela prova de ausência de autoridade; fechar a corrida remanescente entre essa reconferência e a substituição exigiria
primitivas de descritor de diretório, que o contrato não usa. Qualquer outro caminho do repositório é escolha de quem
opera, e apontar o relatório para um arquivo versionado o substitui.

O gate `scripts/validate_release_handoff.py` valida a política, a ausência de autoridade no contrato e executa a
evidência completa; ele também falha fechado, inclusive quando a raiz informada não pode ser resolvida.

## Paridade da versão do harness de avaliações

O pacote `evals/` exporta a versão que o manifesto do harness declara, e essa paridade é verificada por
`scripts/validate_evals.py`. A prova sólida é estática e não executa o código auditado: `evals/__init__.py` só é
aceito como envelope canônico — docstring inicial opcional, uma atribuição simples de `__all__` com lista literal de
textos sem repetição nem nome vazio contendo `__version__`, uma atribuição simples de `__version__` com texto literal
igual ao manifesto, e nenhuma outra instrução. Fora do envelope a recusa é imediata, o que elimina por construção as
formas de religar os nomes por alias, `__dict__`, `globals`, `exec`, importação coringa, decorador, metaclasse,
compreensão, `type`, `importlib` e alvo indireto em `for`, `with` e `async`.

Depois da importação, e de novo depois da execução das avaliações, os valores efetivos exportados são reconferidos:
tipo, igualdade com o manifesto, lista de textos sem repetição nem nome vazio e origem dentro da raiz auditada. O
limite é declarado: essa reconferência é defesa em profundidade, não prova. Ela roda no mesmo processo do código
auditado, então código que adultere deliberadamente o interpretador ou os atributos do próprio módulo importado —
`builtins.getattr`, `sys.modules`, a classe do módulo ou atributos como `__file__` — pode mascará-la. A propriedade verificável é a checagem estática do envelope, que não executa nada; a
reconferência serve para detectar alteração não deliberada, e não para resistir a autor com escrita no repositório.
As pendências de endurecimento restantes dessa classe são acompanhadas em issues e não bloqueiam a promoção,
porque não alteram o conteúdo verificado da release.

## Compatibilidade e migração

Cada skill validada deve aparecer no manifesto de compatibilidade com sua versão pública de contrato, linhagem interna, release mínima suportada e instrução de migração. Uma combinação não declarada deve ser tratada como `UNKNOWN` ou incompatível, nunca como compatível por aproximação textual.

Cada adapter validado deve aparecer em `config/platform-adapters.json` e `config/compatibility.json` com `introduced_in`/`min_release` iguais. A release `0.2.0` introduz `generic`, `openai`, `claude`, `gemini`, `ide` e `application` sem presumir capacidades do host.

| Adapter | Introduced in | Compatibility status |
| --- | --- | --- |
| `generic` | `0.2.0` | `supported` |
| `openai` | `0.2.0` | `supported` |
| `claude` | `0.2.0` | `supported` |
| `gemini` | `0.2.0` | `supported` |
| `ide` | `0.2.0` | `supported` |
| `application` | `0.2.0` | `supported` |

Ao remover uma versão, mantenha uma nota de migração e a última release que a suporta. Não apague o histórico do changelog para esconder uma quebra.

## Análise estática do código
O código Python do catálogo é verificado por um gate determinístico e offline, `scripts/validate_lint.py`, que executa
o Ruff com a seleção derivada de `config/lint-policy.json` e reprova qualquer diagnóstico das regras aplicadas.
```bash
python scripts/validate_lint.py --root .
```
A política é a única fonte da seleção: toda família de regras do Ruff aparece exatamente uma vez como aplicada,
aplicada em parte com a parte desligada declarada, ou dispensada com motivo escrito. A cobertura é conferida no nível
da regra, não no nível do prefixo: uma família aplicada precisa aplicar todas as suas regras, uma família parcial
precisa deixar cada regra decidida entre aplicada e desligada, e uma família dispensada não pode selecionar nem
desligar nada. Uma família parcial que desliga tudo é recusada, porque isso é uma dispensa disfarçada. Acrescentar
uma família nova ao catalogo da ferramenta sem decidir sobre ela reprova o gate, e uma dispensa sem motivo escrito
também, de modo que a cobertura não pode encolher em silêncio. A versão da ferramenta é fixada exatamente no manifest e no lockfile, o que o gate de
dependências confere, e declarada na política: este gate compara a versão instalada com a declarada e reprova a
divergência, porque subir de versão muda o catalogo de regras e exige decisão explícita.
### O que cada verificação prova
| Verificação | O que prova |
| --- | --- |
| Família do catalogo sem decisão | que nenhuma família de regras ficou desligada por omissão |
| Família dispensada sem motivo escrito | que a dispensa é deliberada e revisável |
| Versão instalada igual à declarada | que o resultado não depende de uma versão implícita da ferramenta |
| Supressão em linha com código permitido e justificativa própria | que a supressão foi revisada no ponto em que aparece |
| Supressão que não suprime nada | que uma diretiva morta não permanece no código |
| Regra sem decisão dentro da família | que a cobertura não encolhe por seleção estreita nem por `ignore` contraditório |
| Diretiva em qualquer caixa e diretiva de arquivo | que a supressão que a ferramenta reconhece não escapa da política |
| Arquivo coberto fora da raiz, em diretório ilegível ou com sufixo coberto | que a descoberta reprova em vez de omitir código em silêncio |
| Saída da ferramenta em formato inesperado | que a falha é reprovação com causa explícita, nunca traceback nem aprovação |
| Diagnóstico de regra aplicada | que a sujeira reprova a entrega em vez de depender de revisão manual |
### O que fica fora, e por quê
As famílias dispensadas e as partes desligadas das famílias parciais estão declaradas na própria política, cada uma
com o motivo escrito. O recorte mais visível: formatação e largura de linha, porque o repositório escreve linhas
longas de propósito; docstring por símbolo, porque a documentação normativa vive em `SKILL.md` e nas referências;
regras de segurança no estilo bandit, que se sobrepõem a `docs/SECURITY.md` e à auditoria de dependências; captura
ampla de exceção, que é o contrato fail-closed dos validadores; e complexidade, que não é sinal de correção aqui.
### Supressões
Uma supressão só é aceita quando o código está na lista permitida da política e a própria diretiva traz a
justificativa depois de ` - `. Uma política quebrada interrompe a validação ali: seleção, arquivos, supressões e análise
dependem de uma política íntegra, então nada derivado dela é consultado e a reprovação traz a causa em vez do sintoma
que a ferramenta reportaria em cima de uma seleção inválida. Forma bruta inválida, como `families` ausente ou nulo,
entrada de família que não é objeto, `select` que não é lista e `line_length` que não é objeto reprovam pelo mesmo
caminho, sem traceback.
A leitura cobre as formas que a ferramenta reconhece: o marcador em qualquer caixa e a
diretiva de arquivo com prefixo `ruff:` ou `flake8:`. Supressão de arquivo sem código é recusada, porque desliga a
análise inteira sem deixar o alvo declarado, e diretiva que não suprime nada reprova. A leitura é feita sobre
comentários reais, então a mesma sequência dentro de uma string não conta como supressão. A lista permitida existe
para o caso em que o import precisa vir depois do ajuste de `sys.path`, situação em que a supressão é local e o
motivo fica visível. Corrigir o diagnóstico é preferível a suprimi-lo, e uma supressão nova exige decisão de política
no mesmo commit.
### Escopo varrido
O que o gate varre é declarado na política, não presumido pelo código: os sufixos cobertos (`.py` e `.pyi`) e os
diretórios excluídos, que são controle de versão, cache de ferramenta ou saída de empacotamento gerada. Um arquivo
coberto que seja link simbólico para fora da raiz, um diretório do escopo que seja link simbólico, um link quebrado
ou em ciclo, um diretório ilegível, uma saída da ferramenta vazia ou em formato inesperado, a ausência do executável
no momento da análise e um conjunto varrido sem nenhum arquivo coberto reprovam com causa explícita, em vez de
reduzir o conjunto analisado em silêncio ou tratar o vazio como aprovação.
### Forma bruta da política
Booleano e fração não são inteiros: `schema_version: true`, `schema_version: 1.0`, `line_length.value: true` e
`line_length.value: 100.0` reprovam, porque em Python `True == 1` e `1.0 == 1` e a coerção aceitaria uma forma que
ninguém declarou. O que a política exige é o inteiro exato. Os campos `tool.install` e `tool.invocation` também são verificados, e não
apenas declarados, e por forma exata: a instalação precisa ser o pip pelo lockfile com `--require-hashes`, com
caminho relativo dentro da raiz, e a invocação precisa ser a ferramenta declarada com seu subcomando. `description`
precisa ser texto não vazio, e a instalação precisa ter um único `-r`, com lockfile relativo, sem `..`, sem caminho
absoluto e sem lockfile extra ou repetido. Procura textual deixaria passar `echo pip install ... && outra coisa`. O estado de família precisa ser texto, e uma
forma que não pode sequer ser comparada, como dicionário ou lista, reprova em vez de estourar.
### Limite declarado
O gate verifica presença e extensão do motivo declarado, não a veracidade dele: um motivo longo e enganoso passa.
A honestidade do motivo depende da revisão independente da mudança, e é por isso que alterar a política é alteração
revisável que precisa vir no mesmo commit do código que ela autoriza.
Os diretórios excluídos são pulados por nome, então um link simbólico que use um desses nomes não é inspecionado: o
que decide é o escopo declarado na política, e alterá-lo é a forma de mudar o conjunto varrido.

## Dependências e política de exceção

Cada manifest de skill (`<skill>/requirements*.txt`) tem um lockfile irmão com o mesmo nome e sufixo `.lock.txt`, que
fixa versão exata, o artefato escolhido e o hash sha256 de cada distribuição do fechamento transitivo. O lockfile é
derivado, nunca fonte de verdade: alteração de dependência começa no manifest e o lockfile é regenerado.

```bash
python scripts/lock_dependencies.py --manifest entregar-issue/requirements.txt
python scripts/validate_dependency_locks.py --root .
```

Cada entrada declara `# via <pais>` quando é transitiva e `# arquivo: <distribuição>` antes da própria linha, para que
o digest tenha um artefato nomeado a que se referir. O cabeçalho registra o manifest de origem, o contexto de
resolução e o comando de regeneração. Como o hash corresponde à distribuição escolhida naquele contexto, regenerar em
outra plataforma pode alterar o hash sem alterar a versão; a regeneração é uma alteração revisável, e o validador
reprova entrada sem hash ou sem artefato justamente para que a mudança apareça.

### O que cada verificação prova

| Verificação | Onde roda | O que prova |
| --- | --- | --- |
| Forma e vínculo | `scripts/validate_dependency_locks.py`, obrigatório e offline | Cada manifest do repositório, inclusive o do ferramental na raiz, tem lockfile irmão. Manifest, lockfile e política precisam resolver para dentro da raiz do repositório, o manifest precisa ser arquivo regular, todo lockfile precisa ser pareado **nominalmente** com um manifest e nenhum lockfile órfão alimenta o índice da política. Cada requisito declarado aparece com versão que **satisfaz o especificador declarado**; a cadeia `# via` alcança pacote declarado; o lockfile aceita somente `--hash` como opção e uma anotação de artefato por entrada; cada entrada nomeia artefato cujo nome e versão são exatamente os fixados. Gramática de versão, especificador, requisito, marcador e nome de distribuição é interpretada pelo `packaging`, declarado em `requirements.txt` e instalado pelo lockfile da raiz: forma que a implementação de referência das PEPs 440, 508 e 427 recusa **reprova em vez de ser aproximada**, o que cobre especificador com fase em curinga, extras com forma inválida, nome de projeto com pontuação final, exigência direta por URL, etiqueta de wheel inválida e marcador com nome fora da norma A resolução real é verificada na sequência obrigatória por `scripts/lock_dependencies.py --check`, que regenera o lockfile e compara o **fechamento resolvido** — pacotes, versões e arestas de dependência. Contexto, nome do artefato e digest são do ambiente que resolveu e, quando o contexto é de outro ambiente, a comparação os ignora e a integridade fica com `scripts/audit_dependencies.py`, que confere o digest contra o artefato real. É o que reprova fechamento forjado e transitiva que um extra ativa e ficou de fora: é o que reprova fechamento forjado e transitiva que um extra ativa e ficou de fora, coisas que o gate offline não pode resolver por não tocar a rede |
| Integridade do digest | `scripts/audit_dependencies.py`, fora da sequência obrigatória | O digest corresponde ao artefato, conferido por `pip download --no-deps --require-hashes`; um hash arbitrário com formato válido só é detectável com o artefato em mãos |
| Vulnerabilidade | `scripts/audit_dependencies.py` | Nenhum aviso do banco de vulnerabilidade ficou fora da política |

O gate offline não afirma integridade que não pode verificar: ele prova o vínculo entre nome, versão, artefato e
digest, e a satisfação do especificador. Um digest fabricado passa pelo gate offline e reprova na verificação de
integridade, que é onde o artefato está disponível.

### Vínculo de contexto

O lockfile é resolvido em um contexto — versão de Python, plataforma e arquitetura — e registra esse contexto no
cabeçalho. O digest pertence à distribuição escolhida naquele contexto, e por isso outra versão de Python pode
escolher outro arquivo, com outro digest, e reprovar a instalação por divergência de hash. Esse é o comportamento
pretendido: a divergência aparece em vez de passar silenciosamente. A sequência obrigatória usa Python 3.12, a mesma
versão registrada nos lockfiles, e adotar uma matriz de versões exigiria um lockfile por versão.

Manifest e lockfile precisam ser arquivo regular, e o que a regra exclui é o caminho que não leva a um arquivo legível: symlink pendente, diretório e caminho fora da raiz. Symlink interno para arquivo versionado continua válido, porque o conteúdo verificado é o do arquivo alcançado e permanece sob a raiz.

O `packaging` é a autoridade de gramática, e é por isso que `requirements.txt` na raiz declara essa dependência: a alternativa seria aproximar as normas à mão, e aproximação de norma é onde a ambiguidade entra.

A garantia de confinamento é sobre o caminho resolvido: symlink que escape reprova, e um hard link para arquivo fora
da raiz permanece sob o caminho resolvido, o que é uma limitação conhecida da verificação, não uma afirmação de
proveniência por inode.

O cabeçalho é documentação, não autoridade: marcador de ambiente é avaliado contra o interpretador que executa o gate,
e não contra o contexto declarado no comentário. Um comentário editável como autoridade permitiria declarar um
contexto falso para tornar falso um marcador verdadeiro e omitir uma dependência real. A gramática do marcador é
validada por inteiro antes de qualquer atalho lógico, e versão e especificador precisam ser PEP 440 válidos por
completo: forma que o gate não reconhece reprova em vez de ser aproximada.

### Política de exceção

Vulnerabilidade sem correção disponível só pode ser tolerada com exceção declarada em
[`config/dependency-policy.json`](../config/dependency-policy.json), com identificador, **pacote**, **versão fixada**,
justificativa e data de revisão. A versão é obrigatória porque tolerar um pacote sem dizer qual versão permitiria
encobrir qualquer versão futura.

Reprova: exceção sem justificativa, sem data, sem pacote, sem versão, com identificador repetido, apontando pacote ou
versão ausentes dos lockfiles, com data fora da forma `YYYY-MM-DD`; e exceção cujo identificador não aparece em nenhum
achado do banco, porque ela toleraria algo que o banco não reporta.

Não reprova, e é reportado como aviso: exceção com data de revisão vencida, porque data vencida é decisão de pessoa e
não defeito de arquivo.

A auditoria exige que a exceção case identificador **e** pacote **e** versão do achado: só o identificador permitiria
encobrir outra dependência.

### Workflow

A sequência obrigatória instala as dependências de teste do próprio lockfile com `--require-hashes`, de modo que o ambiente que executa o gate é o ambiente registrado.

A sequência documentada é comparada com a do workflow pelo teste de paridade, que lê os passos com um parser de YAML
e é fail-closed na forma do documento: exige um único documento, recusa chave duplicada no mesmo mapeamento, exige
`jobs` objeto não vazio, cada job objeto, `steps` lista não vazia e cada passo objeto com `run` ou `uses` — e não os
dois —, com valor textual. Chave repetida é recusada pelo valor construído, então `true` e `True`, `01` e `1`, `null`
e `~` contam como a mesma chave, e chave que não pode ser comparada reprova em vez de estourar. Cada linha de
`run` é conferido em duas partes, e nenhuma delas é procura textual. A linha inteira precisa casar com a gramática
declarada: `python` seguido de um alvo e de argumentos sem metacaractere de shell, com no máximo um redirecionamento
simples de saída, com ou sem `2>&1`. Composição (`&&`, `||`, `;`, `|`, `&`), substituição (`$()`, crase), aspas,
escape, descritor de arquivo (`2>`, `1>`, `10>`), redirecionamento extra, `python -c` e invólucros (`eval`, `env`,
`sudo`, `time`, `nohup`, `xargs`, `sh -c`) não casam. Além disso, o alvo precisa estar declarado: um script de
validação declarado um a um, que existe como arquivo regular sob a raiz e não passa por link simbólico, ou um dos
módulos declarados (`pip`, `pytest`). Assim um marcador escrito em um argumento não promove um script arbitrário, um
nome parecido sem arquivo não passa, um `validate_algo.py` recém-criado não entra na sequência por conta própria e um
link com nome declarado não vale pelo conteúdo que ele aponta.

Duas limitações são declaradas, e não achados: o destino do redirecionamento é conferido como texto de comando, sem
confinamento de caminho, porque a sequência grava o relatório de avaliações em `/tmp`; e a autenticação de um comando
de módulo recai sobre o alvo declarado (`pip`, `pytest`), não sobre cada argumento, de modo que mudar argumentos de um
passo já declarado aparece na revisão da mudança, e não como reprovação do gate. Essa classificação é executada por `scripts/validate_workflow_classification.py`, que está na sequência
obrigatória e também confere a paridade entre CI, README e AGENTS, e não apenas por um teste. Assim, uma forma alternativa de escrever o mesmo passo ativo, ou uma forma estrutural
inválida que o parser aceitaria, não passa sem classificação.
A consulta ao banco de vulnerabilidade e a verificação de integridade são do workflow
[`.github/workflows/dependency-audit.yml`](../.github/workflows/dependency-audit.yml), com gatilho agendado, manual e em
pull request que toca manifest, lockfile ou política. Ele nunca faz parte da sequência obrigatória: quando o banco, o
artefato ou a ferramenta não estão disponíveis, o resultado é `UNKNOWN` e reprova aquele job, porque ausência de
verificação não é verificação de ausência.
