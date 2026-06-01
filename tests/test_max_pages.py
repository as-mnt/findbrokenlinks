"""Verify the --max-pages safety cap actually stops enqueuing past the limit."""

from __future__ import annotations

import pytest

from findbrokenlinks import crawler as crawler_mod
from findbrokenlinks.config import Config
from findbrokenlinks.crawler import crawl


@pytest.mark.asyncio
async def test_max_pages_caps_enqueued_urls(live_server, monkeypatch):
    """With max_pages=3, the crawler must not process more than 3 URLs."""
    processed: list[str] = []
    original_process = crawler_mod._process

    async def counting_process(state, url, *, extract, depth):
        processed.append(url)
        return await original_process(state, url, extract=extract, depth=depth)

    monkeypatch.setattr(crawler_mod, "_process", counting_process)

    config = Config(
        start_url=live_server + "/",
        mode="internal",
        rate_limit_rps=0,
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
        max_pages=3,
        soft404_probe_enabled=False,  # probe bypasses the queue — exclude from count
    )
    await crawl(config)
    assert len(processed) <= 3, processed


@pytest.mark.asyncio
async def test_max_pages_zero_means_unlimited(live_server, monkeypatch):
    """max_pages=0 should not cap anything."""
    processed: list[str] = []
    original_process = crawler_mod._process

    async def counting_process(state, url, *, extract, depth):
        processed.append(url)
        return await original_process(state, url, extract=extract, depth=depth)

    monkeypatch.setattr(crawler_mod, "_process", counting_process)

    config = Config(
        start_url=live_server + "/",
        mode="internal",
        rate_limit_rps=0,
        concurrency=4,
        ignore_robots=True,
        timeout_s=5.0,
        max_pages=0,
        soft404_probe_enabled=False,
    )
    await crawl(config)
    # The local server has ~10 internal routes reachable from /; with cap off we
    # should pull more than 3 (the small-cap value used in the other test).
    assert len(processed) > 3, processed
