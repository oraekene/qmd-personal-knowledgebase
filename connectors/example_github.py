"""Example thin connector — demonstrates minimal SDK surface for #11 prototype.

One plugin that yields a single UnitPayload for a fake GitHub repo,
writes via writer.write_unit, and is discoverable via sdk discovery.

Per #9 locked schema and #10 orchestrator contract: forward scan since last_seen,
CrawlState repointed, single write, no chunking.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Iterator

from connectors.sdk.base import SourcePlugin, UnitPayload


class ExampleGithubConnector(SourcePlugin):
    NAME = "example_github"
    DESCRIPTION = "Thin example — one GitHub repo as Unit"
    REQUIRES_AUTH = False
    SUPPORTS_LOOKBACK = False
    DEFAULT_CONFIG: dict = {}

    def fetch_recent(self, since: datetime, limit: int = 50) -> Iterator[UnitPayload]:
        # In real connector, would call GitHub API for repos updated since `since`
        # Here we yield one deterministic Unit for the prototype
        fake_created = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
        if since and fake_created <= since:
            return
        if limit <= 0:
            return
        yield UnitPayload(
            source=self.NAME,
            silo="github",
            source_id="oraekene__nebula",
            url="https://github.com/oraekene/nebula",
            created_at=fake_created.isoformat(),
            tags=["python", "example"],
            author="oraekene",
            title="Nebula",
            summary="GitHub repo oraekene/nebula — forked, 12 stars, example thin connector.",
            body_markdown="# Nebula\n\nExample repo for thin connector prototype. Forked from upstream, 12 stars.\n\n## README\n\nContent here as-is from repo files.",
        )
