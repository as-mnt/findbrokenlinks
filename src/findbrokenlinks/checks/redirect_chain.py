from __future__ import annotations

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@register
class RedirectChainCheck(Check):
    code = "REDIRECT_CHAIN"
    severity = "warning"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        hops = len(fetch.redirect_chain) - 1  # chain includes final URL
        threshold = ctx.config.redirect_chain_threshold
        if hops < threshold:
            return None
        return Issue(
            code=self.code,
            severity=self.severity,
            message=f"Long redirect chain: {hops} hops (threshold {threshold})",
            details={"hops": hops, "chain": fetch.redirect_chain},
        )
