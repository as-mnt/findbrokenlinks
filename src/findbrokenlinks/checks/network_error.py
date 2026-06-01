from __future__ import annotations

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@register
class NetworkErrorCheck(Check):
    code = "NETWORK_ERROR"
    severity = "error"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if fetch.error is None:
            return None
        return Issue(
            code=self.code,
            severity=self.severity,
            message=f"Network error: {fetch.error}",
            details={"error": fetch.error},
        )
