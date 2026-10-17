"""Diagram and animation presets.

    from presets import install
    install(blocks.DIRECTIVES, config)      # every preset becomes a `:::name` directive

Built-in modules: graph (flow, state, er, network, swimlane), structure (sequence, layers, zones, tree,
mindmap, cycle, pyramid, funnel), charts (donut, chart, radar, gantt, quadrant, heatmap, stats).
Project presets: any `docs/site/presets_custom/*.py` that uses `from presets.common import preset`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from . import charts, graph, structure                       # noqa: F401  (importing registers the presets)
from .common import ANIMATIONS, CONFIG, REGISTRY, Preset, as_directive, reset_ids


def load_custom(folder: Path) -> list[str]:
    """Import every *.py in `folder`; returns the names of the presets they added."""
    before = set(REGISTRY)
    if folder.is_dir():
        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"presets_custom_{path.stem}", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
    return sorted(set(REGISTRY) - before)


def install(directives: dict[str, Any], config: dict[str, Any] | None = None, custom_dir: Path | None = None) -> list[str]:
    CONFIG.update(config or {})
    reset_ids()
    added = load_custom(custom_dir) if custom_dir else []
    for name, p in REGISTRY.items():
        directives[name] = as_directive(p)
    return added


def catalog() -> list[Preset]:
    """One entry per preset (aliases collapsed), grouped for display."""
    seen: dict[int, Preset] = {}
    for p in REGISTRY.values():
        seen.setdefault(id(p), p)
    return sorted(seen.values(), key=lambda p: (p.group, p.name))


__all__ = ["install", "catalog", "load_custom", "REGISTRY", "ANIMATIONS", "CONFIG", "reset_ids"]
