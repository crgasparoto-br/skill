"""OAuth resource metadata for a future MCP-facing HTTPS deployment.

Do not advertise GitHub API as this MCP resource's OAuth issuer: GitHub's
user-token endpoint alone is not an MCP-compatible authorization server.
The issuer must be a separately configured, standards-compliant authority.
This module does not enable OAuth or network exposure.
"""
from urllib.parse import urlsplit


def resource_metadata(*, resource_url: str, issuer_url: str) -> dict:
    resource = urlsplit(resource_url)
    issuer = urlsplit(issuer_url)
    if (resource.scheme != "https" or not resource.netloc
            or resource.username or resource.password or resource.fragment
            or resource.query or resource.path != "/mcp"):
        raise ValueError("public MCP resource must be an absolute HTTPS /mcp URL")
    if (issuer.scheme != "https" or not issuer.netloc
            or issuer.username or issuer.password or issuer.fragment
            or issuer.query):
        raise ValueError("OAuth issuer must be an HTTPS URL")
    return {
        "resource": resource_url,
        "authorization_servers": [issuer_url],
        "bearer_methods_supported": ["header"],
    }

def authenticate_challenge(*, resource_metadata_url: str) -> str:
    parts = urlsplit(resource_metadata_url)
    if parts.scheme != "https" or not parts.netloc or parts.fragment or parts.query:
        raise ValueError("metadata URL must be HTTPS")
    return f'Bearer resource_metadata="{resource_metadata_url}"'
