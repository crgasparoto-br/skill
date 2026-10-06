# Perfis de execucao

## Regra central

Usar `standard` por padrao. O perfil define o custo de evidencia do handoff, nao a severidade do requisito nem a profundidade da implementacao. Promover para `critical` somente quando o risco exigir prova adversarial completa.

## Light

Usar apenas para documentacao/assets isolados ou alteracao sem comportamento runtime material. Exigir contrato, closure, verificacao documental/visual aplicavel, identidade, CI observavel e handoff. Nao exigir `standard-evidence`, matriz ou saturacao.

## Standard

Usar para funcionalidade comum, UI, configuracao comportamental, persistencia ordinaria e integracoes reversiveis sem risco critico. Produzir `standard-evidence.json` exact-material-head com, por requirement ID, evidencia positiva, um controle negativo primario e regressao; inicializar com `python <skill>/scripts/init_standard_evidence.py --requirement-closure <requirement-closure.json> --head-sha <material-head> --out <standard-evidence.json>`. Nao produzir `requirement-attack-matrix.json`/`risk-saturation.json` apenas por existir mais de uma camada ou muitos criterios de aceite.

## Critical

Promover quando houver pelo menos um destes sinais objetivos:

- autorizacao/privacidade/isolamento multi-tenant material;
- migracao/backfill destrutivo ou compatibilidade de dados de alto impacto;
- concorrencia/atomicidade com risco de dupla gravacao, perda ou corrupcao;
- parser/decoder de entrada nao confiavel em fronteira publica;
- segredo/credencial, policy de runtime ou cancelamento que altere seguranca/isolamento;
- provider com efeito financeiro/irreversivel ou retry/fallback/idempotencia que possa duplicar efeito externo;
- remediacao `systemic-remediation` de rejeicao independente.

Provider, callback, retry, fallback ou continuidade **nao promovem sozinhos** quando o efeito e reversivel, sem dinheiro, sem isolamento e sem estado critico; nesses casos permanecer `standard` e exercitar os controles focados correspondentes.

No perfil `critical`, aplicar os portoes F20 a F27 de [critical-closure-gates.md](critical-closure-gates.md) cujos sinais estiverem presentes.

## Rejeicao independente anterior

`targeted-remediation` nao promove automaticamente para `critical`; exigir ledger de remediacao e evidencia do requisito afetado no perfil corrente. `systemic-remediation|mixed-remediation` exige `critical`, closure de escape, learning closure e controles herdados.

## Classificacao de mudanca

- config/schema sem codigo elegivel: preservar gates comportamentais, marcar higiene `not-applicable`;
- teste/gerado apenas: nao executar higiene por padrao;
- assets visiveis: ativar interface quando houver efeito percebido;
- finding novo nos mesmos caminhos: reabrir implementacao pelo `work_item_fingerprint`.

O perfil pode subir quando surgir risco novo. Reducao exige justificativa estruturada e nunca remove gate funcional aplicavel.
