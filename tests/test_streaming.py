"""Streaming: findings appear via callback during crawl; JSONL reporter; CLI parity."""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from findbrokenlinks.config import Config
from findbrokenlinks.crawler import crawl
from findbrokenlinks.models import FetchResult, Finding, Issue, LinkRef
from findbrokenlinks.reporters.base import get_reporter


@pytest.mark.asyncio
async def test_crawler_invokes_on_finding_callback(live_server):
    captured: list[Finding] = []
    config = Config(
        start_url=live_server + "/",
        mode="internal",
        rate_limit_rps=0,
        concurrency=4,
        ignore_robots=True,
        timeout_s=5.0,
    )
    findings = await crawl(config, on_finding=captured.append)
    # The callback should have received the same findings as the return value.
    assert findings == captured
    assert any("HTTP_ERROR" in (i.code for i in f.issues) for f in captured)


def _sample_finding() -> Finding:
    link = LinkRef(
        url="https://example.com/x",
        source_page="https://example.com/",
        anchor="x",
        tag="a",
    )
    fetch = FetchResult(
        url=link.url, final_url=link.url, status=404,
        redirect_chain=[link.url], headers={}, body=None,
        elapsed_ms=1.0, error=None,
    )
    return Finding(link=link, fetch=fetch, issues=[
        Issue(code="HTTP_ERROR", severity="error", message="HTTP 404", details={"status": 404})
    ])


def test_jsonl_reporter_one_line_per_finding():
    rep = get_reporter("jsonl")
    out = rep.render([_sample_finding(), _sample_finding()])
    lines = out.strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert obj["link_url"] == "https://example.com/x"
        assert obj["issues"][0]["code"] == "HTTP_ERROR"


def test_csv_stream_matches_batch_render():
    rep = get_reporter("csv")
    findings = [_sample_finding(), _sample_finding()]
    batch = rep.render(findings)
    buf = io.StringIO(newline="")
    rep.stream_start(buf)
    for f in findings:
        rep.stream_append(f, buf)
    rep.stream_finish(buf)
    assert buf.getvalue() == batch


def test_cli_streams_csv_to_file(live_server, tmp_path):
    """End-to-end: CLI with --format csv -o <file> writes the same output as batch mode."""
    out_file = tmp_path / "stream.csv"
    proc = subprocess.run(
        [
            sys.executable, "-m", "findbrokenlinks",
            live_server + "/",
            "--mode", "internal",
            "--ignore-robots",
            "--rate-limit", "0",
            "--format", "csv",
            "-o", str(out_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    # Header must be the first line, even if crawl was killed early.
    assert content.splitlines()[0].startswith("source_page,link_url,")
    # Expected broken-link rows appear.
    assert "/missing" in content
    assert "HTTP_ERROR" in content
    # Exit code is 1 because there are error-level findings (/missing returns 404).
    assert proc.returncode == 1
