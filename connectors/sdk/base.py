"""SourcePlugin base + UnitPayload — generalized from platform_extractor.py:178-229 and research #2.

Per spec.md:87-91 + CONTEXT.md:14-30 + map #9 locked schema:
- Unit = one file per logical item, 9-field Frontmatter (no title), Summary Line required, first heading = title
- Silo = top-level corpus subtree = QMD collection (github, chats/{6}, twitter/bookmarks, notes/{2}, pdfs, web, wiki)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator


@dataclass
class UnitPayload:
    """What a connector yields; writer turns it into a Unit file."""

    source: str  # plugin NAME, also frontmatter source
    silo: str  # corpus subdir, e.g. github, chats/claude, twitter/bookmarks
    source_id: str  # native stable ID
    url: str | None = None
    created_at: str | None = None  # ISO8601
    tags: list[str] = field(default_factory=list)
    author: str = ""
    title: str = ""  # becomes first # heading (not frontmatter)
    summary: str = ""  # one sentence -> blockquote Summary Line (required)
    body_markdown: str = ""  # per-silo template body (after summary + heading)
    extra: dict[str, Any] = field(default_factory=dict)


class SourcePlugin(ABC):
    """Generalized from platform_extractor.py:178. Copy, not import."""

    NAME: str = ""
    DESCRIPTION: str = ""
    REQUIRES_AUTH: bool = False
    SUPPORTS_LOOKBACK: bool = False
    DEFAULT_CONFIG: dict[str, Any] = {}

    def configure(self, config: dict[str, Any]) -> None:
        cfg = dict(self.DEFAULT_CONFIG)
        cfg.update(config)
        self._config = cfg  # type: ignore

    @abstractmethod
    def fetch_recent(self, since: datetime, limit: int = 50) -> Iterator[UnitPayload]:
        """Forward scan — yield Units discovered since `since`."""

    def fetch_batch(self, cursor: Any, batch_size: int = 50) -> tuple[list[UnitPayload], Any]:
        """Lookback — returns (items, next_cursor). next_cursor=None => history_complete."""
        return [], None

    def get_config_schema(self) -> dict[str, Any]:
        return {}

    def health_check(self) -> tuple[bool, str]:
        return True, "ok"
