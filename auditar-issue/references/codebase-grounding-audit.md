# Auditoria de ancoragem no codigo

## Objetivo

Refutar `GROUND-REUSE-001`, `GROUND-EXIST-001` e `GROUND-DEAD-001` sem aceitar `codebase-grounding.json` como conclusao. O relatorio da entrega prova apenas o que declarou; a auditoria procura o que ele omitiu.

## Refutacao independente

Com checkout e base disponiveis, usando buscas proprias sobre o `material_head_sha`:

1. **Duplicidade:** para cada arquivo, simbolo publico, endpoint, tabela ou dependencia adicionada no diff da issue, buscar por comportamento equivalente ja existente com termos diferentes dos registrados pela entrega. Equivalente nao citado como candidato e finding.
2. **Existencia:** extrair do diff imports, chamadas, comandos, caminhos e chaves de configuracao novos e confrontar com definicoes e manifestos do head. Referencia sem definicao, sem dependencia declarada ou ausente do relatorio e finding.
3. **Sobra:** para cada comportamento substituido, procurar o caminho antigo, flags, aliases e documentacao que ainda o descrevam. Codigo sem consumidor ou dois caminhos ativos para o mesmo comportamento e finding.

Quando o gate era aplicavel e o relatorio estiver ausente ou stale para o SHA auditado, tratar como `delivery-not-ready` antes de provas caras. Finding em SHA aprovado internamente e `audit_escape`.

Sem checkout executavel, declarar a verificacao `UNKNOWN`; nao aprovar por inferencia.
