"""Reporter registry — populated by side-effect when submodules are imported.

Auto-discovers every non-private submodule in this package so dropping a new
file with an ``@register`` decorator is enough — no edits here required.
"""

from __future__ import annotations

import importlib
import pkgutil

from findbrokenlinks.reporters.base import REGISTRY, Reporter, register  # noqa: F401


def _discover() -> None:
    for info in pkgutil.iter_modules(__path__):
        if info.name == "base" or info.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{info.name}")


_discover()
