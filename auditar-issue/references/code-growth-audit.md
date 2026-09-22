# Auditoria de crescimento de codigo

## Objetivo

Refutar `CODE-GROWTH-001` sem aceitar o relatorio do controlador como conclusao. O relatorio certificado e apenas indice.

## Preflight barato

Quando `handoff-ready.json.controls.code_growth.applicable=true`, exigir artefato certificado `code_growth`, hash valido, `control_id=CODE-GROWTH-001`, `status=passed`, `subject_sha=material_head_sha` e `blocking_files=[]`. Ausencia ou stale e `delivery-not-ready`, antes de provas caras.

## Refutacao independente

Com checkout/base disponiveis, comparar os arquivos executaveis tocados contra o baseline e a politica do repositorio. Procurar especialmente: arquivo novo acima do hard limit, arquivo legado grande com crescimento material, responsabilidade nova concentrada no mesmo modulo e exclusao indevida como generated/vendor/test. Pequena correcao em legado grande nao deve virar finding so pelo tamanho historico.

Se a evidencia certificada disser `passed` mas a recomputacao independente encontrar bloqueio, emitir finding estrutural e tratar como `audit_escape` quando o mesmo SHA havia sido aprovado internamente.
