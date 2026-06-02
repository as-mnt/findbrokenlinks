"""Sitemap discovery must share the Fetcher's network policy.

Before this change ``_seed_from_sitemap`` called ``client.get`` directly:
no token-bucket throttling, no Accept-Language, no body cap. That made
``/sitemap.xml`` an architectural hole. Now it must go through
``Fetcher.fetch_text``.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from findbrokenlinks.config import Config
from findbrokenlinks.crawler import crawl
from findbrokenlinks.fetcher import Fetcher
from findbrokenlinks.rate_limiter import NoopLimiter


@pytest.mark.asyncio
async def test_fetch_text_reads_xml_body(live_server):
    """The new method gets the XML body that ``fetch()`` would have dropped."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        fetcher = Fetcher(
            client, NoopLimiter(),
            timeout_s=5.0, max_redirects=5, user_agent="fbl-test",
        )
        plain = await fetcher.fetch(live_server + "/sitemap.xml")
        wide = await fetcher.fetch_text(live_server + "/sitemap.xml")

    # fetch() with the narrow type list won't pull an XML body.
    assert plain.status == 200
    assert plain.body is None

    # fetch_text() does — and the body is the actual sitemap.
    assert wide.status == 200
    assert wide.body is not None
    assert "<urlset" in wide.body
    assert "/from-sitemap-ok" in wide.body


@pytest.mark.asyncio
async def test_sitemap_urls_get_crawled_when_use_sitemap_is_on(live_server):
    """End-to-end: with ``use_sitemap=True`` the sitemap's URLs end up fetched
    (one of them is a 404 we expect to see as a finding)."""
    config = Config(
        start_url=live_server + "/ok",
        mode="internal",
        use_sitemap=True,
        rate_limit_rps=0,
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
        soft404_probe_enabled=False,
    )
    findings = await asyncio.wait_for(crawl(config), timeout=10.0)
    urls_with_findings = {f.link.url for f in findings}
    # The 404 endpoint pulled in from sitemap surfaces as a broken-link finding.
    assert any(u.endswith("/from-sitemap-404") for u in urls_with_findings), (
        f"sitemap-discovered URL missing from findings: {urls_with_findings}"
    )


@pytest.mark.asyncio
async def test_sitemap_fetch_uses_the_limiter(live_server, monkeypatch):
    """The sitemap fetch must hit the same token bucket as everything else.

    Count calls to ``TokenBucket.acquire`` during a crawl with the sitemap
    seeding turned on. Before the refactor, the bare ``client.get`` in
    ``_seed_from_sitemap`` bypassed the limiter — so the count would be
    "seed + sitemap targets" rather than "seed + sitemap meta + sitemap
    targets". We assert at least one extra acquire beyond the no-sitemap
    baseline.
    """
    from findbrokenlinks.rate_limiter import TokenBucket

    calls = 0
    real_acquire = TokenBucket.acquire

    async def counting_acquire(self):
        nonlocal calls
        calls += 1
        await real_acquire(self)

    monkeypatch.setattr(TokenBucket, "acquire", counting_acquire)

    base_config = dict(
        start_url=live_server + "/ok",
        mode="internal",
        rate_limit_rps=100,  # high enough to never actually block the test
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
        soft404_probe_enabled=False,
    )

    # Baseline: no sitemap.
    calls = 0
    await asyncio.wait_for(crawl(Config(**base_config, use_sitemap=False)), timeout=10.0)
    no_sitemap = calls

    # With sitemap: must use the limiter for at least the sitemap.xml fetch
    # plus its two discovered URLs (/from-sitemap-ok, /from-sitemap-404).
    calls = 0
    await asyncio.wait_for(crawl(Config(**base_config, use_sitemap=True)), timeout=10.0)
    with_sitemap = calls

    assert with_sitemap > no_sitemap, (no_sitemap, with_sitemap)
