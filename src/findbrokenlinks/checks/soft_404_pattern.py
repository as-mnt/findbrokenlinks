from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef

VALID_TARGETS = {"title", "h1", "body", "raw"}


@dataclass
class CompiledPattern:
    name: str
    target: str  # 'title' | 'h1' | 'body' (BeautifulSoup-extracted text) | 'raw' (HTML as-is)
    regex: re.Pattern[str]


def load_patterns(extra: Path | None = None) -> list[CompiledPattern]:
    """Load built-in patterns and optionally user patterns. Composite."""
    paths = [Path(__file__).resolve().parent.parent / "patterns" / "builtin.yaml"]
    if extra is not None:
        paths.append(extra)
    compiled: list[CompiledPattern] = []
    for p in paths:
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or []
        for item in raw:
            target = item.get("target", "body")
            if target not in VALID_TARGETS:
                raise ValueError(
                    f"soft-404 pattern {item.get('name', '?')!r}: unknown target "
                    f"{target!r} (allowed: {sorted(VALID_TARGETS)})"
                )
            compiled.append(
                CompiledPattern(
                    name=item["name"],
                    target=target,
                    regex=re.compile(item["regex"]),
                )
            )
    return compiled


def _extract_targets(body: str) -> dict[str, str]:
    """Return the four search surfaces.

    title/h1/body are BeautifulSoup-extracted text — convenient for human-readable
    error messages but stripped of all markup. `raw` is the unaltered HTML body —
    use it for patterns that need to look at tags, classes, or server signatures
    that don't survive text extraction.
    """
    soup = BeautifulSoup(body, "lxml")
    title = (soup.title.string if soup.title and soup.title.string else "") or ""
    h1_el = soup.find("h1")
    h1 = h1_el.get_text(" ", strip=True) if h1_el else ""
    text = soup.get_text(" ", strip=True)
    return {"title": title.strip(), "h1": h1, "body": text, "raw": body}


@register
class Soft404PatternCheck(Check):
    code = "SOFT_404_PATTERN"
    severity = "warning"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if fetch.status is None or fetch.status >= 400:
            return None
        if not fetch.body:
            return None
        if not ctx.soft404_patterns:
            return None
        targets = _extract_targets(fetch.body)
        for pat in ctx.soft404_patterns:
            haystack = targets.get(pat.target, "")
            if not haystack:
                continue
            if pat.regex.search(haystack):
                return Issue(
                    code=self.code,
                    severity=self.severity,
                    message=f"Page matched soft-404 pattern {pat.name!r} in {pat.target}",
                    details={"pattern": pat.name, "target": pat.target},
                )
        return None
