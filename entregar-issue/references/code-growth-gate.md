# Gate de crescimento de codigo

## Objetivo

Impedir que a entrega concentre responsabilidade em arquivos grandes. `CODE-GROWTH-001` mede linhas totais dos arquivos de codigo do escopo local da issue no `material_head_sha` contra o `work_item_start_sha`.

## Politica

Padrao, usado quando o repositorio nao define politica propria:

| Situacao | Resultado |
| --- | --- |
| arquivo novo ate `new_file_soft_limit` (300) | passa |
| arquivo novo acima de 300 e ate `new_file_hard_limit` (500) | passa somente com justificativa registrada |
| arquivo novo acima de 500 | bloqueia |
| arquivo existente que cruza 500 | bloqueia |
| arquivo que ja excedia 500 e cresce ate `legacy_growth_allowance` (20) linhas liquidas | passa |
| arquivo que ja excedia 500 e cresce mais de 20 | bloqueia: extrair antes de acrescentar |

Testes, gerados e caminhos com marcadores de `exempt_path_markers` (vendor, dependencias instaladas, migrations) ficam isentos.

O repositorio pode sobrescrever os valores em `.github/code-growth-policy.json`. A politica e lida **somente do `work_item_start_sha`**: alteracao feita pelo proprio candidato nunca afrouxa o limite da propria entrega. Politica invalida bloqueia; ausencia usa o padrao.

## Execucao

No gate final, sobre o SHA congelado:

```bash
python scripts/check_code_growth.py \
  --repo <checkout> --base-sha <work_item_start_sha> --head-sha <material_head_sha> \
  --justifications <justificativas.json> --out <code-growth.json>
```

`--justifications` e um objeto `caminho -> motivo` e so e necessario para arquivo novo na faixa intermediaria. Bloqueio se resolve dividindo ou extraindo, nunca ajustando a politica ou reclassificando o arquivo como isento. Sem checkout executavel o resultado e `UNKNOWN`.

Em `certified-handoff`, passar o relatorio ao builder com `--code-growth`; quando o escopo local da issue toca codigo, o builder bloqueia sem relatorio `passed` do SHA exato e a auditoria o refuta conforme `auditar-issue/references/code-growth-audit.md`.
