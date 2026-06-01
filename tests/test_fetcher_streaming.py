"""Verify fetcher streams responses: skips binary bodies, caps text bodies."""

from __future__ import annotations

import httpx
import pytest

from findbrokenlinks.fetcher import Fetcher
from findbrokenlinks.rate_limiter import NoopLimiter


@pytest.mark.asyncio
async def test_binary_body_is_not_downloaded(live_server):
    """A 5 MB PDF should return status=200 with body=None and no download."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        fetcher = Fetcher(
            client,
            NoopLimiter(),
            timeout_s=5.0,
            max_redirects=10,
            user_agent="fbl-test",
            max_body_bytes=1024,  # tiny cap to prove we don't read binary anyway
        )
        result = await fetcher.fetch(live_server + "/big.pdf")
    assert result.status == 200
    assert result.content_type == "application/pdf"
    assert result.body is None  # binary → never read
    assert result.error is None


@pytest.mark.asyncio
async def test_text_body_is_capped(live_server):
    """A 2 MB HTML page must be truncated when fetched with a 100 KB cap."""
    cap = 100 * 1024
    async with httpx.AsyncClient(timeout=5.0) as client:
        fetcher = Fetcher(
            client,
            NoopLimiter(),
            timeout_s=5.0,
            max_redirects=10,
            user_agent="fbl-test",
            max_body_bytes=cap,
        )
        result = await fetcher.fetch(live_server + "/big.html")
    assert result.status == 200
    assert result.content_type == "text/html"
    assert result.body is not None
    assert len(result.body.encode("utf-8")) <= cap
    assert result.headers.get("x-fbl-body-truncated") == "1"


@pytest.mark.asyncio
async def test_small_text_body_is_not_truncated(live_server):
    async with httpx.AsyncClient(timeout=5.0) as client:
        fetcher = Fetcher(
            client,
            NoopLimiter(),
            timeout_s=5.0,
            max_redirects=10,
            user_agent="fbl-test",
        )
        result = await fetcher.fetch(live_server + "/ok")
    assert result.body is not None
    assert "<h1>OK</h1>" in result.body
    assert "x-fbl-body-truncated" not in result.headers
