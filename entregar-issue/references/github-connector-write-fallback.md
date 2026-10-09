# Implementacao via conector GitHub quando checkout local falhar

## Gatilho

Aplicar quando `git clone/fetch`, DNS, proxy, token de checkout ou indisponibilidade do ambiente local bloquear o acesso ao repositorio, **mas o conector GitHub permitir leitura e escrita no alvo**. Falha do clone, isoladamente, nao e impedimento terminal nem autoriza encerrar a entrega apenas com diagnostico. Nao repetir tentativas de clone sem fato novo.

## Sequencia obrigatoria

1. Resolver issue/PR/branch/base e HEAD por leitura remota fresca. Conferir permissoes de leitura e escrita, conflitos da PR e instrucoes do repositorio. Manter a PR/branch original sempre que possivel; nunca escrever por engano na branch default.
2. Usar `fetch_file` por path e ref da branch para obter conteudo integral e `sha` do blob. Para arquivos ainda inexistentes, confirmar ausencia antes de `create_file`. Buscar arquivos correlatos por busca de codigo e ler os trechos integrais necessarios antes de editar.
3. Preparar o patch minimo em memoria ou workspace efemero. Preservar integralmente bytes/semantica fora do recorte; nao substituir arquivo grande por trechos incompletos. Comparar diff antes da publicacao. Se a ferramenta so permitir substituicao integral, partir sempre do conteudo integral recem-lido.
4. Para arquivo existente, usar `update_file` com o `sha` atual e `branch` explicita. Para arquivo novo, usar `create_file` na branch explicita. Para alteracoes multi-arquivo que devam ser atomicas, quando disponivel, criar blobs/tree/commit e atualizar ref com `expected_sha` (CAS), sem force; caso contrario, sequenciar commits pequenos e verificar cada um. Nao usar force-push nem deletar arquivos.
5. Em conflito de blob/ref, nao sobrescrever: reler HEAD/arquivo, reconciliar o delta e revalidar o patch. Observar continuamente o `work_item_start_sha` original, e registrar novos commits materiais.
6. Apos cada escrita, reler os paths modificados e o HEAD remoto e provar que o conteudo esperado foi publicado na PR correta. Atualizar a identidade do candidato material e invalidar evidencias/certificados herdados afetados.
7. Executar checks focados onde houver runner local utilizavel. Se a dependencia necessaria (por exemplo, Prettier) nao puder rodar localmente, **nao declarar o arquivo formatado por inspecao manual**: publicar apenas patch fundamentado, consumir diagnostico do check canonico no SHA exato, corrigir iterativamente via conector; delegar observacao/remediacao de CI a `corrigir-ci` segundo o contrato de ownership. Nunca mudar CI, gates, secrets ou required checks para encobrir falha. Nunca inventar logs/capturas/evidencias.
8. Para evidencias Chrome autenticadas, comparar artefatos exact-SHA de desktop/mobile, estados e modais, com controles negativos discriminantes. Se o conector nao expuser os artefatos ou nao permitir validacao obrigatoria, registrar exatamente qual gate nao foi possivel, manter o requisito aberto e nao emitir READY.
9. Seguir normalmente freeze, post-write-refreeze, handoff certificado ou auditoria nativa conforme o transporte escolhido; nenhuma mudanca material posterior pode reutilizar certificado anterior.

## Classificacao de impedimento

- `checkout-unavailable + connector-write-available` = **fallback executavel**, nao bloqueio terminal.
- `connector-read-only` = buscar outro canal de escrita autorizado; sem ele, explicar a operacao impedida.
- `validation-runtime-unavailable` = nao afirmar gate local verde; usar CI exact-SHA quando adequado e preservar checks visuais independentes.
- `head-conflict` = reconciliar antes de nova escrita; nao sobrepor alteracoes concorrentes.
- `artifact-inaccessible` = evidencias dependentes do artefato permanecem abertas; nao aprovar visual por CI verde.

## Controle negativo do proprio processo

Simular mentalmente uma edicao errada que passa por leitura remota mas sobrescreve alteracao de terceiro. Exigir SHA do blob e HEAD fresco, erro de concorrencia tratado por releitura, diff minimo, branch explicita e verificacao pos-escrita. Simular falha de Prettier ou visual validation: o processo deve manter estado bloqueado/remediacao, nunca declarar entrega concluida a partir do commit publicado.

## Relatorio

Registrar na PR paths editados, SHA anterior e posterior, estrategia de escrita (Contents API ou tree/commit/ref), checks executados/nao executados, resultados exact-SHA e pendencias reais. Nao tratar uso de connector como excecao aos contratos de dominio, testes, seguranca ou handoff.
