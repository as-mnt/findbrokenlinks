from __future__ import annotations

import time
from typing import Protocol

import httpx

from findbrokenlinks.models import FetchResult

# Content-Type prefixes we consider "text-like" and worth reading into memory.
_TEXT_TYPES = ("text/", "application/xhtml", "application/xml", "application/json")

DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MB


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

    async def fetch(self, url: str) -> FetchResult:
        await self._limiter.acquire()
        start = time.perf_counter()
        try:
            async with self._client.stream(
                "GET",
                url,
                follow_redirects=True,
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
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
            msg = str(e)
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
