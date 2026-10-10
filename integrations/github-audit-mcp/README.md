# SolverIT GitHub Audit MCP (read-only)

Proof-of-infrastructure integration; not an independent auditor or approval engine. The integration **does not** merge, alter rulesets or issue verdicts. It exposes raw observations for the independent auditor.

## Auth boundaries

1. ChatGPT authenticates to the MCP using the built-in FastMCP GitHub OAuth provider. Set `MCP_OAUTH_CLIENT_ID` and `MCP_OAUTH_CLIENT_SECRET` from a **separate GitHub OAuth App**, not the numeric GitHub App ID or an installation token. Configure its callback URL according to the FastMCP GitHubProvider discovery/callback metadata for the deployed version.
2. The server independently authenticates its GitHub API requests with GitHub App ID **5257238** and the PEM private key, obtaining scoped short-lived installation tokens automatically via `GET /repos/{owner}/{repo}/installation`. You do not need to find the Installation ID manually.
3. Keep PEM and OAuth secret outside the git checkout and Docker image. Protect the environment file with permissions 0600. Never send secrets in chat.
4. GitHub's API may omit `bypass_actors` for read-only identities. The server returns `UNKNOWN_NO_WRITE_ACCESS`, not an empty list. Do not claim independent bypass verification if this field is absent.

## Deployment on an Ubuntu VPS

Prerequisites: Python 3.12 or Docker, reverse proxy with trusted HTTPS certificate, DNS pointing to the VPS and outbound access to `api.github.com`. Follow an existing VPS deployment convention; avoid opening port 8765 publicly.

- Generate/download a GitHub App private key under `/run/secrets/solverit-audit-app.pem`, readable by the service user only. The Docker image runs as UID 65532; mount a read-only key with appropriate ownership.
- Create a dedicated **GitHub OAuth App** for interactive ChatGPT authorization; store client ID and secret in the environment, not the repository.
- Populate the environment variables from `.env.example` through your container orchestration/secret store. The deployed URL was verified on 2026-10-10 with Caddy and Let's Encrypt; verify the active deployment independently before reuse.
- Build: `docker build -t solverit-github-audit-mcp integrations/github-audit-mcp`.
- Run behind a TLS reverse proxy forwarding to `127.0.0.1:8765` on the host; use an appropriate network mapping and secret mount, not `--network host`.
- Set the reverse proxy's URL base to `https://audit-mcp.solveritconsultoria.com.br` and forward OAuth discovery endpoints as well as `/mcp`. Verify public HTTPS and the unauthenticated discovery metadata before attempting the ChatGPT connection.
- In ChatGPT custom MCP server, name `SolverIT GitHub Auditor`, select URL and OAuth, and use `https://audit-mcp.solveritconsultoria.com.br/mcp` only after successful deployment.
- Validate using tools against both `develop` and `main`; compare required contexts including exact `Validate repository`, ruleset source, enforcement, and any bypass visibility. Missing controls => UNKNOWN; do not approve issue #499 without adequate evidence.

## Safety boundaries

- Only repositories in `ALLOWED_REPOS` are accessible, and only `main`/`develop` for branch-specific tools.
- Only GitHub GET requests are exposed to MCP; POST is used server-side exclusively to mint temporary installation access tokens.
- No GitHub tokens, private keys or write operations appear in MCP results.
- For more than 100 rulesets the response sets `pagination_complete=false`; do not treat the result as exhaustive.
- A protected branch may have rulesets while classic protection returns 404.
- On 2026-10-10 the VPS operator reported FastMCP 3.4.8, local `/mcp` HTTP 401, OAuth discovery HTTP 200, valid HTTPS through Caddy, and a successful ChatGPT OAuth-connected functional audit against `training-system`. These observations are operational evidence, **not** an automated security certification.
- Run the offline regressions from the integration directory with `python -m unittest -v test_authorization.py` after installing dependencies. Simulated tokens do not replace a live negative OAuth test with an unapproved GitHub account.
- Before production sign-off, confirm authorized and unauthorized OAuth sessions, service restart behavior, token/credential rotation, outbound requests, and CI. Do not share authorization codes, tokens, client secrets or private keys in audit output.
