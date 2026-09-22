# Consumo de artefatos grandes

## Regra

Artefato de entrega pode estar em JSON direto ou em `base64-shards-v1`. Tratar ambos como duas representações físicas do mesmo JSON lógico.

Usar sempre `scripts/audit_artifact_io.py` para ler artefatos certificados. Não implementar decodificação paralela em cada gate.

## Verificação fail-closed

Para `base64-shards-v1`, exigir antes da auditoria ampla:

- manifesto válido;
- paths relativos sem traversal;
- todas as partes presentes;
- `size` e SHA-256 de cada parte;
- `encoded_size` e `encoded_sha256` quando declarado;
- base64 estrito;
- gzip dentro do limite de descompressão;
- `decoded_size` e `decoded_sha256`;
- JSON lógico válido.

O certificado deve bater no hash físico e no `logical_sha256` quando este estiver presente. A reconstrução não é evidência do produtor: é somente transporte verificado para permitir que o auditor rederive os controles normalmente.

## Connector-only

Quando o auditor materializar o pacote via conector, buscar o manifesto e todas as partes listadas no certificado/manifesto no mesmo commit imutável. Se uma parte não puder ser obtida integralmente, usar o fallback connector-native somente quando ele satisfizer os contratos semânticos já definidos; caso contrário a limitação permanece de runtime, nunca deve ser preenchida por inferência.

## Somente leitura

`auditar-issue` não empacota, não corrige e não publica artefatos. O suporte a shards no auditor é exclusivamente leitura, reconstrução e validação.
