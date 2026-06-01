from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ScopeMode = Literal["page", "internal", "internal+external"]


@dataclass
class Config:
    start_url: str
    mode: ScopeMode = "internal+external"
    depth: int = 0  # 0 = unlimited

    rate_limit_rps: float = 5.0
    concurrency: int = 10
    timeout_s: float = 15.0
    max_redirects: int = 10
    user_agent: str = "findbrokenlinks/0.1 (+https://example.local)"
    ignore_robots: bool = False
    use_sitemap: bool = False

    redirect_chain_threshold: int = 3
    patterns_path: Path | None = None
    soft404_probe_enabled: bool = True

    enabled_checks: set[str] | None = None
    disabled_checks: set[str] = field(default_factory=set)

    formats: list[str] = field(default_factory=lambda: ["tsv"])
    output_path: Path | None = None
    output_dir: Path | None = None

    verbose: bool = False
    log_file: Path | None = None
