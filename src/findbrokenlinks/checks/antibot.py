"""Detect anti-bot blocks so they don't masquerade as broken links.

Many sites (tass.ru, news portals, anything behind DataDome / PerimeterX /
Cloudflare interstitial / Imperva) refuse to serve a request from a client
they classify as a bot. The response is technically a 4xx/5xx, but it's not
a *broken link* in any user-meaningful sense — a real visitor sees the page
just fine.

This check looks at the response body and headers of any 4xx/5xx response
and emits ``ANTIBOT_BLOCKED`` (warning, not error) when it matches a known
anti-bot vendor signature. ``HTTP_ERROR`` continues to fire too — operators
can suppress one or the other via ``--enable-checks`` / ``--disable-checks``
depending on whether they want to triage these separately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@dataclass(frozen=True)
class _Signature:
    vendor: str
    # Header signature: the named header (case-insensitive) is present at all.
    # Only used for headers that are specific to *blocking* — i.e., not
    # generic platform headers like cf-ray which appear on every Cloudflare
    # response (legit or not).
    header: str | None = None
    # Body signature: regex search against the response body.
    body_re: re.Pattern[str] | None = None


_SIGNATURES: tuple[_Signature, ...] = (
    # Vendor-specific blocking headers — these are only set on actual blocks.
    _Signature("datadome", header="x-datadome-cid"),
    _Signature("perimeterx", header="x-sp-crid"),  # the tass.ru case
    _Signature("sucuri", header="x-sucuri-block"),
    # Cloudflare interstitial / challenge body (their "Just a moment..." page).
    _Signature(
        "cloudflare",
        body_re=re.compile(r"(?i)just a moment\.\.\.|checking your browser before accessing"),
    ),
    _Signature(
        "cloudflare",
        body_re=re.compile(r"(?i)cloudflare[^<]{0,200}(ray id|attention required)"),
    ),
    # Akamai bot manager block page.
    _Signature("akamai", body_re=re.compile(r"(?i)reference\s*#\d+\.[a-f0-9]+|akamaighost")),
    # Imperva / Incapsula.
    _Signature("imperva", body_re=re.compile(r"(?i)incident\s*id:\s*\d+|imperva|incapsula")),
    # PerimeterX / HUMAN block body (in case header missing).
    _Signature("perimeterx", body_re=re.compile(r"(?i)px-captcha|perimeterx")),
    # Generic anti-bot text — short bodies typical of WAF block pages.
    _Signature("generic", body_re=re.compile(r"(?i)\bif you are not a bot\b")),
    _Signature("generic", body_re=re.compile(r"(?i)\bbot detected\b|\bare you a bot\b")),
    _Signature(
        "generic",
        body_re=re.compile(r"(?i)please (complete the captcha|verify you'?re human)"),
    ),
    _Signature("generic", body_re=re.compile(r"(?i)ddos protection by")),
    _Signature("generic", body_re=re.compile(r"(?i)pardon our interruption")),
    _Signature("generic", body_re=re.compile(r"(?i)access denied[^<]{0,80}bot")),
)


def _detect(fetch: FetchResult) -> str | None:
    """Return vendor name if any signature matches the response, else None."""
    headers_lower = {k.lower(): v for k, v in fetch.headers.items()}
    body = fetch.body or ""
    for sig in _SIGNATURES:
        if sig.header is not None and sig.header.lower() in headers_lower:
            return sig.vendor
        if sig.body_re is not None and body and sig.body_re.search(body):
            return sig.vendor
    return None


@register
class AntibotBlockedCheck(Check):
    code = "ANTIBOT_BLOCKED"
    severity = "warning"

    def evaluate(
        self, link: LinkRef, fetch: FetchResult, ctx: CheckContext
    ) -> Issue | None:
        # Only suspect anti-bot when the server actually returned an error.
        # A 200 page that happens to contain the word "bot" is not a block.
        if fetch.status is None or not (400 <= fetch.status < 600):
            return None
        vendor = _detect(fetch)
        if vendor is None:
            return None
        return Issue(
            code=self.code,
            severity=self.severity,
            message=f"Likely anti-bot block ({vendor}); may not be a real broken link",
            details={"vendor": vendor, "status": fetch.status},
        )
