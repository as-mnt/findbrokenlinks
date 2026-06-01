from __future__ import annotations

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@register
class HttpStatusCheck(Check):
    code = "HTTP_ERROR"
    severity = "error"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if fetch.status is None:
            return None
        if fetch.status >= 400:
            return Issue(
                code=self.code,
                severity=self.severity,
                message=f"HTTP {fetch.status}",
                details={"status": fetch.status, "final_url": fetch.final_url},
            )
        return None
