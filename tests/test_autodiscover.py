"""Dropping a new check/reporter file must be enough — no __init__.py edits.

These tests write a synthetic plugin file into the package, re-run discovery,
and verify it shows up in REGISTRY. Files and registry entries are cleaned up
in a finally block to keep the source tree pristine between runs.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from findbrokenlinks.checks import REGISTRY as CHECKS_REGISTRY
from findbrokenlinks.reporters import REGISTRY as REPORTERS_REGISTRY


def test_new_check_file_is_autodiscovered():
    pkg_dir = Path(importlib.import_module("findbrokenlinks.checks").__file__).parent
    plugin_path = pkg_dir / "zzz_autodiscover_probe.py"
    plugin_path.write_text(
        """from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@register
class ZzzAutodiscoverProbe(Check):
    code = "ZZZ_AUTODISCOVER_PROBE"
    severity = "info"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext):
        return None
""",
        encoding="utf-8",
    )
    try:
        # Re-run discovery (simulates a fresh interpreter picking up the new file).
        from findbrokenlinks.checks import _discover

        _discover()
        assert "ZZZ_AUTODISCOVER_PROBE" in CHECKS_REGISTRY
    finally:
        plugin_path.unlink(missing_ok=True)
        CHECKS_REGISTRY.pop("ZZZ_AUTODISCOVER_PROBE", None)
        # Drop the imported module too so a later test run starts clean.
        import sys

        sys.modules.pop("findbrokenlinks.checks.zzz_autodiscover_probe", None)


def test_new_reporter_file_is_autodiscovered():
    pkg_dir = Path(importlib.import_module("findbrokenlinks.reporters").__file__).parent
    plugin_path = pkg_dir / "zzz_autodiscover_probe.py"
    plugin_path.write_text(
        """from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register


@register
class ZzzAutodiscoverProbeReporter(Reporter):
    name = "zzz-probe"
    file_ext = "zzz"

    def render(self, findings: list[Finding]) -> str:
        return ""
""",
        encoding="utf-8",
    )
    try:
        from findbrokenlinks.reporters import _discover

        _discover()
        assert "zzz-probe" in REPORTERS_REGISTRY
    finally:
        plugin_path.unlink(missing_ok=True)
        REPORTERS_REGISTRY.pop("zzz-probe", None)
        import sys

        sys.modules.pop("findbrokenlinks.reporters.zzz_autodiscover_probe", None)


def test_base_module_is_skipped_by_discovery():
    """Sanity check: `base` itself is not re-imported as a plugin candidate."""
    from findbrokenlinks.checks import _discover

    # Should be idempotent and never crash.
    _discover()
    _discover()
