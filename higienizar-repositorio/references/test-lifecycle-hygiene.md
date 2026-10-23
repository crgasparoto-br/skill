# Diagnóstico sob demanda de testes

O perfil estrutural de higiene possui cinco classes e não mede cobertura, equivalência, efetividade, execução nem obsolescência dos testes. Esta referência complementa `references/global-hygiene-profile.md`, sem alterar `config/hygiene-policy.json` nem criar outro scanner ou estado canônico.

## Procedimento

1. Somente quando solicitado, identificar escopo, comportamento, requisitos atuais, runner e configuração de descoberta, inclusive registro dinâmico ou parametrização. Localizar casos, fixtures, mocks, helpers e uso downstream; se não houver acesso, registrar `UNKNOWN`, jamais ausência.
2. Sinalizar testes permanentemente ignorados, presos a contrato removido, fixtures/mocks ultrapassados ou duplicidade substancial de cenário e oráculo. Sem mesmo risco, nível, isolamento e assertivas discriminantes não existe prova de equivalência. Nome igual, import ausente, análise AST e contagem não bastam; `dead-module.exclude_tests` pode ignorar testes executados dinamicamente.
3. Para cada candidato registrar `keep`, `refactor/consolidate`, `remove-candidate` ou `needs-investigation`, com caminho/caso, requisito/oráculo, consumidores/contrato legado, runner/CI e prova de preservação de controles positivos, negativos, limites, casos históricos, matrizes adversariais e gates.
4. Produzir *findings acionáveis* como work items na forma canônica existente, identificando passos para investigar ou validar e resultados de checks focados/exact-SHA quando executados. Se evidência ou acesso faltar, preservar o teste e registrar o bloqueio.
5. Não excluir automaticamente, não abrir issue dentro da varredura e não usar a ausência de achado estrutural como aprovação de cobertura; a decisão e qualquer operação destrutiva pertencem ao ciclo de entrega, conforme autorizações do projeto.

## Limites explícitos

Testes descobertos dinamicamente, oráculos externos e cenários parametrizados podem ser invisíveis à busca estática; não extrapolar descoberta parcial para a suíte. A auditoria independente deve refutar equivalência e preservação de cobertura, não aceitar a classificação do implementador como prova.
