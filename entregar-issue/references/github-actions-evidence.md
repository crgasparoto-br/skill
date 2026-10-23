# Coleta de evidencias de handoff no GitHub Actions

## Objetivo

Eliminar a dependencia da VPS para capturar inputs de readiness em PRs contra `develop`.
O workflow `.github/workflows/handoff-evidence.yml` usa `ubuntu-latest`, token
somente de leitura e checkout do SHA material da PR (nao do merge-preview).

## Contrato de producao

1. No evento `pull_request`, exigir repositorio, PR, base `develop` e um unico
   identificador explicito `Issue #N` (ou `Fixes/Closes/Resolves #N`).
2. Usar a API GitHub autenticada somente para ler o corpo integral da issue.
3. Executar `build_specification_snapshot.py` e `init_requirement_closure.py`
   existentes, sem marcar como passed entradas geradas como pending.
4. Executar a suite de testes no SHA material e guardar log, JUnit, codigo de
   saida e hash SHA-256 do log. Nao declarar equivalencia semantica por nome.
5. Publicar o conjunto em um artifact GitHub Actions com nome que inclua PR e
   SHA. O arquivo `handoff-preflight.json` permanece `status=blocked` ate haver
   evidencia discriminante, validacoes e certificado autenticos.
6. `entregar-issue` deve consumir esses bytes pelo mesmo SHA, mapear requisitos
   e controles, produzir `codebase-grounding`, `code-growth` e evidencia do perfil,
   reconciliar auditorias anteriores e executar os validadores oficiais.
7. Somente apos `READY` construir, simular e publicar `result-only-child`
   atomico, seguindo `terminal-handoff.md`. Um artifact do Actions sozinho nao
   substitui o certificado versionado nem a auditoria independente.

## Seguranca e limites

- Nao usar self-hosted, VPS, `workflow_dispatch`, `pull_request_target`,
  token de escrita, secrets de negocio, workflows privilegiados ou merge.
- Nao executar codigo de fork com credenciais: forks falham no preflight.
- Falta de referencia de issue, acesso API, runner, log ou controle deve falhar
  explicitamente: `UNKNOWN/blocked`, nunca status de aprovacao.
- O workflow e coletor de fatos, nao o produtor do veredito. CI verde nao prova
  cobertura de cada requisito nem fechamento de achados independentes.
- O pacote vai para Actions artifacts efemeros; nao comitar log, token ou
  evidencias incompletas em `.audit/` como se fossem handoff final.
