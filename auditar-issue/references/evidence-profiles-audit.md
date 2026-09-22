# Auditoria por perfil de evidencia

O `handoff-ready.json` declara `evidence_profile=light|standard|critical`. Tratar perfil ausente de certificado legado como `critical`.

- `light`: validar certificado, closure, identidade, controles explicitamente certificados e gates aplicaveis. Nao exigir matriz/saturacao ausentes por design.
- `standard`: exigir `standard-evidence.json` exact-material-head, cobrindo cada requirement ID com evidencia positiva, um controle negativo primario e regressao. Rederivar riscos independentemente durante a auditoria. Flags estruturais/temporais ordinarias nao promovem sozinhas; isolamento, atomicidade ou reference-liveness declarados no closure bloqueiam `standard`, e risco critico adicional rederivado tambem pode promover.
- `critical`: exigir o pacote completo de `requirement-attack-matrix.json`, `risk-saturation.json`, `inherited-controls.json` e demais artefatos especializados.
- rejeicao independente anterior nao exige `critical` por si so; somente item `systemic-remediation` ou risco critico real promove o perfil.

Nao transformar a reducao de artefatos de `light|standard` em finding quando o certificado e a closure forem compativeis com o perfil. Perfil insuficiente para o risco real e finding de readiness.
