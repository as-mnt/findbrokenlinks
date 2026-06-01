from findbrokenlinks.scope import Scope, normalize_url


def test_normalize_drops_fragment_and_default_port():
    assert normalize_url("HTTP://Example.com:80/A?b=2&a=1#frag") == "http://example.com/A?a=1&b=2"


def test_normalize_adds_root_path():
    assert normalize_url("https://example.com") == "https://example.com/"


def test_scope_internal_mode():
    s = Scope("https://example.com/", "internal")
    assert s.should_fetch("https://example.com/page")
    assert not s.should_fetch("https://other.com/page")
    assert s.should_recurse("https://example.com/page")
    assert not s.should_recurse("https://other.com/page")


def test_scope_internal_plus_external():
    s = Scope("https://example.com/", "internal+external")
    assert s.should_fetch("https://other.com/")
    assert not s.should_recurse("https://other.com/")  # external → no recursion


def test_scope_page_mode():
    s = Scope("https://example.com/", "page")
    assert s.should_fetch("https://other.com/")
    assert not s.should_recurse("https://example.com/x")


def test_subdomain_is_internal():
    s = Scope("https://example.com/", "internal")
    assert s.is_internal("https://api.example.com/x")
