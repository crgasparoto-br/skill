# Relatorio externo assinado para o Entregar Issue

## Quando ler este arquivo

Consultar ao inicializar, assinar, validar ou transportar um parecer Ed25519, inclusive no modo solo de operador único.

## Índice

- [Quando produzir](#quando-produzir)
- [Modo Ed25519 de operador único — check distinto](#modo-ed25519-de-operador-unico--check-distinto)
- [Preparacao da chave](#preparacao-da-chave)
- [Montar o registro de auditores](#montar-o-registro-de-auditores)
- [Inicializar o relatorio](#inicializar-o-relatorio)
- [Completar](#completar)
- [Metadados de aprendizado por achado](#metadados-de-aprendizado-por-achado)
- [Assinar e validar](#assinar-e-validar)
- [Entrega](#entrega)
- [Pacote neutro obrigatorio](#pacote-neutro-obrigatorio)
- [Escape de aprovacao interna](#escape-de-aprovacao-interna)

## Quando produzir

Para a modalidade independente de terceiro, produzir `external-audit.json` importavel somente quando:

- esta execucao ocorreu em conversa, agente, sessao ou ferramenta realmente separada da implementacao;
- existe identificador de contexto fornecido pela plataforma ou ferramenta, nao inventado pelo auditor;
- head, base e merge preview foram confirmados antes e depois;
- a chave privada Ed25519 pertence a um auditor previamente confiado e nunca esteve acessivel ao contexto de implementacao;
- o registro publico de auditores foi estabelecido antes da PR ou fica fora do repositorio.

Se qualquer condicao faltar, emitir somente pre-auditoria ou relatorio independente nao importavel. Nunca assinar uma autodeclaracao de independencia.

## Modo Ed25519 de operador unico — check distinto

O gate `Verify solo audit attestation (exact SHA)` aceita um contrato assinado diferente, `assurance_mode=single-operator-separate-context`. Esse modo declara honestamente `independent=false` e `same_conversation=false`: contextos de implementação/auditoria separados e custódia da chave podem ser declarados pelo mesmo proprietário, mas não provam identidade humana independente. Nunca usar este modo para satisfazer `Verify independent audit (exact SHA)` nem chamar seu resultado de auditoria de terceiro.

Inicializar explicitamente o relatório v3 com os valores atuais autenticados da PR/issue:

```bash
python <skill>/scripts/init_external_audit_report.py \
  --repository <owner/repo> --issue <issue> --pull-request <pr> \
  --issue-body-sha256 <sha256-do-corpo-atual-da-issue> \
  --assurance-mode single-operator-separate-context \
  --operator-github-id <id-numerico-do-operador> \
  --base-ref <develop|main> --head-sha <head> --base-sha <base-sha> \
  --merge-preview-sha <preview> \
  --orchestration-cycle <ciclo> \
  --implementation-context-id <id-de-implementacao> \
  --audit-context-id <id-real-do-contexto-separado> \
  --context-proof-kind <chatgpt-conversation-id|agent-run-id|tool-attestation> \
  --context-proof-value <id-real-do-contexto-separado> \
  --context-proof-issuer <plataforma-ou-ferramenta> \
  --origin <procedencia-verificavel> --out <external-audit.json>
```

Completar e assinar como no contrato comum. A assinatura cobre `assurance_mode`, `independent=false`, `operator_github_id`, número da PR, issue e hash do corpo da issue, além dos vínculos exact-SHA e do parecer inteiro. O modo solo continua exigindo veredito `approved`, pacote neutro, contextos distintos, listas vazias de findings/recommendations/limitations e chave confiável Ed25519.

O repositório fornece o opt-in, o ID numérico do operador, o `key_id` e o JSON público `SOLVERIT_TRUSTED_AUDITORS_JSON` apenas por GitHub Actions Variables fora da branch candidata. `SOLVERIT_SOLO_AUDIT_ENABLED` deve ser exatamente `true`; o ID deve ser positivo; o key id precisa existir e autorizar o repositório exato por literal válido `owner/repo`, sem wildcard ou escopo malformado. O workflow valida comentário, ID autenticado do autor, permissão atual `write`/`maintain`/`admin`, PR, issue, hash do corpo, base, HEAD, preview vivo/pais ordenados e checks obrigatórios.

Para transportar o relatório, publicar um único comentário público na PR cujo corpo inteiro seja `SOLVERIT_EXTERNAL_AUDIT_JSON:` seguido por uma quebra de linha e o objeto JSON, sem narrativa adicional. Corpo total máximo: 48 KiB; registry máximo: 32 KiB. O parser rejeita chaves JSON duplicadas, constantes não JSON, marcador duplicado, texto adicional, registro wild-card, assinatura desconhecida e inventário incompleto. Não incluir segredo, chave privada, transcrição ou PII desnecessária. Edição/exclusão do comentário revoga o transporte e bloqueia; postar comentário novo somente depois de nova assinatura e revalidação.

Editar Actions Variables não produz automaticamente evento de workflow. A alteração de chave/configuração só será observada na avaliação seguinte; o procedimento explícito de revogação é excluir o comentário ativo para forçar reavaliação antes de qualquer merge. Nunca afirmar que uma mudança silenciosa de variável cancelou um check verde já publicado. O modo M1 permanece candidato até bootstrap confiável, read-back e decisão administrativa M2; não altere rulesets, approval count nem faça merge como parte da geração do relatório.

O GitHub associa Check Runs ao commit, não a uma PR exclusiva. O controlador cria um Check Run novo por run confiável, vincula o `external_id` ao PR/issue/base/HEAD/preview/run ID e não adota runs prévios por metadados; bloqueia também quando duas PRs abertas compartilham o mesmo HEAD. Antes do PATCH de sucesso, repete a coleta de evidências e de autoridades após o GET inicial do Check Run e relê o mesmo objeto imediatamente antes da escrita. Essas leituras REST reduzem, mas não eliminam a janela concorrente e não são uma transação atômica. Isso sozinho não torna o status exigido pela branch protection per-PR. M2 só pode exigir esta via se um required workflow ou mecanismo equivalente vincular a execução confiável a cada PR, com read-back da proteção das bases e ensaios negativos de HEAD compartilhado. Sem essa prova, manter a exigência humana existente e não substituir o gate nativo.

## Preparacao da chave

Executar uma unica vez em ambiente controlado pelo auditor:

```bash
python <skill>/scripts/generate_auditor_keypair.py \
  --private-out <local-seguro>/auditor-private.pem \
  --public-out <local-publico>/auditor-public.pem \
  --password-env AUDITOR_KEY_PASSWORD
```

Entregar somente a chave publica ao responsavel pelo Entregar Issue. Nunca compartilhar, anexar, versionar ou incluir a chave privada no ZIP da skill.

## Montar o registro de auditores

O registro vive fora do repositorio do candidato, entao nenhum teste do repositorio detecta uma entrada malformada: a falha aparece depois, na validacao do parecer, com aparencia de relatorio invalido. Montar a entrada com o utilitario evita essa classe de erro, porque `public_key_sha256` e derivado do proprio `public_key_pem` e nao aceito como valor informado.

```bash
python <skill>/scripts/build_trusted_auditor_entry.py \
  --public-key <local-publico>/auditor-public.pem \
  --key-id <id-da-chave> \
  --name "<nome do auditor>" \
  --repository <owner/repo> \
  --registry \
  --out <local-seguro>/trusted-auditors.json
```

O utilitario recusa arquivo que contenha chave privada, chave que nao seja Ed25519 e saida que o esquema `trusted-auditors.schema.json` rejeite. Custodia, separacao entre produtor e aprovador, rotacao, revogacao e a limitacao de operador unico estao declaradas em `docs/SECURITY.md`.

## Inicializar o relatorio

Usar os valores exatos do handoff:

```bash
python <skill>/scripts/init_external_audit_report.py \
  --repository <owner/repo> --issue <numero> --base-ref <base> \
  --head-sha <head> --base-sha <base-sha> \
  --merge-preview-sha <merge-preview> \
  --orchestration-cycle <ciclo> \
  --implementation-context-id <id-do-handoff> \
  --audit-context-id <id-real-desta-execucao> \
  --context-proof-kind <chatgpt-conversation-id|agent-run-id|tool-attestation> \
  --context-proof-value <id-real-desta-execucao> \
  --context-proof-issuer <plataforma-ou-ferramenta> \
  --origin <procedencia-verificavel> \
  --out <external-audit.json>
```

O arquivo inicial e um rascunho invalido ate ser completado e assinado.

## Completar

Preencher:

- `head_sha_after`, `base_sha_after` e `merge_preview_sha_after`;
- `verdict`;
- para `verdict=rejected`, preservar o `rejection_id` estavel inicializado como `audit-rejection:<report_id>`; para outro verdict, o signer normaliza `rejection_id=null`;
- evidencias com ID, claim, source e `observed_at`;
- achados estruturados;
- limitacoes.

`approved` exige listas vazias de achados e limitacoes. `approved-with-reservations` nao fecha o ciclo no Entregar Issue.

## Metadados de aprendizado por achado

Cada finding material deve incluir `escape_category`, `required_gate`, `literal_case` e `sibling_cases` com pelo menos dois casos.

Mapeamento: `execution-state-gap`→F28, `control-propagation-gap`→F29, `capability-operation-drift`/`adapter-support-drift`→F30, `silent-translation-loss`→F31, `legacy-variant-gap`→F32 e `documentation-claim-drift`→F33. Usar `other` para achados fora dessas famílias.

## Assinar e validar

```bash
python <skill>/scripts/sign_external_audit_report.py \
  <external-audit.json> \
  --private-key <local-seguro>/auditor-private.pem \
  --key-id <id-da-chave> \
  --password-env AUDITOR_KEY_PASSWORD

python <skill>/scripts/validate_external_audit_report.py \
  <external-audit.json> \
  --trusted-auditors <trusted-auditors.json>
```

A assinatura cobre a serializacao canonica de todo o relatorio, exceto o proprio campo `signature`. Qualquer edicao posterior invalida a assinatura.

## Entrega

Entregar:

- relatorio humano detalhado;
- `external-audit.json` assinado;
- hash SHA-256 do arquivo;
- identificador da chave publica;
- indicacao de que a chave privada permaneceu fora do contexto de implementacao.

O bloco textual `AUDIT_HANDOFF` continua util para leitura humana, mas nao substitui o JSON assinado.

## Pacote neutro obrigatorio

O relatorio externo schema 3 deve conter `neutral_packet` com `implementation_conclusions_included=false` e `implementation_narrative_included=false`. O auditor deve rejeitar material contaminado e solicitar um pacote composto apenas por fontes canonicas, identidade, diff, codigo, testes e evidencias brutas.

## Escape de aprovacao interna

Quando `prior_internal_approval.head_sha` for igual ao SHA auditado e houver finding material, marcar `audit_escape=true` em cada finding escapado e preencher `reusable_control_requirement`. O relatorio rejeitado deve ser importado pelo Entregar Issue como causa raiz e melhoria de Skill obrigatorias na primeira ocorrencia.
O `rejection_id` do relatorio rejeitado e a identidade canonica que `entregar-issue` deve copiar para `learning-closure.source_event.rejection_id` e `audit-escape-closure.source_audit.rejection_id`; o produtor nao deve rederivar esse identificador.
