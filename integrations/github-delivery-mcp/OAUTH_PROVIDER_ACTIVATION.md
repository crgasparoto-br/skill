# Issue #88 — OAuth authorization-server activation contract

Status: **NOT CONFIGURED**. This document prepares a real OAuth authority; it does
not claim that a real login or HTTPS endpoint is deployed.

## Separation of trust

- The ChatGPT MCP client authorizes with an independent OAuth authorization server (AS).
- The MCP service is only the protected resource. The AS is **not** GitHub OAuth.
- The AS issues access tokens for the **exact** HTTPS MCP resource URL, with the
  `solverit:read` scope, and subject allowlisting on the MCP server.
- The GitHub App private key and installation tokens stay with the separate privileged
  token broker. Neither is an MCP client credential.
- Keep `127.0.0.1:8769` loopback only. Do not expose it until end-to-end auth,
  proxy trust, SDK transport compatibility and rate-limits have passed.

## Required operator choices

1. Decide public HTTPS hostnames for the MCP resource and the AS, and control their DNS.
2. Select a supported AS with authorization code + PKCE S256, refresh tokens,
   discoverable `issuer`, `authorization_endpoint`, `token_endpoint`, and `jwks_uri`.
3. Register the ChatGPT OAuth client through client ID metadata, preregistration
   or supported dynamic registration. Confirm the actual ChatGPT redirect URI during
   the client-configuration workflow; never guess or blindly allow redirect URIs.
4. Configure audience/resource indicator to match exactly the MCP HTTPS URL.
5. Provision public TLS and a hardened reverse proxy with limited request sizes,
   connection and request timeouts, IP-aware rate limits and Host enforcement.
6. Provision/read only the AS **public verification key** in the MCP worker process
   and configure `SOLVERIT_MCP_JWT_PUBLIC_KEY_FILE`, `SOLVERIT_MCP_JWT_KEY_ID`,
   `SOLVERIT_MCP_SUBJECTS`, `SOLVERIT_MCP_RESOURCE_URL`,
   `SOLVERIT_OAUTH_ISSUER_URL`. Never copy an AS signing private key here.
7. Validate the entire authorization-code + PKCE + refresh flow, token issuer,
   audience, subject and scope with ChatGPT. Test revocation/rotation and failure cases.

## Static preflight (no service deployment or real login)

Save the AS's public OAuth 2.0 / OIDC discovery JSON to a **temporary local file**
on an operator machine and run:

```sh
python3 integrations/github-delivery-mcp/oauth_provider_preflight.py \
  --issuer https://auth.example.org/realms/solverit \
  --metadata-json /tmp/solverit-as-discovery.json
```

For an AS with an explicitly pre-registered client and no registration endpoint,
add `--pre-registered-client` only after completing preregistration.

A passing static check is **not proof** that the provider issues suitable RS256
resource-bound access tokens, supports refresh in practice, performs client
registration safely, or interoperates with ChatGPT. Those are live validation gates.

## Verification state and deployment gate

The pilot supports either a **pinned RS256 public key** or a **trusted HTTPS JWKS**
(`SOLVERIT_OAUTH_JWKS_URI`), never both. Its JWKS verifier caches only issuer-relative
RS256 RSA verification keys, rejects unknown key IDs, and refreshes on bounded TTL.
This is source-level functionality, **not** evidence of a configured Keycloak realm,
a deployed service, working token rotation, or ChatGPT interoperability.

Before public activation, validate real Keycloak access tokens for `iss`, exact
`aud`, `sub`, `scope=solverit:read`, `iat`, `nbf`, `exp`, `alg=RS256` and a known
`kid`; reject absent/incorrect claims, untrusted users, and unsigned tokens.
Exercise key rotation across cache expiry, issuer outage, and revocation policy
without relaxing verification. Verify the deployed image digest and commit HEAD.
The pilot currently exposes **no write tools**; passing OAuth checks must not
be interpreted as authorization to start the issue executor.

No public listener, production credentials, GitHub writes, or deployed AS are
authorized by this document.
