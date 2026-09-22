# Ownership de CI

A fonte canonica machine-readable e `contracts/ci-ownership.json`. `corrigir-ci` usa exclusivamente `ci-remediation-loop`; `entregar-issue` usa `delivery-snapshot`. Os modos sao mutuamente exclusivos por material SHA.

Em entrega governada, commit material posterior ao freeze exige `finalize-after-ci` no controlador `entregar-issue` antes de liberacao para auditoria. `corrigir-ci` encerra em `green-material` e devolve o envelope; nao executa a recertificacao.
