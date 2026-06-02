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

import html
import re
from dataclasses import dataclass

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@dataclass(frozen=True)
class _Signature:
    vendor: str
    # Header signature: the named header (case-insensitive) is present.
    # Used either alone (presence is enough — only for headers that are
    # *only* set on blocks, like x-datadome-cid) or in combination with
    # header_value_re for headers whose name is generic but value identifies
    # the vendor (e.g., server: ddos-guard).
    header: str | None = None
    header_value_re: re.Pattern[str] | None = None
    # Body signature: regex search against the response body. Matched against
    # the entity-decoded body so HTML-encoded payloads (Akamai's typical
    # "Reference&#32;&#35;..." output) match plain-text patterns.
    body_re: re.Pattern[str] | None = None


_SIGNATURES: tuple[_Signature, ...] = (
    # Vendor-specific blocking headers — these are only set on actual blocks.
    _Signature("datadome", header="x-datadome-cid"),
    _Signature("perimeterx", header="x-sp-crid"),  # the tass.ru case
    _Signature("sucuri", header="x-sucuri-block"),
    # Cloudflare sets cf-mitigated specifically on requests it blocked or
    # challenged — distinct from the generic cf-ray that appears everywhere.
    _Signature("cloudflare", header="cf-mitigated"),
    # DDoS-Guard (Russian DDoS protection CDN) — the iz.ru case. The Server
    # header value is the reliable signal; the header name itself is generic
    # but the value isn't.
    _Signature(
        "ddos-guard",
        header="server",
        header_value_re=re.compile(r"(?i)ddos[-_ ]?guard"),
    ),
    # Cloudflare interstitial / challenge body (their "Just a moment..." page).
    _Signature(
        "cloudflare",
        body_re=re.compile(r"(?i)just a moment\.\.\.|checking your browser before accessing"),
    ),
    _Signature(
        "cloudflare",
        body_re=re.compile(r"(?i)cloudflare[^<]{0,200}(ray id|attention required)"),
    ),
    # Akamai bot manager block page. mdpi.com emits HTML-entity-encoded
    # "Reference&#32;&#35;..." — handled by entity-decoding the body before
    # regex search (see _detect).
    _Signature(
        "akamai",
        body_re=re.compile(r"(?i)reference\s*#\d+\.[a-f0-9]+|akamaighost|edgesuite\.net"),
    ),
    # Imperva / Incapsula.
    _Signature("imperva", body_re=re.compile(r"(?i)incident\s*id:\s*\d+|imperva|incapsula")),
    # PerimeterX / HUMAN block body (in case header missing).
    _Signature("perimeterx", body_re=re.compile(r"(?i)px-captcha|perimeterx")),
    # DDoS-Guard sometimes serves a JS challenge body.
    _Signature("ddos-guard", body_re=re.compile(r"(?i)ddos-guard\.net")),
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
    raw_body = fetch.body or ""
    # Entity-decode once: catches Akamai's classic "Reference&#32;&#35;..."
    # output, where the literal HTML has &#46; in place of `.` and &#35; in
    # place of `#`.
    decoded_body = html.unescape(raw_body) if raw_body else ""
    for sig in _SIGNATURES:
        if sig.header is not None:
            value = headers_lower.get(sig.header.lower())
            if value is None:
                continue
            if sig.header_value_re is None or sig.header_value_re.search(value):
                return sig.vendor
            # Header present but value didn't match — try other signatures.
            continue
        if sig.body_re is not None and decoded_body and sig.body_re.search(decoded_body):
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
