"""Don't extract from non-HTML responses.

A JS bundle containing string literals like `'<img src="'+png+'.png"/>'` used
to be parsed as HTML by bs4, producing fake "broken link" findings for the
literal string fragments — that's what produced the bogus "template bug" pile
on the poi.dvo.ru crawl. Fix: trust the Content-Type header.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from findbrokenlinks.config import Config
from findbrokenlinks.crawler import _is_html_content_type, crawl
from findbrokenlinks.fetcher import Fetcher
from findbrokenlinks.rate_limiter import NoopLimiter

# ----- the helper itself ----- #

def test_html_content_types_accepted():
    assert _is_html_content_type("text/html")
    assert _is_html_content_type("text/html; charset=utf-8")
    assert _is_html_content_type("application/xhtml+xml")
    assert _is_html_content_type("TEXT/HTML")  # case-insensitive


def test_non_html_content_types_rejected():
    assert not _is_html_content_type("text/javascript")
    assert not _is_html_content_type("application/javascript")
    assert not _is_html_content_type("text/css")
    assert not _is_html_content_type("application/json")
    assert not _is_html_content_type("application/xml")
    assert not _is_html_content_type("image/png")


def test_missing_content_type_is_optimistically_html():
    """Some misconfigured servers omit the header — try anyway."""
    assert _is_html_content_type(None)
    assert _is_html_content_type("")


# ----- fetcher narrows what it reads ----- #

@pytest.mark.asyncio
async def test_fetcher_does_not_read_javascript_body(live_server):
    async with httpx.AsyncClient(timeout=5.0) as client:
        fetcher = Fetcher(
            client, NoopLimiter(),
            timeout_s=5.0, max_redirects=5, user_agent="fbl-test",
        )
        result = await fetcher.fetch(live_server + "/bundle.js")
    assert result.status == 200
    assert result.content_type == "text/javascript"
    # Body is now None — text/javascript is no longer in _TEXT_TYPES, so the
    # streaming path skips reading it altogether.
    assert result.body is None


# ----- end-to-end: crawl a page that links to a JS bundle ----- #

@pytest.mark.asyncio
async def test_js_bundle_does_not_produce_link_findings(live_server):
    """The bundle contains JS strings that look like <a>/<img> tags. Those
    must NOT surface as findings — the content-type guard short-circuits
    extraction before bs4 sees them."""
    config = Config(
        start_url=live_server + "/bundle.js",
        mode="page",
        rate_limit_rps=0,
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
        soft404_probe_enabled=False,
    )
    findings = await asyncio.wait_for(crawl(config), timeout=10.0)
    # The only finding could be the seed itself (a synthetic LinkRef pointing
    # at /bundle.js with tag="seed"). It should NOT contain any inferred
    # <a>/<img> links pulled out of the JS source.
    for f in findings:
        assert "'+link+'" not in f.link.url
        assert "'+png+'" not in f.link.url
        assert "+png+" not in f.link.url
