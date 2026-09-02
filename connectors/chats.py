"""Chats Inbox connector — ZIP drops for 6 platforms → Units in corpus/chats/{platform}/.

Per #16 + spec.md:109-111 + #9 per-silo templates + ADR-0007 (no connector split, QMD 900/135 chunks):
- Inbox: inbox/ ZIPs (claude, chatgpt, gemini, qwen, zai, deepseek exports) unpacked by normalizer
- Each ZIP contains one JSON per session: {id, platform, created_at, messages: [{role, content}]}
- One Unit per session, whole-session, alternating speaker sections, no split
- Silo: chats/{platform}, source: chats, source_id: session id, url: "", created_at: session created_at
- Summary Line: first user message truncated to one sentence
- Body: alternating sections, e.g. "User:\ncontent\n\nAssistant:\ncontent"

This is the production connector for #16 — fixture-testable, no live API.
"""
from __future__ import annotations
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from connectors.sdk.base import SourcePlugin, UnitPayload

# Supported platforms — per spec.md:109 + #9 Sils
SUPPORTED_PLATFORMS = {"claude", "chatgpt", "gemini", "qwen", "zai", "deepseek"}


def _platform_from_zip_name(zip_name: str) -> str | None:
    # e.g. claude-export.zip -> claude, chatgpt-export.zip -> chatgpt
    lower = zip_name.lower()
    for plat in SUPPORTED_PLATFORMS:
        if plat in lower:
            return plat
    return None


def _summary_from_messages(messages: list[dict]) -> str:
    # First user message, truncated to one sentence (up to . ! ? or 120 chars)
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content"):
            content = msg["content"].strip().replace("\n", " ")
            # Take first sentence
            for sep in [". ", "! ", "? "]:
                if sep in content:
                    content = content.split(sep)[0] + sep.strip()
                    break
            # Truncate
            if len(content) > 120:
                content = content[:120].rstrip() + "..."
            # Ensure ends with period if not
            if content and content[-1] not in ".!?":
                content += "."
            return content
    # Fallback: first message
    if messages:
        return messages[0].get("content", "")[:120]
    return "Chat session."


def _body_from_messages(messages: list[dict], title: str) -> str:
    # Alternating speaker sections, whole-session, no split
    # Per #9: chat session Units alternate speaker sections and are written as one file per session
    parts = [f"# {title}\n"]
    for msg in messages:
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "")
        # Use role as heading or bold? Use "User:" / "Assistant:" sections
        parts.append(f"**{role}:**\n\n{content}\n")
    return "\n".join(parts)


class ChatsConnector(SourcePlugin):
    """Inbox ZIP connector for chats silo."""

    NAME = "chats"
    DESCRIPTION = "Chat exports from 6 platforms via inbox ZIPs"
    REQUIRES_AUTH = False
    SUPPORTS_LOOKBACK = False
    DEFAULT_CONFIG: dict = {}

    def __init__(self, inbox_dir: Path | str | None = None, corpus_root: Path | str | None = None):
        super().__init__()
        # Inbox is watched folder where manual export drops land (per CONTEXT.md Inbox)
        self.inbox_dir = Path(inbox_dir) if inbox_dir else Path("inbox")
        self.corpus_root = Path(corpus_root) if corpus_root else Path("corpus")

    def fetch_recent(self, since: datetime, limit: int = 50) -> Iterator[UnitPayload]:
        # Scan inbox for ZIPs
        if not self.inbox_dir.exists():
            return
        # Ensure since is timezone-aware
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        count = 0
        # Sort ZIPs for deterministic order
        for zip_path in sorted(self.inbox_dir.glob("*.zip")):
            if count >= limit:
                break
            # Determine platform from ZIP name as fallback
            zip_platform = _platform_from_zip_name(zip_path.name)
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        if not info.filename.lower().endswith(".json"):
                            continue
                        if count >= limit:
                            break
                        try:
                            data = zf.read(info.filename)
                            sess = json.loads(data.decode("utf-8"))
                        except Exception:
                            continue
                        # Validate session
                        sess_id = sess.get("id")
                        if not sess_id:
                            continue
                        platform = sess.get("platform") or zip_platform or "claude"
                        # Only handle supported platforms, but allow any for test
                        if platform not in SUPPORTED_PLATFORMS:
                            # Still allow, but normalize to lower
                            platform = platform.lower()
                        created_at_str = sess.get("created_at") or "2026-09-01T00:00:00+00:00"
                        try:
                            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                            if created_at.tzinfo is None:
                                created_at = created_at.replace(tzinfo=timezone.utc)
                        except Exception:
                            created_at = datetime.now(timezone.utc)
                        # Respect since (only yield if created_at > since)
                        if created_at <= since:
                            continue
                        messages = sess.get("messages") or []
                        # Skip empty sessions
                        if not messages:
                            continue
                        summary = _summary_from_messages(messages)
                        title = sess_id
                        # Try to derive title from first user message if available
                        # Use sess_id as title per spec (source_id is native ID)
                        body_markdown = _body_from_messages(messages, title)

                        payload = UnitPayload(
                            source=self.NAME,
                            silo=f"chats/{platform}",
                            source_id=sess_id,
                            url="",
                            created_at=created_at.isoformat(),
                            tags=[platform],
                            author="",
                            title=title,
                            summary=summary,
                            body_markdown=body_markdown,
                        )
                        count += 1
                        yield payload
            except zipfile.BadZipFile:
                continue
            except Exception:
                continue
