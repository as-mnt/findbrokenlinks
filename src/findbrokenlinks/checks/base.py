from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from findbrokenlinks.models import FetchResult, Issue, LinkRef

if TYPE_CHECKING:
    from findbrokenlinks.config import Config  # noqa: F401 — used in annotations


@dataclass
class Baseline404:
    status: int | None
    final_url: str
    text_len: int
    text_hash: str


@dataclass
class CheckContext:
    config: Config
    base_host: str
    baselines: dict[str, Baseline404] = field(default_factory=dict)  # host -> baseline
    soft404_patterns: list[Any] = field(default_factory=list)  # compiled patterns


class Check(ABC):
    code: ClassVar[str]
    severity: ClassVar[str] = "error"

    @abstractmethod
    def evaluate(
        self, link: LinkRef, fetch: FetchResult, ctx: CheckContext
    ) -> Issue | None: ...


REGISTRY: dict[str, type[Check]] = {}


def register(cls: type[Check]) -> type[Check]:
    if not getattr(cls, "code", None):
        raise TypeError(f"{cls.__name__} must define a non-empty `code`")
    if cls.code in REGISTRY:
        raise ValueError(f"Check code {cls.code!r} already registered")
    REGISTRY[cls.code] = cls
    return cls


def active_checks(ctx: CheckContext) -> list[Check]:
    """Instantiate checks honoring enable/disable config."""
    enabled = ctx.config.enabled_checks
    disabled = ctx.config.disabled_checks
    result: list[Check] = []
    for code, cls in REGISTRY.items():
        if enabled is not None and code not in enabled:
            continue
        if code in disabled:
            continue
        if code == "SOFT_404_PROBE" and not ctx.config.soft404_probe_enabled:
            continue
        result.append(cls())
    return result
