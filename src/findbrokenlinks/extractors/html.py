from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from findbrokenlinks.extractors.base import Extractor
from findbrokenlinks.models import LinkRef
from findbrokenlinks.scope import is_skipped_scheme

# (tag, attribute) pairs and the logical tag name we use in LinkRef.
_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("a", "href", "a"),
    ("img", "src", "img"),
    ("script", "src", "script"),
    ("link", "href", "link"),
)


def _str_attr(tag: Tag, name: str) -> str | None:
    """Read a single string-valued HTML attribute, or None if missing/multi-valued."""
    value = tag.get(name)
    return value if isinstance(value, str) else None


def _first_rel(tag: Tag) -> str | None:
    """The `rel` attribute is multi-valued in HTML5; return the first token if any."""
    value = tag.get("rel")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item:
                return item
        return None
    return value if isinstance(value, str) and value else None


class HTMLExtractor(Extractor):
    def extract(self, body: str, source_page: str) -> Iterable[LinkRef]:
        soup = BeautifulSoup(body, "lxml")
        # Resolve relative URLs against <base href=...> if present, otherwise source_page.
        base_url = source_page
        base_tag = soup.find("base", href=True)
        if isinstance(base_tag, Tag):
            base_href = _str_attr(base_tag, "href")
            if base_href:
                base_url = urljoin(source_page, base_href)

        seen: set[tuple[str, str]] = set()
        for tag_name, attr, kind in _TARGETS:
            for el in soup.find_all(tag_name):
                if not isinstance(el, Tag):
                    continue
                raw = _str_attr(el, attr)
                if not raw:
                    continue
                raw = raw.strip()
                if not raw or raw.startswith("#"):
                    continue
                if is_skipped_scheme(raw):
                    continue
                absolute = urljoin(base_url, raw)
                # Drop fragment for fetch target (kept normalization in scope.normalize_url).
                parts = urlsplit(absolute)
                if not parts.scheme or not parts.netloc:
                    continue
                clean = absolute.split("#", 1)[0]

                key = (kind, clean)
                if key in seen:
                    continue
                seen.add(key)

                anchor: str | None
                if kind == "a":
                    anchor = el.get_text(strip=True) or None
                elif kind == "img":
                    alt = _str_attr(el, "alt")
                    anchor = alt if alt else None
                else:
                    anchor = _first_rel(el)

                yield LinkRef(url=clean, source_page=source_page, anchor=anchor, tag=kind)
