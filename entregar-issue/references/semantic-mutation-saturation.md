# Saturacao semantica antes do handoff

## Quando aplicar
Obrigatorio para detector AST, gate estatico, parser, rastreador de origem, lexicos e suas remediacoes recorrentes. Integra `requirement-attack-matrix.md`, `risk-saturation-gate.md` e `audit-escape-pattern-catalog.md`, sem substituir validadores existentes.

## Implementacao orientada por familias
1. Antes da primeira edicao, importar todos os findings anteriores (nao somente o ultimo parecer), com IDs, SHA, causa raiz, superficies e controles. Marcar cada item `resolved|still-open|regressed|not-applicable` com evidencia e justificativa.
2. Decompor o contrato em invariantes e oraculos independentes: violacao material dentro do escopo do contrato **deve** bloquear; dados inertes, caminhos fora do escopo e aliases sem proveniencia decisoria **nao** devem bloquear.
3. Produzir uma matriz executavel para cada regra com eixos `origin, binding, transformation, control_flow, consumption, boundary`. Selecionar combinacoes pairwise e triplas de alto risco, nao somente exemplos de auditoria.
4. Testes metamorfos: quando origem, identidade e uso decisorio sao preservados, uma transformacao transparente nao pode alterar o veredito; se a proveniencia foi descartada antes do uso, nao atribuir bloqueio ao dado abandonado.
5. Mutation testing: inserir deliberadamente violacoes em entradas isoladas e verificar gate positivo e controles negativos. Se mutante critico sobreviver, nao publicar handoff/nao declarar `READY`. Agrupar variantes por causa raiz e corrigir a generalizacao, nao hardcodar strings dos casos.
6. Registrar teste declarado, efetivamente executado, passou, SHA do codigo e hashes dos arquivos de prova; exigir `fail-closed` quando a execucao da bateria for obrigatoria e ausente.
7. Antes do freeze, varrer **todas** as familias/superficies materiais e auditar as restricoes de falso positivo. Depois do primeiro blocker, continuar a varredura barata, sem teto de findings. Uma familia `not-executed` permanece explicita e impede afirmacao de saturacao.
8. Publicar resumo de cobertura e casos no CI do mesmo SHA. So entao encaminhar a auditoria independente, a qual usara casos nao compartilhados. CI nao substitui independencia.

## Perfis e limites
Em casos de baixo risco, aplicar apenas superficies realmente expostas. Em riscos criticos usar matriz completa, casos herdados, pairwise e mutacoes relevantes. Evitar suites combinatorias quadradas sem ganho de descoberta: executar focados durante edicao, e bateria final antes da CI. Nao alterar codigo de producao apenas para facilitar o detector; nao alterar baseline/dívida para fazer mutantes passarem.

## Exemplo transversal
Em um verificador de autorizacao, se uma lista estatica indevida alimenta uma decisao de acesso, `allowedActions.includes(requestedAction)` e transformacoes transparentes como `allowedActions.slice().includes(requestedAction)` devem ser julgadas de maneira equivalente. Um alias imutavel preserva a proveniencia quando comprovada; uma lista descartada, um valor sombreado e um uso administrativo fora da fronteira auditada servem de controles negativos. Aplicar o mesmo raciocinio a regras de outros dominios, derivando sempre o esperado do contrato vigente.

## Isolamento de estudos de caso
Exemplos historicos e findings com IDs de issues externas sao materiais nao normativos. Utiliza-los como regressao somente quando houver correspondencia explicita de requisito, superficie e risco com o target atual. Nunca transportar tarefas corretivas ou identificadores de um estudo de caso para o fluxo padrao de entrega.
