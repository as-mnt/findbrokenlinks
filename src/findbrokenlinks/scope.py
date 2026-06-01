from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from findbrokenlinks.config import ScopeMode

SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "ftp", "file"}


def normalize_url(url: str) -> str:
    """Canonical form for dedup: lowercase scheme/host, drop fragment, sort query."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # Strip default ports.
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    path = parts.path or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url: str) -> str:
    return urlsplit(url).hostname or ""


def is_http(url: str) -> bool:
    return urlsplit(url).scheme.lower() in ("http", "https")


def is_skipped_scheme(url: str) -> bool:
    return urlsplit(url).scheme.lower() in SKIP_SCHEMES


class Scope:
    """Decides whether to enqueue (recurse) or just fetch a URL."""

    def __init__(self, base_url: str, mode: ScopeMode) -> None:
        self.base_host = host_of(base_url)
        self.mode = mode

    def is_internal(self, url: str) -> bool:
        h = host_of(url)
        if not h or not self.base_host:
            return False
        # Match exact host or subdomain.
        return h == self.base_host or h.endswith("." + self.base_host)

    def should_fetch(self, url: str) -> bool:
        """Should we make an HTTP request for this URL at all?"""
        if not is_http(url):
            return False
        if self.mode == "page":
            return True  # caller restricts to seed + direct links anyway
        if self.mode == "internal":
            return self.is_internal(url)
        return True  # internal+external

    def should_recurse(self, url: str) -> bool:
        """Should we enqueue this URL for further crawling (extract its links)?"""
        if self.mode == "page":
            return False
        if not is_http(url):
            return False
        return self.is_internal(url)
