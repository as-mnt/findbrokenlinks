"""Output path template substitution.

`-o` and `--output-dir` accept `{host}`, `{date}`, `{time}`, `{ts}`,
`{format}`, `{ext}` placeholders. Multi-format with no destination flag
falls back to `reports/{host}_{date}_{time}/` so runs don't clobber each
other and the file name itself records *what* was scanned and *when*.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from findbrokenlinks.cli import (
    _expand_template,
    _host_from_url,
    _resolve_output_paths,
)
from findbrokenlinks.config import Config

_FROZEN = datetime(2026, 6, 2, 22, 30, 45)


# ---- _host_from_url ----

def test_host_from_url_lowercases():
    assert _host_from_url("https://Example.COM/path") == "example.com"


def test_host_from_url_falls_back_for_unparseable():
    assert _host_from_url("not-a-url") == "host"


# ---- _expand_template ----

def test_expand_substitutes_all_placeholders():
    out = _expand_template(
        "reports/{host}_{date}_{time}_{ts}/{format}.{ext}",
        host="example.com", fmt="csv", ext="csv", start=_FROZEN,
    )
    assert out == f"reports/example.com_2026-06-02_223045_{int(_FROZEN.timestamp())}/csv.csv"


def test_expand_returns_literal_when_no_placeholders():
    """A plain path passes through unchanged — no surprise rewriting."""
    out = _expand_template("reports/manual.csv", host="x", start=_FROZEN)
    assert out == "reports/manual.csv"


def test_expand_unknown_placeholder_raises_systemexit():
    with pytest.raises(SystemExit, match="unknown placeholder"):
        _expand_template("reports/{user}.csv", host="x", start=_FROZEN)


def test_expand_format_and_ext_are_empty_string_when_not_supplied():
    """Without fmt/ext the keys still resolve so directory templates work."""
    out = _expand_template("dir/{host}/{format}/", host="x", start=_FROZEN)
    assert out == "dir/x//"


# ---- _resolve_output_paths defaults ----

def _make_config(*, formats=None, output_path=None, output_dir=None) -> Config:
    return Config(
        start_url="https://example.com/",
        formats=formats or ["tsv"],
        output_path=output_path,
        output_dir=output_dir,
    )


def test_multi_format_with_no_output_uses_default_dir_template():
    cfg = _make_config(formats=["csv", "json"])
    _resolve_output_paths(cfg, "https://example.com/")
    assert cfg.output_dir is not None
    s = str(cfg.output_dir)
    assert s.startswith("reports/example.com_")
    # No unexpanded braces.
    assert "{" not in s


def test_single_format_no_output_leaves_stdout():
    """A bare single-format run must still go to stdout, not auto-create files."""
    cfg = _make_config(formats=["tsv"])
    _resolve_output_paths(cfg, "https://example.com/")
    assert cfg.output_path is None
    assert cfg.output_dir is None


def test_output_path_template_expanded():
    cfg = _make_config(formats=["json"], output_path=Path("logs/{host}.{ext}"))
    _resolve_output_paths(cfg, "https://example.com/")
    assert cfg.output_path == Path("logs/example.com.json")


def test_output_dir_template_expanded():
    cfg = _make_config(formats=["csv", "json"], output_dir=Path("out/{host}/"))
    _resolve_output_paths(cfg, "https://example.com/")
    assert cfg.output_dir == Path("out/example.com/")


def test_output_path_without_template_kept_as_literal():
    cfg = _make_config(formats=["tsv"], output_path=Path("out.tsv"))
    _resolve_output_paths(cfg, "https://example.com/")
    assert cfg.output_path == Path("out.tsv")


def test_explicit_output_dir_disables_default():
    """User's --output-dir always wins over the default template."""
    cfg = _make_config(formats=["csv", "json"], output_dir=Path("custom/"))
    _resolve_output_paths(cfg, "https://example.com/")
    assert cfg.output_dir == Path("custom/")


# ---- end-to-end via subprocess ----

def test_cli_multiformat_default_dir_is_created(live_server, tmp_path):
    """Run findbrokenlinks with multi-format and no -o/--output-dir from a
    cwd inside tmp_path; the default reports/<host>_<date>_<time>/ tree must
    appear and contain one file per format."""
    subprocess.run(
        [
            sys.executable, "-m", "findbrokenlinks",
            live_server + "/",
            "--mode", "internal",
            "--ignore-robots",
            "--rate-limit", "0",
            "--format", "csv,json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    # exit code is data-dependent — what matters is that the default tree exists.
    reports = tmp_path / "reports"
    dirs = list(reports.iterdir())
    assert len(dirs) == 1, dirs
    auto = dirs[0]
    assert auto.name.startswith("127.0.0.1_")  # host comes from the fixture URL
    # Two distinct files — no collision.
    assert (auto / "csv.csv").exists()
    assert (auto / "json.json").exists()


def test_cli_output_path_template_writes_to_expected_file(live_server, tmp_path):
    out_template = tmp_path / "out_{host}.json"
    subprocess.run(
        [
            sys.executable, "-m", "findbrokenlinks",
            live_server + "/ok",
            "--mode", "page",
            "--ignore-robots",
            "--rate-limit", "0",
            "--format", "json",
            "-o", str(out_template),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    # We don't know the exact host (127.0.0.1) — discover the created file.
    matches = list(tmp_path.glob("out_*.json"))
    assert matches, list(tmp_path.iterdir())
    written = matches[0].read_text(encoding="utf-8")
    assert '"findings"' in written
