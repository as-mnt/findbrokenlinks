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

# Warnings keyed by FetchResult.tls_warning — the request *succeeded* (status,
# body present) but only because verification was relaxed for a recoverable
# reason. We still crawl the page; the operator just needs to know the chain
# is broken so they can fix the server.
_WARNING_MESSAGES: dict[str, str] = {
    "ssl_chain": (
        "Incomplete certificate chain — server didn't send the intermediate CA. "
        "Crawled anyway with TLS verification relaxed (browsers tolerate this via "
        "AIA fetching). Fix: serve fullchain.pem from the server."
    ),
}


@register
class NetworkErrorCheck(Check):
    code = "NETWORK_ERROR"
    severity = "error"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if fetch.error is not None:
            message = _ERROR_MESSAGES.get(fetch.error, f"Network error: {fetch.error}")
            return Issue(
                code=self.code,
                severity="error",
                message=message,
                details={"error": fetch.error},
            )
        if fetch.tls_warning is not None:
            message = _WARNING_MESSAGES.get(
                fetch.tls_warning, f"TLS warning: {fetch.tls_warning}"
            )
            return Issue(
                code=self.code,
                severity="warning",
                message=message,
                details={"tls_warning": fetch.tls_warning},
            )
        return None
