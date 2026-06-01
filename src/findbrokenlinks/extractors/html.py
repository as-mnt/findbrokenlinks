from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

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


class HTMLExtractor(Extractor):
    def extract(self, body: str, source_page: str) -> Iterable[LinkRef]:
        soup = BeautifulSoup(body, "lxml")
        # Resolve relative URLs against <base href=...> if present, otherwise source_page.
        base_tag = soup.find("base", href=True)
        base_url = urljoin(source_page, base_tag["href"]) if base_tag else source_page

        seen: set[tuple[str, str]] = set()
        for tag_name, attr, kind in _TARGETS:
            for el in soup.find_all(tag_name):
                raw = el.get(attr)
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
                    anchor = el.get("alt") or None
                else:
                    anchor = el.get("rel", [None])[0] if isinstance(el.get("rel"), list) else None

                yield LinkRef(url=clean, source_page=source_page, anchor=anchor, tag=kind)
