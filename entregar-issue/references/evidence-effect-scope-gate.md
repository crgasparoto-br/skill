# Gate de coerencia evidencia -> efeito

## Objetivo

Impedir que uma evidencia, revisao, aprovacao, policy snapshot ou decisao valida autorize um efeito mais amplo do que o escopo realmente sustentado por essa fonte.

## Quando ativar

Ativar quando o contrato contiver semantica equivalente a:

- efeito, operacao, recurso ou mutacao deve estar relacionado a evidencia;
- somente operacoes afetadas, revisadas, aprovadas ou autorizadas podem sofrer efeito;
- uma decisao persistida define quais acoes futuras podem ocorrer;
- branch emergencial, override, excecao, bypass ou fallback pode produzir o mesmo tipo de efeito com um fluxo de validacao diferente.

Classificar no minimo `authorization:evidence-effect-scope`. Quando a evidencia ou aprovacao for persistida em T1 e consumida em T3, ativar tambem `reference-liveness`.

## Invariante

No ponto definitivo do efeito, derivar o conjunto autorizado da evidencia/revisao/aprovacao canonica e provar que todo efeito solicitado pertence a esse conjunto. Presenca de evidencia valida nao substitui a vinculacao entre evidencia e efeito.

Nenhum branch de excecao pode ampliar silenciosamente o escopo. Emergencia pode alterar pre-condicoes ou prazo somente quando o contrato permitir; nao pode remover a relacao evidencia -> efeito sem regra canonica explicita.

## Controle obrigatorio

Usar `AUTH-EFFECT-SCOPE-001` como controle reutilizavel primario para a superficie `evidence-effect-scope`.

O controle deve usar valores deliberadamente divergentes:

1. fonte/evidencia autoriza `effect_a` e a requisicao pede `effect_a` -> aceitar;
2. a mesma fonte/evidencia autoriza `effect_a` e a requisicao pede `effect_b` -> rejeitar antes de qualquer mutacao/efeito;
3. pedido misto `effect_a + effect_b` -> seguir a atomicidade definida pelo contrato e provar que `effect_b` nunca e aplicado;
4. quando houver branch emergencial/override/excecao, repetir a divergencia nesse branch e provar que o escopo continua preservado;
5. quando a fonte for persistida entre etapas, alterar/revogar o escopo antes do efeito definitivo e revalidar conforme `reference-liveness`.

Registrar `procedure`, `expected`, `observed`, `head_sha`, evidencia hasheada e ao menos dois casos irmaos com dimensoes distintas. Um teste que apenas prova `evidence exists`, `security confirmed`, `review approved` ou equivalente nao fecha esta superficie.

## Falha plausivel a atacar

Uma implementacao pode validar que existe uma evidencia/aprovacao legitima, validar que o efeito solicitado e genericamente permitido e ainda assim deixar de provar que aquele efeito especifico foi autorizado pela evidencia. O caminho feliz passa quando os valores coincidem; somente um fixture divergente revela a perda de escopo.

## Fronteiras

Aplicar a checagem o mais perto possivel da mutacao definitiva. Se houver validacao em service e persistencia concorrente/transacional, preservar o mesmo invariante no ponto de commit quando o escopo puder mudar entre preflight e efeito.

Na rejeicao, provar ausencia de efeito observavel: nenhuma linha, evento, timestamp, chamada outbound, estado parcial ou efeito secundario correspondente ao item nao autorizado.
