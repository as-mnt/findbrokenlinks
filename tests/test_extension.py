"""Verify that adding a new check just requires `@register` — no core edits."""

from __future__ import annotations

from findbrokenlinks.checks.base import REGISTRY, Check, CheckContext, register
from findbrokenlinks.config import Config
from findbrokenlinks.models import FetchResult, Issue, LinkRef


def test_can_register_custom_check_and_use_it(monkeypatch):
    # Use monkeypatch to avoid leaking the test class into other tests' registry.
    saved = dict(REGISTRY)
    try:
        @register
        class SlowResponseCheck(Check):
            code = "SLOW_RESPONSE"
            severity = "info"

            def evaluate(self, link, fetch, ctx):
                if fetch.elapsed_ms > 1000:
                    return Issue(self.code, self.severity, "slow", {"ms": fetch.elapsed_ms})
                return None

        assert "SLOW_RESPONSE" in REGISTRY

        link = LinkRef(url="https://x/", source_page="https://x/", anchor=None, tag="a")
        fetch = FetchResult(
            url="https://x/",
            final_url="https://x/",
            status=200,
            redirect_chain=["https://x/"],
            headers={},
            body=None,
            elapsed_ms=2500.0,
        )
        ctx = CheckContext(config=Config(start_url="https://x/"), base_host="x")
        issue = SlowResponseCheck().evaluate(link, fetch, ctx)
        assert issue and issue.code == "SLOW_RESPONSE"
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)
