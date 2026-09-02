"""CrawlState — repointed from platform_extractor.py:234-301, generalized for corpus.

Per research #2 + spec.md:120, map #10 locked: persists per-source forward last_seen and lookback cursor in corpus/_state/crawl_state.json, atomic JSON, forward cursor = timestamp.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CrawlState:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] = {"sources": {}, "global": {}}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {"sources": {}, "global": {}}
        # ensure shape
        self._data.setdefault("sources", {})
        self._data.setdefault("global", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # atomic write via temp
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _src(self, name: str) -> dict[str, Any]:
        src = self._data["sources"].setdefault(name, {})
        src.setdefault("forward", {})
        src.setdefault("lookback", {})
        return src

    def get_last_seen(self, name: str, default: datetime) -> datetime:
        src = self._src(name)
        v = src["forward"].get("last_seen")
        if v:
            try:
                return datetime.fromisoformat(v)
            except Exception:
                pass
        return default

    def set_last_seen(self, name: str, dt: datetime) -> None:
        src = self._src(name)
        src["forward"]["last_seen"] = dt.astimezone(timezone.utc).isoformat()
        src["forward"]["last_run"] = datetime.now(timezone.utc).isoformat()

    def increment_forward_count(self, name: str, n: int = 1) -> None:
        src = self._src(name)
        src["forward"]["total_discovered"] = src["forward"].get("total_discovered", 0) + n
        self._data["global"]["total_discovered"] = self._data["global"].get("total_discovered", 0) + n

    def get_lookback_cursor(self, name: str) -> Any:
        return self._src(name)["lookback"].get("cursor")

    def set_lookback_cursor(self, name: str, cursor: Any) -> None:
        src = self._src(name)
        src["lookback"]["cursor"] = cursor
        src["lookback"]["last_run"] = datetime.now(timezone.utc).isoformat()

    def is_history_complete(self, name: str) -> bool:
        return bool(self._src(name)["lookback"].get("history_complete"))

    def mark_history_complete(self, name: str) -> None:
        self._src(name)["lookback"]["history_complete"] = True

    def get_floor_date(self, name: str, default: str = "2024-01-01") -> datetime:
        src = self._src(name)
        v = src["lookback"].get("floor_date")
        if not v:
            v = default
            src["lookback"]["floor_date"] = v
        try:
            return datetime.fromisoformat(v)
        except Exception:
            return datetime.fromisoformat(default)

    def bump_global(self, n: int = 1) -> None:
        self._data["global"]["total_discovered"] = self._data["global"].get("total_discovered", 0) + n
        self._data["global"]["last_run"] = datetime.now(timezone.utc).isoformat()
