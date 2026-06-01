"""Crawler must not loop on cyclic link graphs or redirect loops."""

from __future__ import annotations

import asyncio

import pytest

from findbrokenlinks.config import Config
from findbrokenlinks.crawler import crawl


@pytest.mark.asyncio
async def test_two_node_cycle_terminates_and_dedupes(live_server):
    """A ↔ B link cycle: each page must be fetched exactly once."""
    fetch_counts: dict[str, int] = {}

    async def _crawl():
        config = Config(
            start_url=live_server + "/cycle-a",
            mode="internal",
            rate_limit_rps=0,
            concurrency=4,
            ignore_robots=True,
            timeout_s=5.0,
        )
        # Wrap so we can observe duplicate fetches without hooking the fetcher itself.
        from findbrokenlinks import crawler as crawler_mod

        original_process = crawler_mod._process

        async def counting_process(state, url, *, extract, depth):
            fetch_counts[url] = fetch_counts.get(url, 0) + 1
            return await original_process(state, url, extract=extract, depth=depth)

        crawler_mod._process = counting_process
        try:
            return await crawl(config)
        finally:
            crawler_mod._process = original_process

    # Bound the test in time so a runaway loop fails the test instead of hanging.
    await asyncio.wait_for(_crawl(), timeout=10.0)

    # Each URL touched at most once by _process.
    assert all(c == 1 for c in fetch_counts.values()), fetch_counts
    # Both cycle pages were reached.
    assert any(u.endswith("/cycle-a") for u in fetch_counts)
    assert any(u.endswith("/cycle-b") for u in fetch_counts)


@pytest.mark.asyncio
async def test_self_loop_terminates(live_server):
    """A page that links to itself must terminate."""
    config = Config(
        start_url=live_server + "/selfloop",
        mode="internal",
        rate_limit_rps=0,
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
    )
    findings = await asyncio.wait_for(crawl(config), timeout=10.0)
    # The self-link itself isn't broken — it returns 200 — so no findings expected.
    assert all(
        not (f.link.url.endswith("/selfloop") and "HTTP_ERROR" in {i.code for i in f.issues})
        for f in findings
    )


@pytest.mark.asyncio
async def test_redirect_loop_is_caught_as_error(live_server):
    """/rloop-a redirects to /rloop-b which redirects back. httpx must bail out."""
    config = Config(
        start_url=live_server + "/rloop-a",
        mode="internal",
        rate_limit_rps=0,
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
        max_redirects=5,
    )
    findings = await asyncio.wait_for(crawl(config), timeout=10.0)
    # The seed itself should surface as a finding with a NETWORK_ERROR (too_many_redirects).
    assert any(
        f.link.url.endswith("/rloop-a") and "NETWORK_ERROR" in {i.code for i in f.issues}
        for f in findings
    ), [(f.link.url, [i.code for i in f.issues]) for f in findings]
