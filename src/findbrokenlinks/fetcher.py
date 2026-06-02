from __future__ import annotations

import time
from typing import Protocol

import httpx

from findbrokenlinks.models import FetchResult

# Content-Type prefixes we read into memory. We need bodies for HTML extraction
# (text/html, application/xhtml) and soft-404 pattern matching (also HTML).
# Other text-like types (text/javascript, text/css, application/json, text/xml,
# application/xml) don't contribute to either, and parsing JS as HTML actively
# *produces false positives* — bs4/lxml interpret JS string literals like
# `'<img src="'+png+'"/>'` as real img tags. Narrow the list explicitly.
# text/plain is kept because some misconfigured sites serve HTML as plain text.
_TEXT_TYPES = ("text/html", "text/plain", "application/xhtml")

DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MB

# Default Accept-* headers. Many sites' WAFs treat requests without these as
# bot traffic and return 403 (e.g., ras.ru's ASP.NET endpoint did exactly that
# during early testing). Our User-Agent still identifies us honestly — we just
# stop sending malformed-looking requests.
_DEFAULT_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.5"


class _Limiter(Protocol):
    async def acquire(self) -> None: ...


class Fetcher:
    """httpx wrapper that streams responses, classifies errors, and caps body size.

    Non-text responses (PDF, images, archives, …) are *not* downloaded — we read
    headers, record the status, then abort the body. Text responses are read up to
    ``max_body_bytes`` and the rest is discarded.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        limiter: _Limiter,
        *,
        timeout_s: float,
        max_redirects: int,
        user_agent: str,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._timeout = timeout_s
        self._max_redirects = max_redirects
        self._user_agent = user_agent
        self._max_body_bytes = max_body_bytes
        self._headers = {
            "User-Agent": user_agent,
            "Accept": _DEFAULT_ACCEPT,
            "Accept-Language": _DEFAULT_ACCEPT_LANGUAGE,
        }

    async def fetch(self, url: str) -> FetchResult:
        await self._limiter.acquire()
        start = time.perf_counter()
        try:
            async with self._client.stream(
                "GET",
                url,
                follow_redirects=True,
                timeout=self._timeout,
                headers=self._headers,
            ) as resp:
                content_type = (
                    (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                )
                is_text = any(content_type.startswith(t) for t in _TEXT_TYPES)

                body: str | None = None
                truncated = False
                if is_text:
                    body, truncated = await _read_capped(resp, self._max_body_bytes)
                # else: exit the context without reading — httpx closes the stream,
                # so the body never gets downloaded.

                elapsed_ms = (time.perf_counter() - start) * 1000.0
                chain = [str(h.url) for h in resp.history] + [str(resp.url)]
                headers = dict(resp.headers)
                if truncated:
                    headers["x-fbl-body-truncated"] = "1"
                return FetchResult(
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    redirect_chain=chain,
                    headers=headers,
                    body=body,
                    elapsed_ms=elapsed_ms,
                    error=None,
                    content_type=content_type or None,
                )
        except httpx.TimeoutException:
            return self._error(url, start, "timeout")
        except httpx.ConnectError as e:
            # ConnectError covers DNS failures, plain TCP refused, AND SSL
            # verification errors. Distinguish by message — SSL errors should
            # not be lumped in with generic "connect" since they're a different
            # class of problem (often caused by a private CA the OS doesn't
            # trust by default rather than the site being broken).
            msg = str(e)
            msg_lower = msg.lower()
            if "ssl" in msg_lower or "certificate" in msg_lower:
                return self._error(url, start, "ssl")
            is_dns = "Name or service not known" in msg or "nodename" in msg
            return self._error(url, start, "dns" if is_dns else "connect")
        except httpx.TooManyRedirects:
            return self._error(url, start, "too_many_redirects")
        except httpx.HTTPError as e:
            msg = str(e).lower()
            kind = "ssl" if "ssl" in msg or "certificate" in msg else "network"
            return self._error(url, start, kind)

    @staticmethod
    def _error(url: str, start: float, error: str) -> FetchResult:
        elapsed = (time.perf_counter() - start) * 1000.0
        return FetchResult(
            url=url,
            final_url=url,
            status=None,
            redirect_chain=[url],
            headers={},
            body=None,
            elapsed_ms=elapsed,
            error=error,
        )


async def _read_capped(resp: httpx.Response, limit: int) -> tuple[str, bool]:
    """Stream the body in chunks, stopping at ``limit`` bytes. Returns (text, truncated)."""
    chunks: list[bytes] = []
    total = 0
    truncated = False
    async for chunk in resp.aiter_bytes():
        if total + len(chunk) > limit:
            chunks.append(chunk[: limit - total])
            total = limit
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)
    raw = b"".join(chunks)
    encoding = resp.charset_encoding or "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return text, truncated
