from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx


class RobotsCache:
    """Per-host robots.txt cache. Lazy: fetches on first lookup for a host."""

    def __init__(self, client: httpx.AsyncClient, user_agent: str) -> None:
        self._client = client
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def can_fetch(self, url: str) -> bool:
        parts = urlsplit(url)
        host_key = f"{parts.scheme}://{parts.netloc}"
        if host_key not in self._parsers:
            async with self._lock_for(host_key):
                if host_key not in self._parsers:
                    self._parsers[host_key] = await self._load(host_key)
        return self._parsers[host_key].can_fetch(self._user_agent, url)

    async def _load(self, host_key: str) -> RobotFileParser:
        rp = RobotFileParser()
        rp.set_url(f"{host_key}/robots.txt")
        try:
            resp = await self._client.get(
                f"{host_key}/robots.txt",
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
            )
            if 200 <= resp.status_code < 300:
                rp.parse(resp.text.splitlines())
            else:
                # No robots.txt or server error → allow everything.
                rp.parse([])
        except httpx.HTTPError:
            rp.parse([])
        return rp
