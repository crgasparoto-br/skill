"""Pinned HTTPS GitHub transport: no environment proxy and no redirects.

Only trusted, fixed github.com URLs may use this opener. Never pass user URLs
or an MCP tool parameter to it; repository lookup functions construct URLs.
"""
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def safe_open(request: urllib.request.Request, *, timeout: int):
    if (request.full_url.startswith("https://api.github.com/") is False
            or request.get_method() != "GET"):
        raise ValueError("untrusted GitHub read endpoint")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
    )
    return opener.open(request, timeout=timeout)
