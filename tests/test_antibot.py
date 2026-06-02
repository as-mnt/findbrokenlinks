"""ANTIBOT_BLOCKED — detects anti-bot WAF responses so they don't look like 404s."""

from __future__ import annotations

from findbrokenlinks.checks.antibot import AntibotBlockedCheck
from findbrokenlinks.checks.base import CheckContext
from findbrokenlinks.config import Config
from findbrokenlinks.models import FetchResult, LinkRef


def _ctx() -> CheckContext:
    return CheckContext(config=Config(start_url="https://x/"), base_host="x")


def _link(url: str = "https://x/y") -> LinkRef:
    return LinkRef(url=url, source_page="https://x/", anchor=None, tag="a")


def _fetch(status: int | None, body: str | None = None, **headers) -> FetchResult:
    return FetchResult(
        url="https://x/y",
        final_url="https://x/y",
        status=status,
        redirect_chain=["https://x/y"],
        headers=headers,
        body=body,
        elapsed_ms=1.0,
        error=None,
    )


# ----- positive cases (block detected) ----- #

def test_tass_style_body_text_triggers():
    """Real-world: tass.ru returns 403 with this body via PerimeterX."""
    body = (
        "<!DOCTYPE html><html><head></head><body>"
        "<h1>Forbidden</h1>"
        "<p>If you are not a bot, please copy the report and send it to our support team.</p>"
        "</body></html>"
    )
    fetch = _fetch(status=403, body=body)
    issue = AntibotBlockedCheck().evaluate(_link(), fetch, _ctx())
    assert issue is not None and issue.code == "ANTIBOT_BLOCKED"
    assert issue.severity == "warning"  # not error — block is informational
    assert issue.details["vendor"] == "generic"


def test_perimeterx_header_triggers():
    """x-sp-crid is PerimeterX's correlation id, set on blocked responses."""
    fetch = _fetch(status=403, body="anything", **{"x-sp-crid": "29605877962:1"})
    issue = AntibotBlockedCheck().evaluate(_link(), fetch, _ctx())
    assert issue is not None and issue.details["vendor"] == "perimeterx"


def test_datadome_header_triggers():
    fetch = _fetch(status=403, body="anything", **{"x-datadome-cid": "abc123"})
    issue = AntibotBlockedCheck().evaluate(_link(), fetch, _ctx())
    assert issue is not None and issue.details["vendor"] == "datadome"


def test_cloudflare_interstitial_body_triggers():
    body = (
        "<html><head><title>Just a moment...</title></head><body>"
        "<h1>Checking your browser before accessing the site.</h1>"
        "</body></html>"
    )
    fetch = _fetch(status=503, body=body)
    issue = AntibotBlockedCheck().evaluate(_link(), fetch, _ctx())
    assert issue is not None and issue.details["vendor"] == "cloudflare"


def test_imperva_body_triggers():
    body = "<html><body>Incident ID: 12345-67890</body></html>"
    fetch = _fetch(status=403, body=body)
    issue = AntibotBlockedCheck().evaluate(_link(), fetch, _ctx())
    assert issue is not None and issue.details["vendor"] == "imperva"


# ----- negative cases (must not falsely fire) ----- #

def test_plain_404_does_not_trigger():
    fetch = _fetch(status=404, body="<html><body>Page not found</body></html>")
    assert AntibotBlockedCheck().evaluate(_link(), fetch, _ctx()) is None


def test_500_with_unrelated_body_does_not_trigger():
    fetch = _fetch(status=500, body="<html>Internal Server Error</html>")
    assert AntibotBlockedCheck().evaluate(_link(), fetch, _ctx()) is None


def test_200_page_mentioning_bots_does_not_trigger():
    """Status gate prevents false positives on legitimate 200 content."""
    body = (
        "<html><body>"
        "<h1>Our robots.txt policy</h1>"
        "<p>If you are not a bot, you may ignore this page. "
        "Otherwise please complete the captcha — bot detected!</p>"
        "</body></html>"
    )
    fetch = _fetch(status=200, body=body)
    assert AntibotBlockedCheck().evaluate(_link(), fetch, _ctx()) is None


def test_network_error_does_not_trigger():
    fetch = FetchResult(
        url="https://x/y", final_url="https://x/y", status=None,
        redirect_chain=["https://x/y"], headers={}, body=None,
        elapsed_ms=1.0, error="timeout",
    )
    assert AntibotBlockedCheck().evaluate(_link(), fetch, _ctx()) is None


def test_403_without_any_signature_does_not_trigger():
    """Plain 403 from a misconfigured /admin route shouldn't be tagged anti-bot."""
    fetch = _fetch(status=403, body="<h1>Forbidden</h1>")
    assert AntibotBlockedCheck().evaluate(_link(), fetch, _ctx()) is None


# ----- registry / plugin behavior ----- #

def test_check_is_autodiscovered():
    """Drop-in plugin model: ANTIBOT_BLOCKED appears without __init__.py edits."""
    from findbrokenlinks.checks import REGISTRY

    assert "ANTIBOT_BLOCKED" in REGISTRY
