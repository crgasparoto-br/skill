# Política de releases e compatibilidade

## Superfícies de versão

| Superfície | Exemplo | Finalidade |
| --- | --- | --- |
| `VERSION` | `0.2.0` | Versão pública SemVer do conjunto de skills e adaptadores. |
| `config/skills-catalog.json.catalog_version` | `2026-09-29.5` | Snapshot temporal do catálogo e da governança interna. |
| `config/skill-system-requirements.json.system_version` | `2026-09-29.5` | Versão das invariantes globais do sistema. |
| `contracts/version.json.contract_version` | `2026-08-20.3` | Linhagem interna legada dos contratos já consumidos pelas skills. |
| `config/compatibility.json.contract_policy.public_contract_version` | `1.0.0` | Versão pública SemVer do contrato de composição. |

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
| Forma e vínculo | `scripts/validate_dependency_locks.py`, obrigatório e offline | Manifest e lockfile precisam resolver para dentro da raiz do repositório, e a política também, e um manifest que não seja arquivo regular reprova em vez de ser omitido da descoberta: um caminho que escape traria para a verificação arquivo que o repositório não versiona. Cada requisito declarado aparece com versão que **satisfaz o especificador declarado**, com ordenação PEP 440 completa em que pré, pós e dev são eixos independentes e com a semântica de versão local em `==` e `!=`; inclusão `-r` que não resolve, não é manifest ou sai da raiz reprova, opção que o gate não implementa reprova em vez de ser ignorada, e linha de requisito que o gate não interpreta reprova em vez de ser descartada; requisito com marcador falso não é exigido, avaliado contra o interpretador que executa o gate, com a gramática do marcador validada por inteiro antes de qualquer atalho lógico; a cadeia `# via` alcança pacote declarado; o lockfile aceita somente `--hash` como opção e uma anotação de artefato por entrada; cada entrada nomeia artefato com sufixo de distribuição e campos de nome e versão exatamente iguais aos fixados, com a gramática da distribuição verificada — a wheel precisa nomear Python, ABI e plataforma, e o sdist tem exatamente dois campos; cada exceção nomeia pacote e versão existentes |
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

A consulta ao banco de vulnerabilidade e a verificação de integridade são do workflow
[`.github/workflows/dependency-audit.yml`](../.github/workflows/dependency-audit.yml), com gatilho agendado, manual e em
pull request que toca manifest, lockfile ou política. Ele nunca faz parte da sequência obrigatória: quando o banco, o
artefato ou a ferramenta não estão disponíveis, o resultado é `UNKNOWN` e reprova aquele job, porque ausência de
verificação não é verificação de ausência.
