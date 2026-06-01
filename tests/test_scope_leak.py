"""Regression: a redirect from internal → external must not leak extraction.

In internal mode, the crawler must not parse the response body when the final URL
landed on a foreign host. Otherwise:
  - findings get attributed to a foreign source_page,
  - pending_links accumulates dead entries,
  - we end up scanning third-party content the user did not ask about.
"""

from __future__ import annotations

import pytest

from findbrokenlinks.config import Config
from findbrokenlinks.crawler import crawl
from findbrokenlinks.extractors import html as html_ext


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["internal", "internal+external"])
async def test_extract_skipped_when_final_url_is_external(live_server, monkeypatch, mode):
    """The extractor must not be invoked with a source_page outside the seed domain."""
    captured_sources: list[str] = []
    original_extract = html_ext.HTMLExtractor.extract

    def recording_extract(self, body, source_page):
        captured_sources.append(source_page)
        return original_extract(self, body, source_page)

    monkeypatch.setattr(html_ext.HTMLExtractor, "extract", recording_extract)

    config = Config(
        start_url=live_server + "/external-bait",
        mode=mode,
        rate_limit_rps=0,
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
        soft404_probe_enabled=False,
    )
    await crawl(config)

    # The seed itself (127.0.0.1) redirects to localhost (treated as foreign by scope).
    # No extract() call should have a localhost source_page.
    for source in captured_sources:
        assert "localhost" not in source, (
            f"extracted from foreign content in {mode} mode: sources={captured_sources}"
        )


@pytest.mark.asyncio
async def test_page_mode_still_extracts_after_external_redirect(live_server, monkeypatch):
    """In page mode the seed is the user's chosen target — follow the redirect and extract."""
    captured_sources: list[str] = []
    original_extract = html_ext.HTMLExtractor.extract

    def recording_extract(self, body, source_page):
        captured_sources.append(source_page)
        return original_extract(self, body, source_page)

    monkeypatch.setattr(html_ext.HTMLExtractor, "extract", recording_extract)

    config = Config(
        start_url=live_server + "/external-bait",
        mode="page",
        rate_limit_rps=0,
        concurrency=2,
        ignore_robots=True,
        timeout_s=5.0,
        soft404_probe_enabled=False,
    )
    await crawl(config)

    # Page mode: the seed redirected to localhost/external-content — that destination
    # is the "page" the user pointed at, so extraction is expected.
    assert any("localhost" in s and "external-content" in s for s in captured_sources), (
        captured_sources
    )
