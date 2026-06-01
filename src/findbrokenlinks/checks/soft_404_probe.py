from __future__ import annotations

import hashlib
import re

from bs4 import BeautifulSoup

from findbrokenlinks.checks.base import Baseline404, Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef
from findbrokenlinks.scope import host_of

_WS_RE = re.compile(r"\s+")


def normalize_html_text(body: str) -> str:
    soup = BeautifulSoup(body, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return _WS_RE.sub(" ", text)


def baseline_from_fetch(fetch: FetchResult) -> Baseline404:
    text = normalize_html_text(fetch.body or "")
    return Baseline404(
        status=fetch.status,
        final_url=fetch.final_url,
        text_len=len(text),
        text_hash=hashlib.sha1(text.encode("utf-8")).hexdigest(),
    )


@register
class Soft404ProbeCheck(Check):
    """Compare a 2xx response to a known-404 baseline for the same host."""

    code = "SOFT_404_PROBE"
    severity = "warning"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if fetch.status is None or fetch.status >= 300 or fetch.status < 200:
            return None
        if not fetch.body:
            return None
        host = host_of(fetch.final_url)
        baseline = ctx.baselines.get(host)
        if baseline is None or baseline.text_len == 0:
            return None
        # Final URL exactly matching baseline final_url is a strong signal (server redirects
        # unknown URLs to a generic page).
        if fetch.final_url == baseline.final_url and fetch.url != baseline.final_url:
            return Issue(
                code=self.code,
                severity=self.severity,
                message=f"Response identical to baseline 404 endpoint ({baseline.final_url})",
                details={"reason": "final_url_match", "baseline_url": baseline.final_url},
            )
        text = normalize_html_text(fetch.body)
        if not text:
            return None
        # Compare length within ±10% and hash equality.
        diff = abs(len(text) - baseline.text_len)
        rel = diff / max(baseline.text_len, 1)
        cur_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if rel <= 0.1 and cur_hash == baseline.text_hash:
            return Issue(
                code=self.code,
                severity=self.severity,
                message="Response body matches known 404 baseline",
                details={"reason": "body_match", "baseline_len": baseline.text_len},
            )
        return None
