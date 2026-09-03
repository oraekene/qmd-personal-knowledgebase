# scripts package — mirrors, smokes, wiki, etc.
"""Shared helpers for scripts — dedupes _is_excluded across build_mirror/wiki."""
from __future__ import annotations

import pathlib


def is_excluded(path: pathlib.Path) -> bool:
    """Single source of truth for state/qmd/llmwiki exclusion.

    Fixes Duplicated Code across scripts/build_mirror.py and scripts/wiki.py.
    Excludes CrawlState, QMD index, and llmwiki state from corpus scans.
    """
    return "_state" in path.parts or ".qmd" in path.parts or ".llmwiki" in path.parts
