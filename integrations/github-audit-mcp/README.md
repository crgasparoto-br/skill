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
- Rulesets are paginated up to 10 pages (1,000 entries); a full final page yields `pagination_complete=false`, which prohibits exhaustive conclusions.
- A protected branch may have rulesets while classic protection returns 404.
- On 2026-10-10 the VPS operator reported FastMCP 3.4.8, local `/mcp` HTTP 401, OAuth discovery HTTP 200, valid HTTPS through Caddy, and a successful ChatGPT OAuth-connected functional audit against `training-system`. These observations are operational evidence, **not** an automated security certification.
- Run the offline regressions from the integration directory with `python -m unittest -v test_authorization.py` after installing dependencies. Simulated tokens do not replace a live negative OAuth test with an unapproved GitHub account.
- Before production sign-off, confirm authorized and unauthorized OAuth sessions, service restart behavior, token/credential rotation, outbound requests, and CI. Do not share authorization codes, tokens, client secrets or private keys in audit output.

## Mandatory release verification — live OAuth (not covered by offline CI)

1. Using an explicitly permitted GitHub account, authenticate over the public HTTPS MCP endpoint and confirm tool discovery, a successful `get_branch_rules` call for `develop`, and a successful `get_branch_rules` call for `main`.
2. In a fresh independent browser/session, authenticate using an account **not** in `ALLOWED_GITHUB_USERS`. Verify that no privileged tools are discoverable and all four tool calls are denied, with zero outbound GitHub App installation API calls. Do not mistake a failed OAuth login for an application-layer deny test.
3. Try another repository and an invalid branch in a permitted session. Confirm both fail without a GitHub API request.
4. Restart the MCP container and repeat permitted/denied checks, verify token minting after restart, expiry and credential rotation against actual live provider sessions.
5. Record only redacted timestamps, HTTP statuses, tool names, branch names and verification outcomes. Never save credentials, authorization codes, access tokens, refresh tokens, or response authorization headers.
6. Require an independent reviewer to inspect the exact PR HEAD, matching offline workflow, dependency resolution and recorded live evidence before approval. **Without both a permitted and a denied live session, status must remain NOT VALIDATED.**

Direct dependencies are pinned in `requirements.txt`; all resolved Python 3.12 dependencies and SHA-256 distribution hashes are committed in `requirements.lock.txt`. The Docker image installs with `pip --require-hashes`, and the lock-generation workflow checks drift against the committed lockfile. Record the deployed image digest and verify the resolved dependencies match the audited image. Treat changes to the lockfile or image as requiring revalidation.


## Fail-closed release evidence gate

The repository includes `verify_release_evidence.py`, which validates the **structure** of independently collected, redacted evidence. It does not perform an OAuth login or establish that the submitted evidence is authentic. Never create a fabricated PASS record to satisfy the gate.

After obtaining evidence from **real** permitted and unpermitted GitHub identities, record a JSON document outside the repository with `pr_head` (the exact 40-character HEAD), `image_digest` (`sha256:<64-hex>`), `dependency_lock_sha256` (64-character hex), and a `cases` object. Every case needs `result: "PASS"`, `kind: "LIVE"`, `timestamp_utc` (UTC `YYYY-MM-DDTHH:MM:SSZ`) and a redacted `evidence_reference`. Required case identifiers are defined in `CASES` in the script. The reviewer must independently confirm each underlying observation and the reported hashes.

Run `python integrations/github-audit-mcp/verify_release_evidence.py /secure/path/evidence.json <exact-40-character-PR-HEAD> integrations/github-audit-mcp/requirements.lock.txt sha256:<observed-deployed-image-digest>`. Obtain the final digest independently from the deployed runtime (not from the submitted JSON). The validator compares the actual lockfile SHA-256 and the independently observed image digest against the recorded evidence; it also rejects invalid and future-dated UTC timestamps. Exit code 1 blocks sign-off for missing/invalid entries; exit code 0 **only** means the submitted structure is complete. The CI unit tests use synthetic records and cannot certify production OAuth. Never commit the evidence document, login credentials or access tokens.

The Docker build now requires the committed transitive `requirements.lock.txt` with hashes; check the `Generate MCP dependency lock artifact` workflow and container build on the exact PR HEAD. This only proves repeatability of Python package selection, not a successful live OAuth audit. Independent verification of live negative OAuth, restart, expiration, rotation, image digest and transitive locking is still mandatory before merge. A structurally valid evidence file or green CI does not constitute operational approval.
