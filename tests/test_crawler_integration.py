from __future__ import annotations

import pytest

from findbrokenlinks.config import Config
from findbrokenlinks.crawler import crawl


@pytest.mark.asyncio
async def test_finds_expected_issues(live_server):
    config = Config(
        start_url=live_server + "/",
        mode="internal+external",
        rate_limit_rps=0,  # no limiting for tests
        concurrency=4,
        ignore_robots=True,
        timeout_s=5.0,
    )
    findings = await crawl(config)
    by_url: dict[str, list[str]] = {}
    for f in findings:
        by_url.setdefault(f.link.url, []).extend(i.code for i in f.issues)

    # 404 link
    assert any(
        url.endswith("/missing") and "HTTP_ERROR" in codes
        for url, codes in by_url.items()
    )
    # broken image (404 on /img-broken.png)
    assert any(
        url.endswith("/img-broken.png") and "HTTP_ERROR" in codes
        for url, codes in by_url.items()
    )
    # redirect to home
    assert any(
        url.endswith("/redirect-home") and "REDIRECT_TO_HOME" in codes
        for url, codes in by_url.items()
    )
    # 4-hop redirect chain
    assert any(
        url.endswith("/redirect-chain") and "REDIRECT_CHAIN" in codes
        for url, codes in by_url.items()
    )
    # soft-404 by pattern (200 with "Страница не найдена" body)
    assert any(
        url.endswith("/soft404-pattern") and "SOFT_404_PATTERN" in codes
        for url, codes in by_url.items()
    )
    # external dead host → NETWORK_ERROR
    assert any(
        "nonexistent-host.invalid" in url and "NETWORK_ERROR" in codes
        for url, codes in by_url.items()
    )
