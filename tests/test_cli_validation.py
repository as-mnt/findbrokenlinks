"""argparse-level validation of numeric CLI parameters.

Each invalid value must be rejected with SystemExit and a clear stderr message —
not silently coerced (e.g., `max(1, x)` in the crawler used to hide --concurrency 0).
"""

from __future__ import annotations

import pytest

from findbrokenlinks.cli import build_parser


def _expect_reject(argv: list[str], flag: str, capsys) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(argv)
    assert exc.value.code == 2  # argparse error exit
    err = capsys.readouterr().err
    assert flag in err, err


# ---- > 0 (strictly positive) ----

@pytest.mark.parametrize("bad", ["0", "-1", "-0.5"])
def test_timeout_rejects_zero_and_negative(bad, capsys):
    _expect_reject(["http://x/", "--timeout", bad], "--timeout", capsys)


@pytest.mark.parametrize("bad", ["0", "-3"])
def test_concurrency_rejects_zero_and_negative(bad, capsys):
    _expect_reject(["http://x/", "--concurrency", bad], "--concurrency", capsys)


@pytest.mark.parametrize("bad", ["0", "-100"])
def test_max_body_bytes_rejects_zero_and_negative(bad, capsys):
    _expect_reject(["http://x/", "--max-body-bytes", bad], "--max-body-bytes", capsys)


def test_redirect_chain_threshold_rejects_zero(capsys):
    _expect_reject(
        ["http://x/", "--redirect-chain-threshold", "0"],
        "--redirect-chain-threshold",
        capsys,
    )


# ---- >= 0 (non-negative; 0 is documented as unlimited) ----

def test_depth_rejects_negative(capsys):
    _expect_reject(["http://x/", "--depth", "-1"], "--depth", capsys)


def test_depth_accepts_zero():
    args = build_parser().parse_args(["http://x/", "--depth", "0"])
    assert args.depth == 0


def test_max_pages_rejects_negative(capsys):
    _expect_reject(["http://x/", "--max-pages", "-5"], "--max-pages", capsys)


def test_max_pages_accepts_zero():
    args = build_parser().parse_args(["http://x/", "--max-pages", "0"])
    assert args.max_pages == 0


def test_rate_limit_rejects_negative(capsys):
    _expect_reject(["http://x/", "--rate-limit", "-0.1"], "--rate-limit", capsys)


def test_rate_limit_accepts_zero_unlimited():
    args = build_parser().parse_args(["http://x/", "--rate-limit", "0"])
    assert args.rate_limit_rps == 0


def test_max_redirects_rejects_negative(capsys):
    _expect_reject(["http://x/", "--max-redirects", "-1"], "--max-redirects", capsys)


def test_max_redirects_accepts_zero():
    args = build_parser().parse_args(["http://x/", "--max-redirects", "0"])
    assert args.max_redirects == 0


# ---- non-numeric input ----

def test_concurrency_rejects_non_integer(capsys):
    _expect_reject(["http://x/", "--concurrency", "lots"], "--concurrency", capsys)


def test_timeout_rejects_non_number(capsys):
    _expect_reject(["http://x/", "--timeout", "soon"], "--timeout", capsys)


# ---- happy path ----

def test_valid_values_parse_cleanly():
    args = build_parser().parse_args(
        [
            "http://x/",
            "--timeout", "5",
            "--concurrency", "4",
            "--max-body-bytes", "131072",
            "--depth", "3",
            "--max-pages", "100",
            "--rate-limit", "2.5",
            "--max-redirects", "5",
            "--redirect-chain-threshold", "2",
        ]
    )
    assert args.timeout_s == 5.0
    assert args.concurrency == 4
    assert args.max_body_bytes == 131072
    assert args.depth == 3
    assert args.max_pages == 100
    assert args.rate_limit_rps == 2.5
    assert args.max_redirects == 5
    assert args.redirect_chain_threshold == 2
