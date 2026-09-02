"""Plugin discovery — generalized from platform_extractor.py:346.

Per research #2: any connectors/*.py that defines a SourcePlugin subclass with non-empty NAME is auto-discovered.
"""
from __future__ import annotations
import importlib.util
import pathlib
from typing import Dict
from .base import SourcePlugin


def load_plugins(directory: pathlib.Path) -> Dict[str, SourcePlugin]:
    plugins: Dict[str, SourcePlugin] = {}
    if not directory.exists():
        return plugins
    for py in directory.glob("*.py"):
        if py.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(py.stem, py)
        if not spec or not spec.loader:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore
        except Exception:
            continue
        for attr in vars(mod).values():
            if isinstance(attr, type) and issubclass(attr, SourcePlugin) and attr is not SourcePlugin and attr.NAME:
                try:
                    plugins[attr.NAME] = attr()
                except Exception:
                    continue
    return plugins
