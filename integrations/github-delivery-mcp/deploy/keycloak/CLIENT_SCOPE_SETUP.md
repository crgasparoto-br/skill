# Keycloak 26.4.2: ChatGPT OAuth client scope and audience (Issue #88)

State: operator procedure, NOT applied automatically. Realm: `solverit-delivery`.

## Exact identity

- Issuer: `https://auth.solveritconsultoria.com.br/realms/solverit-delivery`
- Protected resource/audience: `https://mcp.solveritconsultoria.com.br/mcp`
- OAuth public client: `solverit-chatgpt-mcp`
- Exact redirect URI (as supplied by operator): `https://chatgpt.com/connector/oauth/R8eXT2XoMcRK`
- Read scope: `solverit:read` (do not grant write yet).

## Setup

1. Realm `solverit-delivery` > Client scopes > Create client scope:
   name `solverit:read`, protocol `OpenID Connect`, type `Optional`.
   Keep scopes optional to prevent automatically granting read to every OAuth
   token and avoid forcing that permission without client request.
2. Open the new scope > Mappers > Configure a new mapper > Audience.
   Name `solverit-mcp-audience`; Included Custom Audience:
   `https://mcp.solveritconsultoria.com.br/mcp`; Add to access token ON,
   Add to ID token OFF, as supported by this Keycloak version.
3. Clients > `solverit-chatgpt-mcp` > Client scopes > Add client scope:
   `solverit:read` as **Optional**.
4. Client > Settings: public client, Standard flow ON, PKCE method S256,
   Direct Access Grants OFF, Implicit OFF, service accounts OFF; valid
   redirect URI must match the ChatGPT callback exactly (no wildcards).
5. Test user authorization with explicit `scope=openid solverit:read`.
   Inspect access token claims (not ID token): `iss`, `aud`, `sub`,
   `scope`, signature algorithm RS256, expiration. Ensure the requested
   scope is actually permitted for the operator, not merely present
   because a client scope was assigned. **Client-scope availability is
   not per-user authorization.** Add dedicated mapper/policy or a
   server-side subject allowlist and verify both before service exposure.
6. Never enable GitHub write tools based only on these Keycloak settings.

## Caution

Keycloak's optional client scopes are included when requested via the OAuth
scope parameter. The MCP server must still check `scope` and exact resource
audience. If ChatGPT cannot request `solverit:read`, stop and investigate
capability negotiation; do not silently make privileged scopes default.

Access-token JWKS rotation is not implemented in the current MCP verifier;
the single pinned public key must be reconciled before public production.

Use only public discovery/JWKS material for validation; never paste secrets
or access tokens into GitHub, tickets, chats, or logs.
