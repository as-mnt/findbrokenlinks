from __future__ import annotations

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef

# Friendlier messages keyed by Fetcher's short error codes. The "ssl_chain"
# entry is the most operationally useful — it directs the operator at a server
# misconfiguration (server isn't sending its intermediate CA) instead of
# generic "SSL failed".
_ERROR_MESSAGES: dict[str, str] = {
    "timeout": "Request timed out",
    "dns": "DNS resolution failed",
    "ssl": "SSL/TLS verification failed",
    "ssl_chain": (
        "Incomplete certificate chain — server didn't send the intermediate CA. "
        "Browsers paper over this via AIA fetching; many SDKs/CLI tools won't. "
        "Fix: serve fullchain.pem from the server."
    ),
    "connect": "Connection refused or host unreachable",
    "too_many_redirects": "Too many redirects",
    "network": "Network error",
}


@register
class NetworkErrorCheck(Check):
    code = "NETWORK_ERROR"
    severity = "error"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if fetch.error is None:
            return None
        message = _ERROR_MESSAGES.get(fetch.error, f"Network error: {fetch.error}")
        return Issue(
            code=self.code,
            severity=self.severity,
            message=message,
            details={"error": fetch.error},
        )
