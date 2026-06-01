from __future__ import annotations

from urllib.parse import urlsplit

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


def _is_home_path(path: str) -> bool:
    return path in ("", "/")


@register
class RedirectToHomeCheck(Check):
    """Flag links that redirect to the site's root — a common soft-404 pattern."""

    code = "REDIRECT_TO_HOME"
    severity = "warning"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if len(fetch.redirect_chain) < 2:
            return None
        original = urlsplit(fetch.url)
        final = urlsplit(fetch.final_url)
        if not _is_home_path(final.path):
            return None
        if _is_home_path(original.path):
            return None  # the link itself pointed to home
        return Issue(
            code=self.code,
            severity=self.severity,
            message=f"Link redirected to home page ({fetch.final_url})",
            details={"final_url": fetch.final_url, "chain": fetch.redirect_chain},
        )
