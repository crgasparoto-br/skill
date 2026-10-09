# Harness de avaliações comportamentais

Este diretório implementa os itens `V030-001` e `V030-002` do [roadmap da `v0.3.0`](../docs/ROADMAP.md). O harness é **provider-agnostic**: a CI valida os casos e pode reproduzir resultados versionados sem chamar um modelo externo. Um runtime de IA pode ser conectado posteriormente por replay de resultados ou por um comando explícito.

## Estrutura

```text
evals/
├── manifest.json           # versão e caminhos canônicos do harness
├── cases/                 # casos versionados; o esperado é parte do caso
├── expected/              # documentação de artefatos golden futuros
├── fixtures/results/      # resultados determinísticos para smoke/replay
├── schemas/               # contratos de caso, resultado e relatório
└── run_evals.py           # runner e CLI
```

## Cobertura de seleção

A família `selection` cobre três formas distintas, e cada uma tem sua invariante em `scripts/validate_evals.py`:

| Forma | Bloco `selection` | Esperado |
| --- | --- | --- |
| Empate material | `disambiguation_required: true` e pelo menos dois candidatos | `UNKNOWN` sem skill selecionado |
| Seleção resolvida | `disambiguation_required: false` e exatamente o skill vencedor | `PASS` com skill selecionado |
| Sem correspondência | ausente | `UNKNOWN` sem skill selecionado |

Os casos resolvidos não são narrativos: `tests/test_v030_002_cases.py` aterra cada um no roteador real, comparando `scripts/select_skill.py` com o esperado declarado. Os casos sem correspondência documentam o limite de recall do roteador, que reconhece gatilhos como substring e portanto abstém-se quando o fraseado é reordenado.

## Modos

Validar somente contratos, sem declarar aprovação comportamental:

```bash
python evals/run_evals.py --root . --validate-only
```

Reproduzir resultados fornecidos por um runtime:

```bash
python evals/run_evals.py \
  --root . \
  --results-dir evals/fixtures/results \
  --report /tmp/eval-report.json

python evals/run_evals.py \
  --root . \
  --verify-report /tmp/eval-report.json
```

Conectar um provider explícito. O comando recebe um caso JSON em `stdin` e deve devolver um resultado JSON no stdout:

```bash
python evals/run_evals.py \
  --root . \
  --provider-command 'python /absolute/path/to/provider_adapter.py' \
  --report /tmp/eval-report.json
```

O provider é executado em um diretório temporário; use um caminho absoluto ou um executável disponível no `PATH`.

O runner não usa `shell=True`, executa o provider em diretório temporário, limita stdout, não escolhe um modelo por conta própria e não transforma runtime ausente em `PASS`. Saídas de `provider-command` são sempre `provider-untrusted` e nunca podem aprovar um caso.

O trust `attested` possui contrato estrutural, mas permanece `NOT_RUN` até existir um verificador criptográfico confiável. O replay pode aprovar somente fixtures determinísticos no diretório canônico; esses fixtures validam o contrato e o baseline versionado, não afirmam que um modelo real foi executado. Para avaliações em lote com LLM, o adapter deve descobrir o catálogo de modelos e declarar provider, modelo, métricas e limites no resultado.

## Entradas invalidas

O CLI falha de forma controlada, com status 1 e prefixo `EVAL_HARNESS_ERROR`, sem traceback: argumento desconhecido, `--root` sem valor, vazio ou em branco, raiz em ciclo de links, raiz inexistente ou que nao seja diretorio, `--results-dir` que nao seja diretorio, destino de relatorio que nao possa ser escrito e fixture ou resultado ilegivel.

## Resultado e estados

O caso declara uma decisão esperada: `PASS`, `BLOCK`, `UNKNOWN` ou `NOT_APPLICABLE`. O runner produz o status da avaliação:

- `PASS`: o resultado observável corresponde exatamente ao contrato do caso;
- `FAIL`: o runtime respondeu, mas divergiu do esperado, violou uma proibição ou excedeu orçamento;
- `NOT_RUN`: não houve runtime disponível ou o resultado não foi produzido;
- `INVALID`: o resultado não respeitou o schema.

`NOT_RUN` e `INVALID` nunca são convertidos em aprovação. Em modo `--validate-only`, os casos são apenas validados e a saída é deliberadamente `NOT_RUN`.

O resultado também deve coincidir exatamente com `case_id` e `adapter`, respeitar `response_minimum`, declarar `runtime.trust` e não possuir arquivos extras no diretório de replay. O comando `--verify-report` recalcula `content_sha256` e o resumo antes de aceitar um relatório persistido.

## Relatórios

Cada relatório contém:

- `run_id`: SHA-256 dos casos, modo e resultados consumidos;
- `content_sha256`: SHA-256 do conteúdo lógico do relatório, sem timestamp;
- versão do harness e versões de release declaradas pelos casos;
- status e razões por caso;
- resumo com `passed`, `failed`, `not_run` e `invalid`.

O timestamp serve para observabilidade, mas não participa do hash lógico. Os fixtures em `evals/fixtures/results/` incluem o smoke case do runner e o baseline determinístico dos casos V030-002; `evals/fixtures/manifest.json` fixa os hashes dos resultados e a proveniência do baseline. Eles não representam uma aprovação de comportamento de um modelo real.

## Regenerar fixtures

Ao adicionar ou alterar um caso, grave o resultado correspondente em `evals/fixtures/results/` e refaça o manifesto, porque `validate_fixture_manifest` recusa qualquer divergência entre casos, arquivos e hashes:

```bash
python - <<'PY'
import hashlib, json
from pathlib import Path

fixtures = Path("evals/fixtures/results")
manifest_path = Path("evals/fixtures/manifest.json")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest["results"] = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(fixtures.glob("*.json"))
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
```

O manifesto cobre exatamente os casos existentes: resultado sem caso, caso sem resultado e hash divergente falham de forma explícita.
