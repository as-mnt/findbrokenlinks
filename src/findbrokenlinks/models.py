from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class LinkRef:
    """A link discovered on a source page."""

    url: str
    source_page: str
    anchor: str | None
    tag: str  # 'a' | 'img' | 'script' | 'link'


@dataclass
class FetchResult:
    """Outcome of fetching a single URL."""

    url: str
    final_url: str
    status: int | None
    redirect_chain: list[str]
    headers: Mapping[str, str]
    body: str | None
    elapsed_ms: float
    error: str | None = None  # 'timeout' | 'dns' | 'ssl' | 'connect' | other
    content_type: str | None = None
    # Set when the request only succeeded because TLS verification was relaxed
    # for a recoverable reason — currently just 'ssl_chain' (missing intermediate
    # CA). The fetch is otherwise normal (status, body) but we record the lapse
    # so a check can surface it as a warning. error stays None in this case.
    tls_warning: str | None = None


@dataclass(frozen=True)
class Issue:
    """A single problem identified by a Check."""

    code: str
    severity: Severity
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    """A link with one or more issues."""

    link: LinkRef
    fetch: FetchResult
    issues: list[Issue]

    @property
    def worst_severity(self) -> Severity:
        order = {"error": 3, "warning": 2, "info": 1}
        return max((i.severity for i in self.issues), key=lambda s: order[s], default="info")
