from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from findbrokenlinks.models import Finding


class Reporter(ABC):
    name: ClassVar[str]
    file_ext: ClassVar[str] = "txt"

    @abstractmethod
    def render(self, findings: list[Finding]) -> str: ...


REGISTRY: dict[str, type[Reporter]] = {}


def register(cls: type[Reporter]) -> type[Reporter]:
    if not getattr(cls, "name", None):
        raise TypeError(f"{cls.__name__} must define a non-empty `name`")
    if cls.name in REGISTRY:
        raise ValueError(f"Reporter {cls.name!r} already registered")
    REGISTRY[cls.name] = cls
    return cls


def get_reporter(name: str) -> Reporter:
    cls = REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"Unknown format {name!r}. Available: {sorted(REGISTRY)}")
    return cls()


def _row_for(finding: Finding) -> dict[str, object]:
    """Common flat row shape shared by tabular reporters."""
    issue_codes = [i.code for i in finding.issues]
    details = "; ".join(i.message for i in finding.issues)
    return {
        "source_page": finding.link.source_page,
        "link_url": finding.link.url,
        "final_url": finding.fetch.final_url,
        "anchor": finding.link.anchor or "",
        "tag": finding.link.tag,
        "status": "" if finding.fetch.status is None else finding.fetch.status,
        "redirect_chain": " -> ".join(finding.fetch.redirect_chain),
        "issue_codes": ",".join(issue_codes),
        "severity": finding.worst_severity,
        "details": details,
    }


ROW_FIELDS: tuple[str, ...] = (
    "source_page",
    "link_url",
    "final_url",
    "anchor",
    "tag",
    "status",
    "redirect_chain",
    "issue_codes",
    "severity",
    "details",
)
