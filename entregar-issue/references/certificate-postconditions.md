# Pos-condicao que consome a propria certificacao

## Quando ler este arquivo

Ler quando uma rejeicao anterior registrar como gate deterministico o verificador
oficial de certificacao e seu replay depender do pacote que o builder ainda precisa
produzir. Esta referencia define `CERTIFICATE-POSTCONDITION-001`.

## Índice

- [Aplicabilidade restrita](#aplicabilidade-restrita)
- [Preparacao sem autoridade terminal](#preparacao-sem-autoridade-terminal)
- [Replay factual do comando original](#replay-factual-do-comando-original)
- [Fechamento sem autorreferencia](#fechamento-sem-autorreferencia)
- [Consumo e falhas](#consumo-e-falhas)

## Aplicabilidade restrita

O replay exato continua obrigatorio. Esta fase resolve a ordem de execucao quando
o input do gate e a propria certificacao; nao dispensa finding, gate, revisao ou
controle semantico. O resultado original, seu hash, `rejection_id`, finding IDs,
modo de remediacao, comando e identidade auditada permanecem imutaveis.

A preparacao somente reconhece o comando do verificador oficial
`require_actions_handoff_certificate.py`. Exigir a fonte do gate no anchor Git
confiavel da auditoria, vinculada a base confiavel, com bytes e hash conferidos.
O anchor deve ser a base observada independentemente ou ancestral comprovado
dela por Git sem replacement objects; ser ancestral apenas do candidato nao basta.
Nao executar script selecionado pelo candidato nem aceitar lista arbitraria de
findings dispensados. Um comando diferente, fonte sem procedencia, outra pendencia
aberta ou estado inconsistente continua bloqueando.

## Preparacao sem autoridade terminal

O builder oficial primeiro valida identidade, cobertura, matriz, saturacao,
grounding, crescimento, enderecos de fontes, historico e aprendizado aplicaveis.
Fixar o SHA de entrada para medir esses fatos nao equivale a declarar freeze
favoravel ou readiness terminal; a identidade permanece constante durante as fases.
Somente o item reconhecido como pos-condicao, seu replay ainda nao executado e o
fechamento dependente podem continuar explicitamente pendentes. Valores de exit
code e hash ausentes permanecem nulos; nao preencher sucesso antecipadamente.

Preservar uma preparacao imutavel com todos os artefatos reais e seus hashes.
Ela tem `phase=preparation`, inventario `prepared_artifacts`, ausencia do mapa
certificador `artifacts` e `certificate_commit_policy.allowed_paths=[]`.
Nao substituir o certificado ou o recibo exportado pelo fluxo normal.

A vista de compatibilidade usada somente pelo replay historico conserva os
campos de identidade e os valores de schema/status que aquele verificador le.
Esses campos descrevem o candidato preparado, sem autoridade de publicacao.
O ledger e o escape continuam abertos, e os recibos mantem
`terminal_ready=false` e `certificate_published=false`. O inventario separado e
a allowlist vazia fazem os validadores completos e publishers anteriores
rejeitarem a vista. Os consumidores atuais tambem rejeitam explicitamente a fase
de preparacao.

## Replay factual do comando original

Executar o mesmo comando e argv do finding, usando os bytes preservados do gate
confiavel e inputs do material SHA atual. Quando o comando contem caminhos
absolutos, remontar esses inputs em um layout novo e controlado; os arquivos
historicos originais nunca sao sobrescritos. Conferir todos os destinos antes
da escrita e bloquear colisao, symlink, fonte alterada ou runtime indisponivel.

O processo recebe ambiente limpo, sem credenciais ou imports controlados pelo
candidato. Um interprete existente deve ser o runtime confiavel; um alias novo
exige prefixo Python inteiramente ausente, sem venv ou configuracao preexistente.
A execucao usa argv direto, sem interpretar o comando como shell.
Preservar saida bruta, exit code real, comando, argv, identidade, anchor/hash da
fonte e hashes dos inputs e da preparacao. Timeout, saida faltante, erro ou hash
divergente mantem o fechamento bloqueado. Um teste sintetico do executor nao
substitui esse replay do finding real no material SHA.

Uma reexecucao semantica independente pode usar caminhos temporarios para
recompor e conferir a prova. Ela deve ser identificada como verificacao da prova,
sem substituir ou ser apresentada como a execucao literal original.

## Fechamento sem autorreferencia

A cadeia e aciclica: evidencias e ledger aberto produzem a preparacao; o replay
consome essa preparacao imutavel; seu recibo fecha o ledger; o builder final
certifica o conjunto fechado. O certificado final nao tenta conter o hash de
uma execucao que dependa dos proprios bytes finais.

Depois do replay realmente aprovado, aplicar uma transformacao deterministica
apenas aos campos de fechamento previstos para o item/escape dependente.
Vincular a saida bruta e o recibo reais. Provar que os outros artefatos, controles,
fontes, identidades e findings continuam iguais aos consumidos na preparacao.
Mudanca nao prevista invalida a prova e exige nova preparacao e execucao.

Executar novamente todos os validadores finais, sem permissao de preparacao.
`validate_audit_remediation.py` continua exigindo ledger `closed`, itens `fixed`,
`closure_kind=deterministic-gate-replay`, comando original e reexecutado iguais,
`subject_sha` atual, `exit_code=0` e hash da evidencia integra. O builder somente
entao emite o certificado final, vinculando preparacao, replay e fechamento.
O sucesso do verificador final posterior nao e reinserido nos artefatos de modo
a recriar a autorreferencia.

## Consumo e falhas

Validacao normal de certificado, publicador, guard terminal, coleta de session
review e auditoria independente recusam preparacao. Retirar o marcador de fase,
renomear a vista, preencher sua allowlist ou apresentar um recibo sem a cadeia
autenticada nao a converte em certificado final.

O publicador valida a prova e a equivalencia entre inputs preparados e finais
antes de escrever. O handoff continua exigindo filho direto de resultados,
allowlist individual, controles historicos, identidade remota fresca e todos
os demais gates. Nenhuma fase cria aprovacao independente ou autoridade de merge.

Se o replay ou qualquer validador final falhar, nao exportar certificado final,
nao registrar `certificate-generated` como resultado normal e nao publicar o
handoff. Preservar os diagnosticos e a preparacao explicitamente nao terminal
para corrigir a causa na mesma rodada.
