# Gate de ancoragem no codigo

## Quando ler este arquivo

Consultar sempre que codigo, testes ou configuracao de descoberta forem alterados, inclusive diffs apenas de testes. Aplicar a validacao no SHA exato, sem presumir equivalencia semantica dos oraculos.

## Índice

- [Objetivo](#objetivo)
- [Quando aplicar](#quando-aplicar)
- [Controles](#controles)
- [Validacao deterministica](#validacao-deterministica)
- [Limites conhecidos](#limites-conhecidos)

## Objetivo

Impedir que a entrega crie o que ja existe, use o que nao existe ou deixe para tras o que substituiu. Toda afirmacao sobre o repositorio deve apontar para bytes do `material_head_sha`; memoria do modelo, nome plausivel e documentacao externa nao sao evidencia.

## Quando aplicar

O planner ativa `codebase-grounding` por `contracts/gate-registry.json` quando `code_touched=true` ou `tests_touched=true`, inclusive diff somente de testes segundo convencoes detectaveis. Registrar em `codebase-grounding.json` (`schemas/codebase-grounding.schema.json`). Arquivo descoberto exclusivamente por runner dinamico exige declaracao de limite UNKNOWN se a arvore/runner nao forem acessiveis; heuristica de nome nao prova completude.

## Controles

### GROUND-REUSE-001 — buscar antes de criar

Antes de criar arquivo de codigo, funcao/classe/componente publico, endpoint, tabela, chave de configuracao ou dependencia:

1. buscar no repositorio por nome, sinonimos e comportamento (texto, simbolos e consumidores), registrando as consultas realmente executadas e o escopo;
2. listar os candidatos encontrados;
3. decidir `reuse`, `extend` ou `create`. `create` com candidato equivalente exige o motivo objetivo de nao reutilizar cada candidato.

Arquivo de codigo adicionado sem registro de busca bloqueia. Arquivo gerado fica isento; teste afetado segue o controle GROUND-TEST-001 especifico abaixo, inclusive quando nenhuma producao foi modificada.

### GROUND-TEST-001 — ciclo de vida dos testes

Antes de adicionar, editar, renomear ou excluir testes e configuracoes de descoberta do runner, inventariar casos, fixtures, parametrizacoes, helpers e niveis no escopo do requisito/risco, incluindo consumidores diretos. Para cada cenario registrar requirement, oracle discriminante, consultas reais, candidatos com comparacao de oraculos, runner e decisao covered-by-existing, extend-existing, new-test-required ou not-testable/blocked. A disposicao e keep, refactor/consolidate, remove-candidate ou needs-investigation. Preferir reaproveitar/estender, salvo necessidade objetiva de setup, nivel, independencia, isolamento ou novo oraculo. Controles historicos positivos, negativos, limites, ataques e gates permanecem.

Registrar uma entrada test_decisions por arquivo de teste alterado (e por cenario quando necessario) no mesmo codebase-grounding.json. Diffs apenas de testes acionam o gate; renomeacoes incluem prior_path. Excluir exige mapa coverage_before/coverage_after, verificacao executada e autorizacao/aviso de operacao destrutiva do repositorio; sinal de duplicacao/obsolescencia nao e prova. Sem runner/checkout, registrar status unknown/blocked e escopo nao verificado; nao declarar READY. A deteccao considera convencoes/runner, incluindo suites dinamicas quando conhecidas e arquivos Cypress `.cy.*` ou E2E `.e2e.*` fora de pastas convencionais; extensoes e nomes sao apenas indicios.

O formato v2 do relatorio exige test_decisions e o validador o confronta com o git diff --name-status -M do base/head. Formato v1 segue aceito apenas se nao houver diff de testes; para diff de testes legado, migrar explicitamente para v2 (rejeicao explicita, nunca compatibilidade silenciosa). O validador confere campos, paths/candidatos, operacoes e verificacao declarada no SHA exato; em exclusoes exige IDs de controles antes/depois sem perda, teste substituto presente no HEAD e evidencia bruta hasheada que identifique o teste alcançado e SHA do HEAD.
Uma decisao `covered-by-existing` em teste **modificado** exige candidato existente identificado na revisao base. O reconhecimento deve ocorrer com a configuracao de descoberta no SHA-base: uma mudanca de runner introduzida apenas no HEAD nao comprova cobertura preexistente. Se o candidato nao for reconhecido pelo runner da base, devolver `UNKNOWN` e exigir prova de execucao historica/dinamica; a mera existencia de um arquivo de producao nao autoriza afirmar cobertura.

Um arquivo de teste **adicionado** nao pode usar essa decisao para justificar sua propria criacao: deve registrar `new-test-required` com justificativa discriminante, ou reaproveitar/estender de fato o teste existente em vez de adicionar arquivo. Em renomeacao, o `prior_path` validado identifica o teste preservado; em exclusao, os controles separados de `replacement_tests` e `coverage_before/coverage_after` comprovam a substituicao declarada. O gate rejeita contradicoes formais observaveis e nao infere equivalencia de oraculos por nomes ou contagens.

Todo `verification.status=passed` em teste alterado exige `subject_sha=material_head_sha`, `reached_tests`,
comando, exit code zero e arquivo de evidencia com SHA-256, incluindo linhas `HEAD:`, `COMMAND:`, `EXIT_CODE:` e
`REACHED:` coerentes com o relatorio. Essas linhas validam apenas a forma/identidade declarada;
nao certificam autenticidade do runner nem qualidade semantica do oraculo, que exigem refutacao independente.
A auditoria deve autenticar a origem dos logs e refutar a equivalencia;
registros autoafirmados nao constituem prova semantica, de descoberta dinamica completa ou de autorizacao de exclusao.

Manifestos de runners (`package.json`, `pyproject.toml`) ativam preflight conservador no planner.
O validador compara as secoes de teste entre base e HEAD: mudancas apenas de versao/metadata nao exigem `test_decisions`.
Para pytest, conferir `python_files` em `pytest.ini`, `pyproject.toml`, `tox.ini` e `setup.cfg`
da raiz e dos ancestrais do caminho modificado, em ambos os SHAs.
Casos correspondentes somente ao padrao configurado exigem GROUND-TEST-001, sem tratar como codigo de producao novo.
Configuracao invalida retorna `UNKNOWN`.
Inspecao estatica nao comprova plugins de descoberta dinamica: exigir evidencia do runner ou `UNKNOWN` fundamentado.
Essas provas pertencem a inspecao independente.

### GROUND-EXIST-001 — provar antes de usar

Para cada simbolo, API, comando, caminho, chave de configuracao ou dependencia que o codigo ou a documentacao nova passou a referenciar:

- `local`: apontar `path:line` da definicao no head;
- `dependency`: apontar o manifesto ou lockfile versionado que declara o pacote;
- em ambos, registrar o arquivo consumidor e o comando executado (import, typecheck, build ou teste) que exercitou a referencia com `exit_code=0`.

Nao deduzir assinatura, parametro ou versao por analogia. Se a prova nao puder ser obtida, o estado e `UNKNOWN` e bloqueia; nunca substituir por suposicao.

### GROUND-DEAD-001 — nao deixar sobra

Para cada caminho ou simbolo substituido pela entrega, declarar `removed` ou `kept`. `kept` exige consumidor real no head; para localizar importadores e chamadores reversos, usar `scripts/map_runtime_consumers.py --repo <checkout> --changed <path>` e tratar `coverage.complete=false` como `UNKNOWN`, nunca como ausencia de consumidor. Dois caminhos para o mesmo comportamento, simbolo novo sem consumidor e codigo antigo mantido "por seguranca" bloqueiam. Complementa `references/hygiene.md`.

### Vinculacao de execucao no GitHub Actions

Para `GROUND-TEST-001`, uma decisao semanticamente revisada pode aguardar
apenas execucao com `verification: {"status": "unknown",
"reason": "awaiting-exact-SHA-JUnit"}`. Nesse caso, o manifesto inclui
`grounding_test_bindings`, indexado pelo `path` de cada decisao pendente,
com entradas explicitas `{"case": "tests/test_example.py::test_case",
"test_case_id": "tests.test_example::test_case"}`. Exclusoes precisam
atingir cada `replacement_tests`; renomeacoes apontam para o caminho novo.
Esse mapa e revisado junto ao dossie; nao se deriva cobertura de nomes.

O helper [bind_grounding_execution.py](../scripts/bind_grounding_execution.py)
confere o HEAD, exit code, hashes do log/JUnit e o resultado `PASSED` do
mesmo caso nos dois formatos. Somente a identidade padrao do pytest e
suportada automaticamente; caso ausente, ignorado, falho, ambiguo ou
customizado permanece bloqueante. O produtor preenche apenas `verification`,
preservando cenarios, oraculos, buscas, decisoes, disposicoes e o dossie
versionado. Provas ja atestadas e outros motivos `unknown` nao sao reescritos.

A prova factual e criada apos os testes sob
`.audit/entregar-issue/execution/`, no checkout e no artefato, com o HEAD,
comando, exit code, casos alcancados e hashes das fontes. O certificado
autoriza individualmente apenas caminhos seguros cujas copias tenham o
mesmo digest, pela opcao existente `--allow-result-path`; nenhum prefixo
inteiro ganha permissao. Assim a prova acompanha o filho de resultados sem
exigir que o dossie contenha uma prova autorreferente do proprio commit.
Os validadores oficiais continuam obrigatorios e o binding nao emite
certificado nem aprovacao semantica.

O publicador confiavel autentica primeiro o certificado, o relatorio de
grounding e cada prova de execucao autorizada. Confere caminhos canonicos,
ausencia de symlinks, hashes, identidade e marcadores da execucao, com limites
de tamanho; entao materializa somente essas provas no checkout material,
antes de reexecutar o validador oficial de grounding. Nenhum codigo do
candidato e executado nessa etapa. Conflitos com arquivos existentes ou
provas ausentes, alteradas ou fora da allowlist bloqueiam a publicacao.

## Validacao deterministica

Executar no gate final, sobre o SHA congelado:

```bash
python scripts/validate_codebase_grounding.py \
  --repo <checkout> --report <codebase-grounding.json> \
  --base-sha <work_item_start_sha> --head-sha <material_head_sha>
```

O validador confere contra o Git: SHA exato, registro de busca para todo arquivo de codigo adicionado, diff de testes (A/M/R/D), decisoes e evidencia formal de preservacao, existencia dos candidatos citados, presenca de simbolos/dependencias e disposicao de cada substituicao. Similaridade nominal nunca basta para bloquear novo teste legitimo. Sem checkout executavel o resultado e `UNKNOWN`, nao aprovacao.

Em `certified-handoff`, passar o relatorio ao builder com `--codebase-grounding`. Quando o escopo local da issue toca codigo, o builder bloqueia sem o relatorio ou com `subject_sha` stale, e `validate_handoff_certificate.py` (entrega e auditoria) recalcula a aplicabilidade a partir do escopo certificado.

## Limites conhecidos

O certificado prova que o relatorio existe e pertence ao SHA; executar o validador em `READY` antes do builder continua sendo obrigacao do controlador. O validador prova que o declarado e verdadeiro; nao prova que a lista de referencias esta completa. Completude e refutada pela auditoria independente (`auditar-issue/references/codebase-grounding-audit.md`).


O modulo `scripts/test_path_discovery.py` centraliza a deteccao de arquivos e runners usada no planejamento e no grounding; a interface legada e preservada. Para `CODE-GROWTH-001`, `--comparison-base-sha` compara o delta contra a base atual da PR, mas a politica permanece ancorada no inicio da issue. Exigir ancestralidade comprovada e justificativas por arquivo acima do limite brando, sem flexibilizar o limite rigido.
