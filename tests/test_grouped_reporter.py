"""grouped-json reporter — aggregates findings by final_url."""

from __future__ import annotations

import json

from findbrokenlinks.models import FetchResult, Finding, Issue, LinkRef
from findbrokenlinks.reporters.base import get_reporter


def _make_finding(
    source: str,
    link: str,
    final: str,
    status: int = 404,
    code: str = "HTTP_ERROR",
    severity: str = "error",
) -> Finding:
    return Finding(
        link=LinkRef(url=link, source_page=source, anchor=None, tag="a"),
        fetch=FetchResult(
            url=link,
            final_url=final,
            status=status,
            redirect_chain=[link, final] if link != final else [link],
            headers={},
            body=None,
            elapsed_ms=1.0,
            error=None,
        ),
        issues=[Issue(code=code, severity=severity, message=f"{code} msg", details={})],
    )


def test_collapses_same_final_url_into_one_group():
    # Three findings all pointing at the same final URL from different sources.
    findings = [
        _make_finding(f"https://site/page{i}", "https://site/broken", "https://site/broken")
        for i in range(3)
    ]
    out = get_reporter("grouped-json").render(findings)
    payload = json.loads(out)

    assert payload["summary"]["raw_findings"] == 3
    assert payload["summary"]["unique_final_urls"] == 1
    assert payload["summary"]["reduction_percent"] == round((1 - 1 / 3) * 100, 1)
    assert payload["summary"]["by_severity"] == {"error": 1, "warning": 0, "info": 0}

    group = payload["groups"][0]
    assert group["final_url"] == "https://site/broken"
    assert group["occurrences"] == 3
    assert group["distinct_source_pages"] == 3
    assert group["distinct_link_urls"] == 1
    assert group["status"] == 404
    assert group["issue_codes"] == ["HTTP_ERROR"]


def test_distinct_link_urls_are_counted_per_group():
    """Different request URLs that redirect to the same final_url share a group."""
    findings = [
        _make_finding("https://site/p1", "http://x", "https://x/"),
        _make_finding("https://site/p2", "http://x/", "https://x/"),
        _make_finding("https://site/p3", "https://x", "https://x/"),
    ]
    payload = json.loads(get_reporter("grouped-json").render(findings))
    assert len(payload["groups"]) == 1
    g = payload["groups"][0]
    assert g["distinct_link_urls"] == 3
    assert set(g["link_urls_sample"]) == {"http://x", "http://x/", "https://x"}


def test_groups_sorted_by_occurrences_desc():
    big = [
        _make_finding(f"https://site/page{i}", "https://site/big", "https://site/big")
        for i in range(5)
    ]
    small = [
        _make_finding("https://site/only", "https://site/small", "https://site/small")
    ]
    payload = json.loads(get_reporter("grouped-json").render(big + small))
    occs = [g["occurrences"] for g in payload["groups"]]
    assert occs == sorted(occs, reverse=True)
    assert payload["groups"][0]["final_url"] == "https://site/big"


def test_source_pages_sample_truncated_to_five():
    findings = [
        _make_finding(f"https://site/page{i}", "https://site/bad", "https://site/bad")
        for i in range(20)
    ]
    payload = json.loads(get_reporter("grouped-json").render(findings))
    g = payload["groups"][0]
    assert g["occurrences"] == 20
    assert g["distinct_source_pages"] == 20
    assert len(g["source_pages_sample"]) == 5


def test_empty_findings_render():
    payload = json.loads(get_reporter("grouped-json").render([]))
    assert payload["summary"] == {
        "raw_findings": 0,
        "unique_final_urls": 0,
        "reduction_percent": 0.0,
        "by_severity": {"error": 0, "warning": 0, "info": 0},
    }
    assert payload["groups"] == []


def test_format_registered_and_discoverable():
    """No __init__.py edit was needed — auto-discovery picks up the new file."""
    from findbrokenlinks.reporters import REGISTRY

    assert "grouped-json" in REGISTRY
