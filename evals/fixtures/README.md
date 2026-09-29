# Fixtures

Os resultados em `results/` são fixtures determinísticos usados para validar o próprio runner e reproduzir o baseline comportamental versionado. O manifesto [`manifest.json`](./manifest.json) fixa a proveniência e o SHA-256 de cada resultado. Eles não são resultados de um modelo real e não constituem aprovação comportamental da IA.

O smoke case `V030-001-runner-contract-001` cobre o contrato do harness. Os casos `V030-002-*` cobrem seleção, autoridade, capacidades, evidências, contexto insuficiente, leitura progressiva, read-only e incompatibilidade de contrato. Um runtime real deve substituir esses fixtures por resultados observados e declarar provider, modelo, métricas e confiança apropriados; indisponibilidade nunca é convertida em `PASS`.
