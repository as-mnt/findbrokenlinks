from __future__ import annotations

import json

from findbrokenlinks.models import FetchResult, Finding, Issue, LinkRef
from findbrokenlinks.reporters.base import REGISTRY, get_reporter


def _sample_findings() -> list[Finding]:
    link = LinkRef(
        url="https://example.com/missing",
        source_page="https://example.com/",
        anchor="missing",
        tag="a",
    )
    fetch = FetchResult(
        url=link.url,
        final_url=link.url,
        status=404,
        redirect_chain=[link.url],
        headers={},
        body=None,
        elapsed_ms=12.0,
        error=None,
    )
    issue = Issue(code="HTTP_ERROR", severity="error", message="HTTP 404", details={"status": 404})
    return [Finding(link=link, fetch=fetch, issues=[issue])]


def test_all_reporters_render_without_error():
    findings = _sample_findings()
    for name in REGISTRY:
        out = get_reporter(name).render(findings)
        assert isinstance(out, str)
        assert out  # non-empty


def test_csv_has_header_and_row():
    out = get_reporter("csv").render(_sample_findings())
    assert "source_page,link_url" in out.splitlines()[0]
    assert "https://example.com/missing" in out
    assert "HTTP_ERROR" in out


def test_json_structure():
    payload = json.loads(get_reporter("json").render(_sample_findings()))
    assert payload["summary"]["total"] == 1
    assert payload["findings"][0]["issues"][0]["code"] == "HTTP_ERROR"


def test_html_contains_link():
    out = get_reporter("html").render(_sample_findings())
    assert "<html" in out
    assert "https://example.com/missing" in out


def test_junit_contains_failure():
    out = get_reporter("junit").render(_sample_findings())
    assert "<testsuites" in out
    assert "<failure" in out


def test_sarif_top_level():
    payload = json.loads(get_reporter("sarif").render(_sample_findings()))
    assert payload["version"] == "2.1.0"
    assert payload["runs"][0]["results"][0]["ruleId"] == "HTTP_ERROR"


def test_unknown_format_raises():
    import pytest

    with pytest.raises(KeyError):
        get_reporter("nope")
