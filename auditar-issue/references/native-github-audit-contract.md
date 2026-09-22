# Contrato de auditoria GitHub-native

## Objetivo

Permitir auditoria independente sem `.audit/entregar-issue/handoff-ready.json` somente quando o proprio repositorio possui contrato canonico confiavel que define um gate de auditoria GitHub-native exact-SHA. O modo padrao continua sendo `certified-handoff`.

## Regra de confianca

A excecao nunca pode ser criada pelo candidato que esta sendo auditado. Ler o contrato no **trusted anchor**: para PR, usar o `base_sha` imutavel; para branch/commit sem PR, usar um SHA confiavel da default branch ou outro anchor explicitamente estabelecido fora do candidato.

Nao usar descricao da PR, comentario, issue, memoria de conversa ou uma alteracao do proprio candidato para habilitar a excecao.

## Manifesto deterministico

Materializar um JSON efemero e executar `scripts/classify_audit_transport.py --manifest <arquivo>`. O manifesto deve conter:

```json
{
  "schema_version": 1,
  "repository": "owner/repo",
  "trusted_anchor_sha": "<40-hex>",
  "contract": {
    "path": "docs/...",
    "observed_at_sha": "<mesmo trusted_anchor_sha>",
    "source_sha256": "<sha256 dos bytes canonicos>",
    "source_git_blob_sha": "<opcional: blob SHA Git imutavel>",
    "canonical": true,
    "audit_mode": "native-github",
    "legacy_handoff_policy": "forbidden",
    "github_native_identity": true,
    "exact_sha_evidence": true,
    "independent_review": true,
    "remote_ci_evidence": true
  }
}
```

Basta fornecer uma identidade imutavel da fonte: `source_sha256` dos bytes ou `source_git_blob_sha` observado pelo connector no trusted anchor.

`legacy_handoff_policy` pode ser `forbidden` ou `not-required`. Qualquer campo ausente, contrato observado apenas no candidate SHA ou origem nao canonica mantem `mode=certified-handoff`.

## Evidencia minima em native-github-audit

Sem certificado, congelar e provar diretamente por fonte remota:

- repository, work item/issue e PR quando houver;
- base ref/base SHA e head ref/current head SHA;
- merge preview quando aplicavel;
- changed paths do candidato;
- CI/checks requeridos terminalmente verdes no exact head;
- risco/classificacao e policy/fingerprint quando o repositorio os publica;
- provider/model/worker de implementacao quando aplicavel;
- provider/model/reviewer independente da auditoria quando aplicavel;
- findings previos da mesma lineage quando houver.

O contrato nativo substitui **somente o transporte/handoff legado**. Ele nao reduz cobertura, independencia, risk gates, exact-SHA, fail-closed, blocker harvesting ou revalidacao final de identidade.

## Falhas

- Contrato nativo confiavel ausente ou incompleto: usar `certified-handoff`.
- Contrato existe apenas no candidate SHA: usar `certified-handoff`; o candidato nao pode se autoisentar.
- Repositorio canonico proibe o handoff legado e o classificador retorna `native-github-audit`: ausencia de `.audit/entregar-issue` **nao e finding** e nao e `delivery-not-ready`.
- Falta de evidencia GitHub-native obrigatoria por responsabilidade da entrega/candidato continua bloqueante.
