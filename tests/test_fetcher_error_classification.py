"""Fetcher must classify SSL errors as 'ssl', not 'connect'.

SSL verification failures bubble up as httpx.ConnectError (a subclass of
HTTPError), so they used to fall into the generic 'connect' bucket alongside
plain TCP refusals. They're a meaningfully different category — typically
caused by a private CA the system doesn't trust by default rather than
the site actually being down.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from findbrokenlinks.fetcher import Fetcher
from findbrokenlinks.rate_limiter import NoopLimiter


def _stream_raising(exc: Exception):
    """Return an object whose context manager raises ``exc`` on entry."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=exc)
    cm.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock(spec=httpx.AsyncClient)
    client.stream = MagicMock(return_value=cm)
    return client


@pytest.mark.asyncio
async def test_ssl_certificate_verify_classified_as_ssl():
    """ConnectError that mentions SSL/certificate must surface as error='ssl'."""
    exc = httpx.ConnectError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "unable to get local issuer certificate (_ssl.c:1032)"
    )
    client = _stream_raising(exc)
    fetcher = Fetcher(
        client, NoopLimiter(), timeout_s=5.0, max_redirects=10, user_agent="x",
    )
    result = await fetcher.fetch("https://gov.example/")
    assert result.error == "ssl", result


@pytest.mark.asyncio
async def test_dns_failure_classified_as_dns():
    exc = httpx.ConnectError("[Errno -2] Name or service not known")
    client = _stream_raising(exc)
    fetcher = Fetcher(
        client, NoopLimiter(), timeout_s=5.0, max_redirects=10, user_agent="x",
    )
    result = await fetcher.fetch("https://nonexistent.invalid/")
    assert result.error == "dns"


@pytest.mark.asyncio
async def test_plain_tcp_refused_classified_as_connect():
    exc = httpx.ConnectError("[Errno 111] Connection refused")
    client = _stream_raising(exc)
    fetcher = Fetcher(
        client, NoopLimiter(), timeout_s=5.0, max_redirects=10, user_agent="x",
    )
    result = await fetcher.fetch("https://x/")
    assert result.error == "connect"


@pytest.mark.asyncio
async def test_timeout_classified_as_timeout():
    exc = httpx.ConnectTimeout("connect timeout")
    client = _stream_raising(exc)
    fetcher = Fetcher(
        client, NoopLimiter(), timeout_s=5.0, max_redirects=10, user_agent="x",
    )
    result = await fetcher.fetch("https://slow/")
    assert result.error == "timeout"
