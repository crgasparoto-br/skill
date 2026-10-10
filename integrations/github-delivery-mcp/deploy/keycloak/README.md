# Isolated Keycloak installation plan (Issue #88)

**Status: staged in Git, NOT deployed.** This compose file deliberately binds the
Keycloak HTTP container to `127.0.0.1:18780`; it is NOT a publicly usable OAuth
authorization server until a separately configured HTTPS reverse proxy and a
real hostname exist.

## Pre-flight before making changes on VPS

1. Select and configure DNS for a **dedicated** authentication hostname. The
   example `auth.example.com` is intentionally invalid for your installation.
2. Confirm that the VPS reverse proxy has an available HTTPS virtual host.
   **Do not replace or restart** existing applications' reverse proxies.
3. Verify the exact image tags, image digests and security updates before running.
   The current file uses explicit version tags but not digest pinning: the
   supply-chain policy must be completed before production.
4. Inspect `docker compose ps`, volumes, available memory, disk and existing
   port assignments; ensure port 18780 is unused.
5. Copy `env.example` to `.env` **outside Git**, generate separate random
   passwords, and restrict file permissions with `chmod 600 .env`.
6. Run `docker compose --env-file .env config --quiet` to validate inputs.
   Never paste `docker compose config` without `--quiet`: it can expose secrets.
7. Only after proxy/TLS and all checks, run `docker compose --env-file .env up -d`
   within this dedicated deployment directory. Do not use `down -v` because it
   destroys the Keycloak database.
8. Confirm a local endpoint `curl -fsS -o /dev/null -w '%{http_code}\n'
   http://127.0.0.1:18780/realms/master/.well-known/openid-configuration`.
   **Do not expose** port 18780 on the firewall.
9. Configure a dedicated realm `solverit-delivery`, its OAuth client and
   redirect URIs based on the actual ChatGPT connector UI (never invented).
   Provision a regular operator user, enforce MFA, and remove the bootstrap
   administrative credentials after administrator recovery is established.
10. Validate OIDC discovery, PKCE S256, refresh tokens and **JWT access-token**
    issuer/audience/scope. The existing verifier accepts only a pinned RS256
    *access-token* public key and does not automatically fetch or rotate JWKS.
    Configure proper resource/audience scope mapping explicitly.
11. Keep write-capable MCP operations disabled until security review and
    end-to-end tests pass. Existing PR #89 remains draft.

## Reverse-proxy boundary

Keycloak is configured to recognize `X-Forwarded-*` from the proxy. The proxy
must **overwrite** all client-supplied forwarding headers, enforce strict SNI
and Host, serve HTTPS, and only proxy the intended login endpoints. Restrict
Keycloak administrator APIs and console to an administrative network where
possible. Never expose `/health` or `/metrics` publicly.

Do not change existing Nginx/Caddy/Traefik config unless its actual live
configuration has been inspected and backup/revert verified. No reverse proxy
configuration is included because the VPS' active proxy implementation and
domain ownership are unverified.

## Secret management

The compose file uses `.env` interpolation: this keeps secrets **out of Git**,
but Docker container metadata can still contain environment values. Only
trusted administrators may access Docker daemon and deployment directory.
For production hardening, migrate to a supported file/vault mechanism with
Keycloak configuration before inviting external users.

## Rollback

Stopping this specific stack uses `docker compose --env-file .env stop`.
Never use global prune/restart commands, never remove the named database volume,
and never close the current SSH terminal.

References: https://www.keycloak.org/server/containers
https://www.keycloak.org/server/configuration-production
https://www.keycloak.org/server/reverseproxy
