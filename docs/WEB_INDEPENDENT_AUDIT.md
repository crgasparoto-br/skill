# Auditoria independente web — issue #127

## Decisão vinculante

Não utilizar API de inteligência artificial para implementação ou auditoria. Não utilizar VPS, runners self-hosted ou infraestrutura privada. O ChatGPT opera por conversas separadas com acesso às ferramentas conectadas do GitHub. GitHub Actions executa somente testes, certificação semântica exact-SHA e validação determinística das evidências.

## Separação de funções

1. **Implementação**: conversa do ChatGPT que implementa e corrige a entrega, sem produzir sua própria aprovação independente.
2. **Certificação**: GitHub Actions coleta resultados técnicos e exige dossiê semântico com vínculo exato a issue, base e HEAD. A falta de entradas permanece bloqueante.
3. **Auditoria**: outra conversa do ChatGPT analisa requisitos, código, controles e testes, em somente leitura, e produz parecer real. Uma conversa separada não é, por si só, prova criptográfica de independência nem equivale a um GitHub review APPROVED.
4. **Verificação**: o verificador determinístico exige relatório assinado por auditor previamente confiado, alvo exato, prova de contexto, assinatura e evidências. Não aceita uma conclusão autoassinada como independência.

## Componentes mantidos

- `scripts/verify_web_external_audit.py`: verificações de relatório Ed25519, repositório, issue, base, SHA material, merge preview e contexto da auditoria.
- `tests/test_verify_web_external_audit.py`: testes de desvio de alvo, contexto, merge preview e evidências de aprovação.
- O validador CLI permanece disponível para execução determinística por política confiável. O workflow manual anterior foi removido porque referenciava o produtor de IA descontinuado e não autenticava a origem de um relatório produzido no ChatGPT.

## Regras contra looping

- Auditoria somente leitura, sem commits, reexecuções de CI ou correção de código.
- Fixar identidade de PR/base/HEAD e invalidar a aprovação somente quando SHA, contrato, risco ou evidência material mudar.
- Agrupar todos os achados demonstrados na mesma rodada.
- Não transformar CI verde em conclusão; não aceitar aprovação interna da implementação como auditoria independente.
- Se a credencial independente ou o relatório assinado faltar, emitir BLOCKED e não reiniciar a auditoria sem mudança material.

## Limitações e implantação

O gate atual `Verify independent audit (exact SHA)` exige uma revisão GitHub APPROVED de outra identidade. Como só existe uma conta humana, **essa proteção não pode ser satisfeita por uma segunda conversa por si só**. A futura substituição do requisito precisa de política e atestação realmente confiáveis. Não desabilitar regras para criar uma aprovação artificial.

O registro `TRUSTED_AUDITORS_JSON` e a assinatura Ed25519 são opcionais para executar testes, mas indispensáveis para aceitar um relatório pela via externa; mantê-los fora da implementação. Não pedir nem cadastrar `OPENAI_AUDITOR_API_KEY`, `OPENAI_AUDITOR_MODEL` ou `OPENAI_AUDITOR_URL`.

A issue #127 permanece aberta até certificação exata, provas de auditoria real, migração segura dos checks e rulesets efetivas em develop/main. Nenhum merge automático.

## Contrato de importação de auditoria em outra conversa

O auditor de uma conversa separada só pode entregar **parecer humano de pré-auditoria** enquanto não houver evidência autenticada do ID da conversa, custódia independente de chave Ed25519 e registro de confiança anterior à PR. O implementador **não pode** assinar esse parecer nem publicar um check aprovado em nome do auditor.

Quando houver uma identidade auditora de fato confiável, o relatório `external-audit.json` deve obedecer ao schema oficial `auditar-issue/schemas/external-audit.schema.json` e incluir fonte da prova de contexto, emissor da prova, contexto de implementação diferente do contexto auditor, base/head/merge-preview exatos e evidência verificável por requisito. O validador `scripts/verify_web_external_audit.py` aceita os parâmetros `--audit-context-id` e `--context-proof-issuer` para confrontar esses campos com valores autenticados fora do relatório. **Esses parâmetros não podem ser copiados cegamente do próprio JSON do candidato.**

Sem essas condições, o resultado formal é BLOCKED. Não há substituição segura de review GitHub obrigatório por um texto fornecido pela mesma conta GitHub. O próximo passo de implantação só poderá ser executado quando houver uma origem de atestação confiável, sem API de IA, aprovada para operador único.
