from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

import httpx

from findbrokenlinks.checks import REGISTRY as CHECK_REGISTRY  # noqa: F401 — registry side effect
from findbrokenlinks.checks.base import CheckContext, active_checks
from findbrokenlinks.checks.soft_404_pattern import load_patterns
from findbrokenlinks.checks.soft_404_probe import baseline_from_fetch
from findbrokenlinks.config import Config
from findbrokenlinks.extractors.html import HTMLExtractor
from findbrokenlinks.fetcher import Fetcher
from findbrokenlinks.models import FetchResult, Finding, LinkRef
from findbrokenlinks.rate_limiter import NoopLimiter, TokenBucket
from findbrokenlinks.robots import RobotsCache
from findbrokenlinks.scope import Scope, host_of, normalize_url

log = logging.getLogger("findbrokenlinks")


async def crawl(config: Config) -> list[Finding]:
    seed = normalize_url(config.start_url)
    scope = Scope(seed, config.mode)
    limiter = TokenBucket(config.rate_limit_rps) if config.rate_limit_rps > 0 else NoopLimiter()
    timeout = httpx.Timeout(config.timeout_s)
    limits = httpx.Limits(
        max_connections=max(config.concurrency * 2, 20),
        max_keepalive_connections=config.concurrency,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        max_redirects=config.max_redirects,
        http2=True,
    ) as client:
        fetcher = Fetcher(
            client,
            limiter,
            timeout_s=config.timeout_s,
            max_redirects=config.max_redirects,
            user_agent=config.user_agent,
        )
        robots = (
            None
            if config.ignore_robots
            else RobotsCache(client, config.user_agent)
        )
        ctx = CheckContext(
            config=config,
            base_host=host_of(seed),
            soft404_patterns=load_patterns(config.patterns_path),
        )
        state = _CrawlState(scope, robots, fetcher, ctx, config)

        # Synthetic seed LinkRef so seed-page issues surface in findings.
        state.links.append(LinkRef(url=seed, source_page=seed, anchor=None, tag="seed"))

        # Seed queue.
        await state.enqueue(seed, extract=True)

        # Sitemap (optional) — internal only, recurse.
        if config.use_sitemap and config.mode != "page":
            await _seed_from_sitemap(client, seed, state, config.user_agent)

        workers = [
            asyncio.create_task(_worker(state)) for _ in range(max(1, config.concurrency))
        ]
        await state.queue.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        return _build_findings(state, ctx)


class _CrawlState:
    def __init__(
        self,
        scope: Scope,
        robots: RobotsCache | None,
        fetcher: Fetcher,
        ctx: CheckContext,
        config: Config,
    ) -> None:
        self.scope = scope
        self.robots = robots
        self.fetcher = fetcher
        self.ctx = ctx
        self.config = config
        self.extractor = HTMLExtractor()
        self.queue: asyncio.Queue[tuple[str, bool, int]] = asyncio.Queue()
        self.enqueued: set[str] = set()
        self.fetched: dict[str, FetchResult] = {}
        self.extracted_from: set[str] = set()  # normalized final URLs we've already parsed
        self.links: list[LinkRef] = []
        self.probed_hosts: set[str] = set()
        self.probe_locks: dict[str, asyncio.Lock] = {}

    async def enqueue(self, url: str, *, extract: bool, depth: int = 0) -> None:
        if url in self.enqueued:
            return
        if self.config.depth and depth > self.config.depth:
            return
        self.enqueued.add(url)
        await self.queue.put((url, extract, depth))


async def _worker(state: _CrawlState) -> None:
    while True:
        url, extract, depth = await state.queue.get()
        try:
            await _process(state, url, extract=extract, depth=depth)
        except Exception:  # noqa: BLE001 — worker must not die on a single URL
            log.exception("error processing %s", url)
        finally:
            state.queue.task_done()


async def _process(state: _CrawlState, url: str, *, extract: bool, depth: int) -> None:
    if url in state.fetched:
        return

    if state.robots is not None:
        try:
            allowed = await state.robots.can_fetch(url)
        except Exception:
            allowed = True
        if not allowed:
            log.info("robots.txt disallows %s", url)
            return

    await _ensure_probe(state, url)
    fetch = await state.fetcher.fetch(url)
    state.fetched[url] = fetch

    if not extract or not fetch.body:
        return

    # The body actually belongs to final_url. Attribute links there and dedupe so a single
    # page reached via redirect isn't parsed twice.
    final_norm = normalize_url(fetch.final_url)
    if final_norm in state.extracted_from:
        return
    state.extracted_from.add(final_norm)
    source = fetch.final_url

    for link in state.extractor.extract(fetch.body, source_page=source):
        state.links.append(link)
        target = normalize_url(link.url)
        if not state.scope.should_fetch(target):
            continue
        will_extract = state.scope.should_recurse(target)
        await state.enqueue(target, extract=will_extract, depth=depth + 1)


async def _ensure_probe(state: _CrawlState, url: str) -> None:
    """Lazy per-host baseline-404 probe for the soft_404_probe check."""
    if not state.config.soft404_probe_enabled:
        return
    host = host_of(url)
    if not host or host in state.probed_hosts:
        return
    if not state.scope.is_internal(url):
        return  # probe only domains we'll crawl
    lock = state.probe_locks.setdefault(host, asyncio.Lock())
    async with lock:
        if host in state.probed_hosts:
            return
        state.probed_hosts.add(host)
        parts = urlsplit(url)
        probe_path = f"/__fbl_probe_{secrets.token_hex(8)}__"
        probe_url = f"{parts.scheme}://{parts.netloc}{probe_path}"
        try:
            probe = await state.fetcher.fetch(probe_url)
        except Exception:  # noqa: BLE001
            return
        if probe.body:
            state.ctx.baselines[host] = baseline_from_fetch(probe)


async def _seed_from_sitemap(
    client: httpx.AsyncClient, seed: str, state: _CrawlState, user_agent: str
) -> None:
    parts = urlsplit(seed)
    sitemap_url = f"{parts.scheme}://{parts.netloc}/sitemap.xml"
    try:
        resp = await client.get(sitemap_url, headers={"User-Agent": user_agent})
    except httpx.HTTPError:
        return
    if resp.status_code != 200:
        return
    try:
        urls = _parse_sitemap(resp.text)
    except Exception:
        return
    for u in urls:
        norm = normalize_url(u)
        if state.scope.is_internal(norm):
            await state.enqueue(norm, extract=True)


def _parse_sitemap(xml: str) -> Iterable[str]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    # Handle both <urlset> and <sitemapindex>.
    for loc in root.findall(f".//{ns}loc"):
        if loc.text:
            yield loc.text.strip()


def _build_findings(state: _CrawlState, ctx: CheckContext) -> list[Finding]:
    checks = active_checks(ctx)
    findings: list[Finding] = []
    for link in state.links:
        target = normalize_url(link.url)
        fetch = state.fetched.get(target)
        if fetch is None:
            continue
        issues = []
        for check in checks:
            issue = check.evaluate(link, fetch, ctx)
            if issue is not None:
                issues.append(issue)
        if issues:
            findings.append(Finding(link=link, fetch=fetch, issues=issues))
    return findings
