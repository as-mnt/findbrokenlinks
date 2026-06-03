"""Default incomplete-chain recovery in the Fetcher.

A server that omits its intermediate CA ("unable to get local issuer
certificate") is rejected by Python's TLS stack but accepted by browsers (which
fetch the missing cert via AIA). Rather than abort the whole crawl on such a
site, the Fetcher retries the request once over a verification-disabled client
and, on success, returns the page with ``tls_warning="ssl_chain"`` so a check
can surface a warning instead of a hard error.

Only ``ssl_chain`` triggers this fallback — genuinely invalid certs (expired,
self-signed, wrong host) must still fail as errors.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from findbrokenlinks.fetcher import Fetcher
from findbrokenlinks.rate_limiter import NoopLimiter

_LOCAL_ISSUER = (
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
    "unable to get local issuer certificate (_ssl.c:1032)"
)


def _stream_raising(exc: Exception) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=exc)
    cm.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock(spec=httpx.AsyncClient)
    client.stream = MagicMock(return_value=cm)
    return client


def _stream_ok(
    body: bytes = b"<html><body><h1>hi</h1></body></html>",
    content_type: str = "text/html",
    url: str = "https://misconfigured.example/",
) -> MagicMock:
    resp = MagicMock()
    resp.headers = httpx.Headers({"content-type": content_type})
    resp.status_code = 200
    resp.url = httpx.URL(url)
    resp.history = []
    resp.charset_encoding = "utf-8"

    async def _aiter():
        yield body

    resp.aiter_bytes = lambda: _aiter()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock(spec=httpx.AsyncClient)
    client.stream = MagicMock(return_value=cm)
    return client


def _fetcher(primary: MagicMock, insecure: MagicMock | None) -> Fetcher:
    return Fetcher(
        primary,
        NoopLimiter(),
        timeout_s=5.0,
        max_redirects=10,
        user_agent="x",
        insecure_client=insecure,
    )


@pytest.mark.asyncio
async def test_ssl_chain_falls_back_to_insecure_and_warns():
    """Primary verifies and fails on the missing intermediate; the insecure
    retry succeeds, so we crawl the page and flag a warning."""
    primary = _stream_raising(httpx.ConnectError(_LOCAL_ISSUER))
    insecure = _stream_ok()
    result = await _fetcher(primary, insecure).fetch("https://misconfigured.example/")
    assert result.error is None
    assert result.tls_warning == "ssl_chain"
    assert result.status == 200
    assert result.body is not None and "hi" in result.body
    insecure.stream.assert_called_once()


@pytest.mark.asyncio
async def test_ssl_chain_without_fallback_client_stays_error():
    """With --insecure the primary already skips verification, so no fallback
    client is wired and a real ssl_chain (retry impossible) remains an error."""
    primary = _stream_raising(httpx.ConnectError(_LOCAL_ISSUER))
    result = await _fetcher(primary, None).fetch("https://misconfigured.example/")
    assert result.error == "ssl_chain"
    assert result.tls_warning is None


@pytest.mark.asyncio
async def test_ssl_chain_retry_also_fails_keeps_original_error():
    """If the insecure retry fails too (e.g. the host is actually down), keep
    the original ssl_chain error rather than masking it."""
    primary = _stream_raising(httpx.ConnectError(_LOCAL_ISSUER))
    insecure = _stream_raising(httpx.ConnectError("[Errno 111] Connection refused"))
    result = await _fetcher(primary, insecure).fetch("https://misconfigured.example/")
    assert result.error == "ssl_chain"
    assert result.tls_warning is None


@pytest.mark.asyncio
async def test_generic_ssl_failure_is_not_retried():
    """Expired / self-signed / wrong-host certs are real problems — they must
    fail as errors and never consult the insecure fallback."""
    primary = _stream_raising(
        httpx.ConnectError("[SSL: CERTIFICATE_HAS_EXPIRED] certificate has expired")
    )
    insecure = _stream_ok()  # would succeed if (wrongly) consulted
    result = await _fetcher(primary, insecure).fetch("https://expired.example/")
    assert result.error == "ssl"
    assert result.tls_warning is None
    insecure.stream.assert_not_called()
