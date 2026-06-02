"""grouped-json reporter — aggregates findings by final_url.

The aggregation must preserve diversity within a group: different request
URLs (`http://x` vs `https://x`) can hit the same final URL with different
statuses, redirect chains and check outcomes. Taking only group[0] loses
that — every assertion below pins the union/max/distribution behaviour.
"""

from __future__ import annotations

import json

from findbrokenlinks.models import FetchResult, Finding, Issue, LinkRef
from findbrokenlinks.reporters.base import get_reporter


def _make_finding(
    source: str,
    link: str,
    final: str,
    *,
    status: int | None = 404,
    issues: list[Issue] | None = None,
    redirect_chain: list[str] | None = None,
    error: str | None = None,
    content_type: str | None = None,
) -> Finding:
    if issues is None:
        issues = [Issue(code="HTTP_ERROR", severity="error", message="HTTP 404",
                        details={})]
    if redirect_chain is None:
        redirect_chain = [link, final] if link != final else [link]
    return Finding(
        link=LinkRef(url=link, source_page=source, anchor=None, tag="a"),
        fetch=FetchResult(
            url=link, final_url=final, status=status,
            redirect_chain=redirect_chain, headers={}, body=None,
            elapsed_ms=1.0, error=error, content_type=content_type,
        ),
        issues=issues,
    )


def test_collapses_same_final_url_into_one_group():
    findings = [
        _make_finding(f"https://site/page{i}", "https://site/broken", "https://site/broken")
        for i in range(3)
    ]
    payload = json.loads(get_reporter("grouped-json").render(findings))

    assert payload["summary"]["raw_findings"] == 3
    assert payload["summary"]["unique_final_urls"] == 1
    assert payload["summary"]["by_severity"] == {"error": 1, "warning": 0, "info": 0}

    g = payload["groups"][0]
    assert g["final_url"] == "https://site/broken"
    assert g["occurrences"] == 3
    assert g["distinct_source_pages"] == 3
    assert g["statuses"] == {"404": 3}
    assert g["severity"] == "error"
    assert g["issue_codes"] == ["HTTP_ERROR"]


def test_distinct_statuses_aggregated_into_distribution():
    """Two request URLs land on the same final URL with different statuses."""
    findings = [
        _make_finding("https://site/p1", "http://x", "https://x/", status=200,
                      issues=[Issue("REDIRECT_TO_HOME", "warning", "redirect", {})]),
        _make_finding("https://site/p2", "http://x/", "https://x/", status=200,
                      issues=[Issue("REDIRECT_TO_HOME", "warning", "redirect", {})]),
        _make_finding("https://site/p3", "https://x", "https://x/", status=502,
                      issues=[Issue("HTTP_ERROR", "error", "HTTP 502", {})]),
    ]
    payload = json.loads(get_reporter("grouped-json").render(findings))
    g = payload["groups"][0]
    assert g["statuses"] == {"200": 2, "502": 1}
    # union of issue codes across the whole group, sorted
    assert g["issue_codes"] == ["HTTP_ERROR", "REDIRECT_TO_HOME"]


def test_severity_is_worst_across_group():
    findings = [
        _make_finding("https://site/p1", "https://x", "https://x",
                      issues=[Issue("REDIRECT_TO_HOME", "warning", "x", {})]),
        _make_finding("https://site/p2", "https://x", "https://x",
                      issues=[Issue("REDIRECT_TO_HOME", "warning", "x", {})]),
        # one error among the warnings — group severity must escalate to error
        _make_finding("https://site/p3", "https://x", "https://x",
                      issues=[Issue("HTTP_ERROR", "error", "HTTP 500", {})]),
    ]
    g = json.loads(get_reporter("grouped-json").render(findings))["groups"][0]
    assert g["severity"] == "error"
    assert g["severity_distribution"] == {"error": 1, "warning": 2, "info": 0}


def test_max_redirect_chain_length_is_taken():
    findings = [
        _make_finding("https://site/a", "http://x", "https://x/",
                      redirect_chain=["http://x", "https://x/"]),  # 1 hop
        _make_finding(
            "https://site/b", "http://x/", "https://x/",
            redirect_chain=["http://x/", "http://x", "https://x", "https://x/"],
        ),  # 3 hops
    ]
    g = json.loads(get_reporter("grouped-json").render(findings))["groups"][0]
    assert g["max_redirect_chain_length"] == 3


def test_distinct_errors_and_content_types_collected():
    findings = [
        _make_finding("https://site/p1", "https://x", "https://x",
                      status=None, error="timeout"),
        _make_finding("https://site/p2", "https://x", "https://x",
                      status=None, error="ssl"),
        _make_finding("https://site/p3", "https://x", "https://x",
                      status=200, content_type="text/html"),
    ]
    g = json.loads(get_reporter("grouped-json").render(findings))["groups"][0]
    assert g["errors"] == ["ssl", "timeout"]
    assert g["content_types"] == ["text/html"]
    # status None is preserved as the literal string "null" key
    assert g["statuses"]["null"] == 2
    assert g["statuses"]["200"] == 1


def test_distinct_link_urls_are_counted_per_group():
    findings = [
        _make_finding("https://site/p1", "http://x", "https://x/"),
        _make_finding("https://site/p2", "http://x/", "https://x/"),
        _make_finding("https://site/p3", "https://x", "https://x/"),
    ]
    g = json.loads(get_reporter("grouped-json").render(findings))["groups"][0]
    assert g["distinct_link_urls"] == 3
    assert set(g["link_urls_sample"]) == {"http://x", "http://x/", "https://x"}


def test_groups_sorted_by_occurrences_desc():
    big = [
        _make_finding(f"https://site/page{i}", "https://site/big", "https://site/big")
        for i in range(5)
    ]
    small = [_make_finding("https://site/only", "https://site/small", "https://site/small")]
    payload = json.loads(get_reporter("grouped-json").render(big + small))
    occs = [g["occurrences"] for g in payload["groups"]]
    assert occs == sorted(occs, reverse=True)


def test_source_pages_sample_truncated_to_five():
    findings = [
        _make_finding(f"https://site/page{i}", "https://site/bad", "https://site/bad")
        for i in range(20)
    ]
    g = json.loads(get_reporter("grouped-json").render(findings))["groups"][0]
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
    from findbrokenlinks.reporters import REGISTRY

    assert "grouped-json" in REGISTRY
