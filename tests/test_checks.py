from __future__ import annotations

from findbrokenlinks.checks.base import CheckContext
from findbrokenlinks.checks.http_status import HttpStatusCheck
from findbrokenlinks.checks.network_error import NetworkErrorCheck
from findbrokenlinks.checks.redirect_chain import RedirectChainCheck
from findbrokenlinks.checks.redirect_to_home import RedirectToHomeCheck
from findbrokenlinks.checks.soft_404_pattern import Soft404PatternCheck, load_patterns
from findbrokenlinks.checks.soft_404_probe import Soft404ProbeCheck, baseline_from_fetch
from findbrokenlinks.config import Config
from findbrokenlinks.models import FetchResult, LinkRef


def _ctx(**overrides) -> CheckContext:
    config = Config(start_url="https://example.com/")
    ctx = CheckContext(config=config, base_host="example.com")
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


def _link(url="https://example.com/x") -> LinkRef:
    return LinkRef(url=url, source_page="https://example.com/", anchor="x", tag="a")


def _fetch(**kw) -> FetchResult:
    defaults = dict(
        url="https://example.com/x",
        final_url="https://example.com/x",
        status=200,
        redirect_chain=["https://example.com/x"],
        headers={},
        body=None,
        elapsed_ms=10.0,
        error=None,
    )
    defaults.update(kw)
    return FetchResult(**defaults)


# ----- HttpStatusCheck ----- #

def test_http_status_404_triggers():
    issue = HttpStatusCheck().evaluate(_link(), _fetch(status=404), _ctx())
    assert issue and issue.code == "HTTP_ERROR"


def test_http_status_200_clean():
    assert HttpStatusCheck().evaluate(_link(), _fetch(status=200), _ctx()) is None


def test_http_status_ignores_network_error():
    assert HttpStatusCheck().evaluate(_link(), _fetch(status=None, error="dns"), _ctx()) is None


# ----- NetworkErrorCheck ----- #

def test_network_error_triggers():
    issue = NetworkErrorCheck().evaluate(_link(), _fetch(status=None, error="timeout"), _ctx())
    assert issue and issue.code == "NETWORK_ERROR"


def test_network_error_no_error():
    assert NetworkErrorCheck().evaluate(_link(), _fetch(status=200), _ctx()) is None


# ----- RedirectToHome ----- #

def test_redirect_to_home_triggers():
    f = _fetch(
        url="https://example.com/deep/page",
        final_url="https://example.com/",
        redirect_chain=["https://example.com/deep/page", "https://example.com/"],
    )
    issue = RedirectToHomeCheck().evaluate(_link("https://example.com/deep/page"), f, _ctx())
    assert issue and issue.code == "REDIRECT_TO_HOME"


def test_redirect_to_home_ignores_no_redirect():
    f = _fetch(final_url="https://example.com/x", redirect_chain=["https://example.com/x"])
    assert RedirectToHomeCheck().evaluate(_link(), f, _ctx()) is None


def test_redirect_to_home_ignores_seed_to_home():
    # Original link is already root → not interesting.
    f = _fetch(
        url="https://example.com/",
        final_url="https://example.com/",
        redirect_chain=["https://example.com", "https://example.com/"],
    )
    assert RedirectToHomeCheck().evaluate(_link("https://example.com/"), f, _ctx()) is None


# ----- RedirectChain ----- #

def test_redirect_chain_threshold():
    chain = [f"https://example.com/r{i}" for i in range(5)]  # 4 hops
    f = _fetch(redirect_chain=chain, final_url=chain[-1])
    ctx = _ctx()
    ctx.config.redirect_chain_threshold = 3
    issue = RedirectChainCheck().evaluate(_link(), f, ctx)
    assert issue and issue.details["hops"] == 4


def test_redirect_chain_below_threshold():
    f = _fetch(redirect_chain=["a", "b"], final_url="b")
    ctx = _ctx()
    ctx.config.redirect_chain_threshold = 3
    assert RedirectChainCheck().evaluate(_link(), f, ctx) is None


# ----- Soft404Pattern ----- #

def test_soft404_pattern_matches_title():
    patterns = load_patterns()
    ctx = _ctx(soft404_patterns=patterns)
    f = _fetch(
        status=200,
        body="<html><title>Страница не найдена</title><body><h1>x</h1></body></html>",
    )
    issue = Soft404PatternCheck().evaluate(_link(), f, ctx)
    assert issue and issue.code == "SOFT_404_PATTERN"


def test_soft404_pattern_no_match():
    patterns = load_patterns()
    ctx = _ctx(soft404_patterns=patterns)
    f = _fetch(status=200, body="<html><title>Welcome</title><h1>Hello</h1></html>")
    assert Soft404PatternCheck().evaluate(_link(), f, ctx) is None


def test_soft404_pattern_skips_4xx():
    patterns = load_patterns()
    ctx = _ctx(soft404_patterns=patterns)
    f = _fetch(status=404, body="<html><title>Страница не найдена</title></html>")
    # HTTP status check handles 4xx — pattern check stays quiet so we don't double-report.
    assert Soft404PatternCheck().evaluate(_link(), f, ctx) is None


# ----- Soft404Probe ----- #

def test_soft404_probe_matches_baseline_body():
    body = "<html><body><p>This is a generic not-found page</p></body></html>"
    baseline_fetch = _fetch(url="https://example.com/__probe__", body=body, status=404)
    baseline = baseline_from_fetch(baseline_fetch)
    ctx = _ctx(baselines={"example.com": baseline})
    target = _fetch(
        url="https://example.com/foo",
        final_url="https://example.com/foo",
        body=body,
        status=200,
    )
    issue = Soft404ProbeCheck().evaluate(_link(), target, ctx)
    assert issue and issue.code == "SOFT_404_PROBE"


def test_soft404_probe_no_match_distinct_body():
    baseline_fetch = _fetch(
        url="https://example.com/__probe__",
        body="generic not found page",
        status=404,
    )
    baseline = baseline_from_fetch(baseline_fetch)
    ctx = _ctx(baselines={"example.com": baseline})
    target = _fetch(body="<html><body>Real content here, plenty of it</body></html>")
    assert Soft404ProbeCheck().evaluate(_link(), target, ctx) is None
