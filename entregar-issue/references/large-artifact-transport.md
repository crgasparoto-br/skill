# Transporte de artefatos grandes

## Objetivo

Transportar artefatos JSON de handoff sem transformar serializacao em caminho critico. Reduzir duplicacao semantica primeiro; somente depois adaptar o transporte, preservando a evidencia exigida pelo perfil.

## Formatos aceitos

Todo consumidor deve aceitar transparentemente:

1. `plain-json`: o arquivo contém diretamente o JSON lógico;
2. `base64-shards-v1`: o caminho canônico contém um manifesto pequeno e o conteúdo lógico fica em partes relativas, comprimidas com gzip determinístico e codificadas em base64.

O formato físico nunca muda a semântica do artefato.

## Orcamento e threshold

Antes de shardear, calcular o custo previsto. Se o pacote exigir mais de 10 blobs/partes somente para transportar evidencia, **nao** iniciar a publicacao: compactar semanticamente o artefato (reutilizar controles/evidencias, usar `standard-evidence.json` quando o perfil permitir) e validar de novo.

Preferir JSON textual nativo do connector. Usar `base64-shards-v1` somente quando o payload nativo falhar por limite objetivo ou quando o artefato lógico exceder 128 KiB e nao houver representacao compacta suportada. Quando necessario, usar shard de 8 KiB de base64 por padrao; reduzir apenas apos falha observada do connector.

Executar:

```bash
python scripts/pack_large_audit_artifact.py .audit/entregar-issue/requirement-closure.json
python scripts/pack_large_audit_artifact.py .audit/entregar-issue/requirement-attack-matrix.json
```

Artefato abaixo do threshold permanece `plain-json`. O empacotamento é determinístico e idempotente.

## Manifesto

`base64-shards-v1` deve registrar pelo menos:

- `schema_version`;
- `artifact_format=base64-shards-v1`;
- `artifact_kind`;
- `compression=gzip`;
- `encoded_size`;
- `decoded_size`;
- `decoded_sha256`;
- `parts[].path|size|sha256`.

Novos produtores também registram `encoded_sha256`. Consumidores devem aceitar manifests anteriores sem esse campo e validá-lo quando presente.

## Validação obrigatória

Usar `scripts/audit_artifact_io.py` como única implementação de leitura. Antes de devolver o JSON lógico, o loader deve:

1. impedir paths absolutos, `..`, duplicidade e escape do diretório do manifesto;
2. exigir cada parte existente e com `size` e SHA-256 exatos;
3. validar `encoded_size` e, quando presente, `encoded_sha256`;
4. decodificar base64 em modo estrito;
5. descomprimir gzip com limite de saída;
6. validar `decoded_size` e `decoded_sha256`;
7. decodificar UTF-8 e somente então fazer `json.loads`.

Falha em qualquer etapa é bloqueante. Nunca fazer fallback para interpretar partes incompletas ou para confiar apenas no manifesto.

## Certificado e allowlist

`build_handoff_certificate.py` deve:

- certificar o SHA-256 físico do manifesto/JSON;
- certificar também `logical_sha256` e `logical_size`;
- registrar metadados de transporte por artefato;
- incluir automaticamente na `certificate_commit_policy.allowed_paths` o manifesto e **todas** as partes declaradas.

O `result-only-child` pode alterar apenas paths allowlisted. Parte ausente, extra ou alterada invalida o certificado.

## Publicação connector-only

Para GitHub connector-only:

1. tentar primeiro publicar cada artefato como JSON textual quando estiver dentro do limite pratico observado;
2. empacotar somente o artefato que exceder/falhar no transporte nativo;
3. criar um blob por manifesto/parte pequena;
4. conferir o SHA Git retornado de cada blob quando houver SHA esperado local;
5. construir uma única tree contendo todos os paths do pacote;
6. criar um único `result-only-child` filho direto do material head;
7. mover a branch sem force;
8. reconsultar o head e executar o terminal handoff guard.

Nunca concatenar manualmente JSON/base64 grande em uma chamada quando o sharding estiver disponível.

## Regra anti-degradação

É proibido reduzir evidência, remover controles, omitir requisitos, simplificar matriz ou alterar conteúdo lógico apenas para caber no conector. Se o artefato grande não puder ser transportado, corrigir a camada de transporte, não o contrato de auditoria.
