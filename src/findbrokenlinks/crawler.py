from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

import httpx

from findbrokenlinks.checks import REGISTRY as CHECK_REGISTRY  # noqa: F401 — registry side effect
from findbrokenlinks.checks.base import Check, CheckContext, active_checks
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

FindingCallback = Callable[[Finding], None]


async def crawl(
    config: Config,
    on_finding: FindingCallback | None = None,
) -> list[Finding]:
    """Crawl the site and return all findings.

    If ``on_finding`` is provided, it is called for each finding as it is
    produced — enabling incremental report writing during the crawl.
    """
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
            max_body_bytes=config.max_body_bytes,
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
        state = _CrawlState(scope, robots, fetcher, ctx, config, on_finding)

        # Synthetic seed LinkRef so seed-page issues surface in findings.
        state.register_link(LinkRef(url=seed, source_page=seed, anchor=None, tag="seed"))

        await state.enqueue(seed, extract=True)

        if config.use_sitemap and config.mode != "page":
            await _seed_from_sitemap(client, seed, state, config.user_agent)

        workers = [
            asyncio.create_task(_worker(state)) for _ in range(max(1, config.concurrency))
        ]
        await state.queue.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        return state.findings


class _CrawlState:
    def __init__(
        self,
        scope: Scope,
        robots: RobotsCache | None,
        fetcher: Fetcher,
        ctx: CheckContext,
        config: Config,
        on_finding: FindingCallback | None,
    ) -> None:
        self.scope = scope
        self.robots = robots
        self.fetcher = fetcher
        self.ctx = ctx
        self.config = config
        self.on_finding = on_finding
        self.extractor = HTMLExtractor()
        self.checks: list[Check] = active_checks(ctx)

        self.queue: asyncio.Queue[tuple[str, bool, int]] = asyncio.Queue()
        self.enqueued: set[str] = set()
        self.fetched: dict[str, FetchResult] = {}
        self.extracted_from: set[str] = set()
        self.probed_hosts: set[str] = set()
        self.probe_locks: dict[str, asyncio.Lock] = {}

        # Links discovered but waiting for their target URL's fetch to complete.
        self.pending_links: dict[str, list[LinkRef]] = {}
        # Accumulated findings (also surfaced via on_finding as they're produced).
        self.findings: list[Finding] = []
        # Has the max_pages-reached message already been logged? Log it once.
        self._cap_logged = False

    async def enqueue(self, url: str, *, extract: bool, depth: int = 0) -> None:
        if url in self.enqueued:
            return
        if self.config.depth and depth > self.config.depth:
            return
        if self.config.max_pages and len(self.enqueued) >= self.config.max_pages:
            if not self._cap_logged:
                log.info(
                    "max_pages=%d reached — further URLs will be skipped",
                    self.config.max_pages,
                )
                self._cap_logged = True
            return
        self.enqueued.add(url)
        await self.queue.put((url, extract, depth))

    def register_link(self, link: LinkRef) -> None:
        """Index a LinkRef; if its target is already fetched, evaluate immediately."""
        target = normalize_url(link.url)
        fetch = self.fetched.get(target)
        if fetch is not None:
            self._evaluate(link, fetch)
        else:
            self.pending_links.setdefault(target, []).append(link)

    def register_fetch(self, url: str, fetch: FetchResult) -> None:
        """Cache the fetch and flush any pending links targeting it."""
        self.fetched[url] = fetch
        for link in self.pending_links.pop(url, []):
            self._evaluate(link, fetch)

    def _evaluate(self, link: LinkRef, fetch: FetchResult) -> None:
        issues = []
        for check in self.checks:
            issue = check.evaluate(link, fetch, self.ctx)
            if issue is not None:
                issues.append(issue)
        if not issues:
            return
        finding = Finding(link=link, fetch=fetch, issues=issues)
        self.findings.append(finding)
        if self.on_finding is not None:
            try:
                self.on_finding(finding)
            except Exception:  # noqa: BLE001 — callback must not break the crawl
                log.exception("on_finding callback failed for %s", link.url)


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
    state.register_fetch(url, fetch)

    if not extract or not fetch.body:
        return

    final_norm = normalize_url(fetch.final_url)
    if final_norm in state.extracted_from:
        return
    state.extracted_from.add(final_norm)
    source = fetch.final_url

    for link in state.extractor.extract(fetch.body, source_page=source):
        state.register_link(link)
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
        return
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
    for loc in root.findall(f".//{ns}loc"):
        if loc.text:
            yield loc.text.strip()
