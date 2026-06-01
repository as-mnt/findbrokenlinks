from __future__ import annotations

import time
from typing import Protocol

import httpx

from findbrokenlinks.models import FetchResult

_TEXT_TYPES = ("text/", "application/xhtml", "application/xml", "application/json")


class _Limiter(Protocol):
    async def acquire(self) -> None: ...


class Fetcher:
    """httpx wrapper that tracks the full redirect chain and classifies errors."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        limiter: _Limiter,
        *,
        timeout_s: float,
        max_redirects: int,
        user_agent: str,
    ) -> None:
        self._client = client
        self._limiter = limiter
        self._timeout = timeout_s
        self._max_redirects = max_redirects
        self._user_agent = user_agent

    async def fetch(self, url: str) -> FetchResult:
        await self._limiter.acquire()
        start = time.perf_counter()
        try:
            resp = await self._client.get(
                url,
                follow_redirects=True,
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
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

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        chain = [str(h.url) for h in resp.history] + [str(resp.url)]
        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        body: str | None = None
        if any(content_type.startswith(t) for t in _TEXT_TYPES):
            try:
                body = resp.text
            except Exception:
                body = None
        return FetchResult(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            redirect_chain=chain,
            headers=dict(resp.headers),
            body=body,
            elapsed_ms=elapsed_ms,
            error=None,
            content_type=content_type or None,
        )

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
