# Protocolo de melhoria de Skills

## Quando alterar

Alterar Skill quando evidencia mostrar que instrucoes, contratos, schemas, scripts ou exemplos omitiram gate, permitiram conclusao prematura, exigiram novo prompt sem necessidade, confundiram garantia com continuidade, repetiram defeito sistemico ou produziram composicao insuficiente.

Nao alterar Skill para mascarar bug pontual, reduzir gate ou justificar comportamento incorreto.

## Procedimento

1. Registrar nome, caminho e SHA-256 da Skill atual.
2. Relacionar o achado a lacuna concreta.
3. Formular regra generalizavel e verificavel.
4. Fazer a menor intervencao coerente.
5. Adicionar teste que falharia antes da mudanca.
6. Validar e empacotar a Skill completa. Para mudanca no ecossistema, executar `bash scripts/run_ecosystem_tests.sh --skills-root <raiz> --report <arquivo>`; o runner isola cada modulo de teste e evita dependencia de ordem.
7. Registrar hash anterior e posterior, arquivos e validacoes.
8. Criar `operational_amendment` com identificador, regra, escopo, justificativa e ciclo de inicio.
9. Aplicar a emenda localmente nos ciclos restantes.
10. Invalidar artefatos dependentes e continuar o loop.

## Autoalteracao e hot reload

Uma Skill carregada nao deve afirmar que foi recarregada durante a mesma invocacao. A versao empacotada vale para futuras invocacoes. No run atual, usar apenas a emenda operacional registrada, sem reinterpretar decisoes anteriores.

## Restricoes

Nunca flexibilizar limite de ciclos, identidade, evidencia, protecao de regressao, autorizacao destrutiva, classificacao honesta do nivel de garantia ou proibicao de aprovacao com achado bloqueante.

## Audit escape targeted versus systemic

Nao tratar `audit_escape` como causa sistemica por definicao. Classificar primeiro a natureza do escape:

- `targeted-remediation`: defeito local, gate deterministico nao reproduzido, evidencia incorreta ou correcao pontual sem sinal de falha generalizavel. Exigir regressao local e fechamento exato do finding; nao exigir alteracao permanente de Skill, casos irmaos ou promocao global apenas por ter escapado da aprovacao interna.
- `systemic-remediation`: regra ausente/ambigua, composicao defeituosa, gate genericamente incapaz de distinguir a classe ou recorrencia transferivel. Exigir mudanca de prevencao e deteccao, teste de contrato, controle reutilizavel e casos de transferencia.

Quando o escape for sistemico, classificar a causa entre `audit-defect`, `skill-defect` e causas contributivas; alterar ao menos uma Skill de prevencao e uma de deteccao quando aplicavel, registrar `role: prevention|detection`, adicionar teste de contrato e vincular o escape ao controle promovido.

## Falha dupla de controle

Finding independente contra SHA aprovado internamente indica uma lacuna de implementacao e uma possivel lacuna de deteccao, mas a promocao sistemica depende da classificacao acima. Para `targeted-remediation`, fortalecer o replay/regressao local suficiente para impedir o mesmo falso fechamento. Para `systemic-remediation`, fortalecer ambos os lados de forma transferivel.
