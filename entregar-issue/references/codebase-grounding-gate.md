# Gate de ancoragem no codigo

## Objetivo

Impedir que a entrega crie o que ja existe, use o que nao existe ou deixe para tras o que substituiu. Toda afirmacao sobre o repositorio deve apontar para bytes do `material_head_sha`; memoria do modelo, nome plausivel e documentacao externa nao sao evidencia.

## Quando aplicar

O planner ativa `codebase-grounding` por `contracts/gate-registry.json` sempre que `code_touched=true`. Registrar o resultado em `codebase-grounding.json` (`schemas/codebase-grounding.schema.json`).

## Controles

### GROUND-REUSE-001 — buscar antes de criar

Antes de criar arquivo de codigo, funcao/classe/componente publico, endpoint, tabela, chave de configuracao ou dependencia:

1. buscar no repositorio por nome, sinonimos e comportamento (texto, simbolos e consumidores), registrando as consultas realmente executadas e o escopo;
2. listar os candidatos encontrados;
3. decidir `reuse`, `extend` ou `create`. `create` com candidato equivalente exige o motivo objetivo de nao reutilizar cada candidato.

Arquivo de codigo adicionado sem registro de busca bloqueia. Teste e arquivo gerado nao exigem registro.

### GROUND-EXIST-001 — provar antes de usar

Para cada simbolo, API, comando, caminho, chave de configuracao ou dependencia que o codigo ou a documentacao nova passou a referenciar:

- `local`: apontar `path:line` da definicao no head;
- `dependency`: apontar o manifesto ou lockfile versionado que declara o pacote;
- em ambos, registrar o arquivo consumidor e o comando executado (import, typecheck, build ou teste) que exercitou a referencia com `exit_code=0`.

Nao deduzir assinatura, parametro ou versao por analogia. Se a prova nao puder ser obtida, o estado e `UNKNOWN` e bloqueia; nunca substituir por suposicao.

### GROUND-DEAD-001 — nao deixar sobra

Para cada caminho ou simbolo substituido pela entrega, declarar `removed` ou `kept`. `kept` exige consumidor real no head. Dois caminhos para o mesmo comportamento, simbolo novo sem consumidor e codigo antigo mantido "por seguranca" bloqueiam. Complementa `references/hygiene.md`.

## Validacao deterministica

Executar no gate final, sobre o SHA congelado:

```bash
python scripts/validate_codebase_grounding.py \
  --repo <checkout> --report <codebase-grounding.json> \
  --base-sha <work_item_start_sha> --head-sha <material_head_sha>
```

O validador confere contra o Git: SHA exato, registro de busca para todo arquivo de codigo adicionado, existencia dos candidatos citados, presenca do simbolo na linha declarada, presenca da dependencia no manifesto, consumidor que realmente contem o simbolo e disposicao de cada substituicao. Sem checkout executavel o resultado e `UNKNOWN`, nao aprovacao.

## Limite conhecido

O validador prova que o declarado e verdadeiro; nao prova que a lista de referencias esta completa. Completude e refutada pela auditoria independente (`auditar-issue/references/codebase-grounding-audit.md`).
