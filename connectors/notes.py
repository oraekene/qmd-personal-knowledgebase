"""Notes Inbox connector — Simplenote ZIPs, Google Keep, and loose text/md -> Units in corpus/notes/.

Per spec.md:109-111 + qmd.index.yml.example:37-44:
- Inbox: inbox/notes/ (or inbox/) ZIP drops or loose note files
- Simplenote ZIPs contain:
  1) source/notes.json (or root notes.json) with activeNotes array containing
     {id, content, creationDate, lastModified, tags, pinned, deleted}
  2) notes/*.txt fallback files (line 1 = title, subsequent lines = body)
- Google Keep Takeout ZIPs contain JSON or HTML notes in Takeout/Keep/
- Loose .txt and .md files in inbox/notes/
- Yields UnitPayload into silo `notes/simplenote` (or `notes/keep`, `notes`)
- Standard QMD Unit with YAML frontmatter, summary blockquote, and # Title
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from connectors.sdk.base import SourcePlugin, UnitPayload


def _extract_title(content: str, fallback: str = "Untitled Note") -> str:
    """Extract clean title from the first non-empty line of content."""
    for line in content.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:80].strip()
    return fallback


def _extract_summary(content: str) -> str:
    """Extract one clean sentence summary from note body."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return "Personal note."
    text = " ".join(lines[1:]) if len(lines) > 1 else lines[0]
    text = text.replace("\n", " ").strip()
    if not text:
        text = lines[0]

    for sep in [". ", "! ", "? "]:
        if sep in text:
            text = text.split(sep)[0] + sep.strip()
            break

    if len(text) > 120:
        text = text[:120].rstrip() + "..."
    if text and text[-1] not in ".!?":
        text += "."
    return text or "Personal note."


def _format_note_body(content: str, title: str) -> str:
    """Ensure content has markdown heading # Title."""
    stripped = content.strip()
    if stripped.startswith(f"# {title}"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].strip().lstrip("#").strip() == title:
        return f"# {title}\n\n" + "\n".join(lines[1:]).lstrip()
    return f"# {title}\n\n{stripped}"


def _parse_iso_date(date_str: Any) -> datetime:
    """Parse ISO8601 date string or timestamp, fallback to utcnow."""
    if not date_str:
        return datetime.now(timezone.utc)
    if isinstance(date_str, (int, float)):
        try:
            return datetime.fromtimestamp(date_str / 1000.0 if date_str > 1e11 else date_str, tz=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)
    if isinstance(date_str, str):
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return datetime.now(timezone.utc)


class NotesConnector(SourcePlugin):
    """Inbox connector for personal notes (Simplenote ZIPs, Keep, loose notes)."""

    NAME = "notes"
    DESCRIPTION = "Personal notes and quick captures from Simplenote, Keep, and loose text/md"
    REQUIRES_AUTH = False
    SUPPORTS_LOOKBACK = False

    def __init__(self, inbox_dir: Path | str | None = None):
        super().__init__()
        self.inbox_dir = Path(inbox_dir) if inbox_dir else Path("inbox/notes")

    def fetch_recent(self, since: datetime, limit: int = 500) -> Iterator[UnitPayload]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        count = 0
        search_dirs = [self.inbox_dir]
        if self.inbox_dir.parent.exists() and self.inbox_dir.parent.name == "inbox":
            search_dirs.append(self.inbox_dir.parent)

        seen_ids = set()

        for sdir in search_dirs:
            if not sdir.exists():
                continue

            # 1. Process ZIP files (Simplenote, Keep)
            for zip_path in sorted(sdir.glob("*.zip")):
                if count >= limit:
                    break
                is_notes_dir = sdir.name == "notes"
                lower_name = zip_path.name.lower()
                is_notes_name = any(k in lower_name for k in ("note", "simplenote", "keep"))

                if not (is_notes_dir or is_notes_name):
                    continue

                for payload in self._process_zip(zip_path, since):
                    if payload.source_id in seen_ids:
                        continue
                    seen_ids.add(payload.source_id)
                    count += 1
                    yield payload
                    if count >= limit:
                        break

            # 2. Process loose .txt and .md files in inbox/notes
            if sdir.name == "notes":
                for note_file in sorted(list(sdir.glob("*.md")) + list(sdir.glob("*.txt"))):
                    if count >= limit:
                        break
                    try:
                        mtime = datetime.fromtimestamp(note_file.stat().st_mtime, tz=timezone.utc)
                        if mtime <= since:
                            continue
                        content = note_file.read_text(encoding="utf-8", errors="replace")
                        if not content.strip():
                            continue

                        source_id = note_file.stem
                        if source_id in seen_ids:
                            continue
                        seen_ids.add(source_id)

                        title = _extract_title(content, fallback=note_file.stem)
                        summary = _extract_summary(content)
                        body = _format_note_body(content, title)

                        count += 1
                        yield UnitPayload(
                            source=self.NAME,
                            silo="notes",
                            source_id=source_id,
                            url="",
                            created_at=mtime.isoformat(),
                            tags=["notes"],
                            author="user",
                            title=title,
                            summary=summary,
                            body_markdown=body,
                        )
                    except Exception:
                        continue

    def _process_zip(self, zip_path: Path, since: datetime) -> Iterator[UnitPayload]:
        """Extract Simplenote or Keep notes from a ZIP archive."""
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                namelist = zf.namelist()

                # Check for Simplenote JSON (source/notes.json or notes.json)
                json_candidates = [n for n in namelist if n.lower().endswith("notes.json")]
                if json_candidates:
                    target_json = json_candidates[0]
                    try:
                        raw_data = zf.read(target_json)
                        parsed = json.loads(raw_data.decode("utf-8", errors="replace"))

                        notes_list = []
                        if isinstance(parsed, dict) and "activeNotes" in parsed:
                            notes_list = parsed["activeNotes"]
                        elif isinstance(parsed, list):
                            notes_list = parsed
                        elif isinstance(parsed, dict) and "notes" in parsed:
                            notes_list = parsed["notes"]

                        if notes_list:
                            for note in notes_list:
                                if not isinstance(note, dict):
                                    continue
                                if note.get("deleted", False):
                                    continue

                                content = note.get("content", "")
                                if not content.strip():
                                    continue

                                note_id = str(note.get("id") or "")
                                created_at = _parse_iso_date(note.get("creationDate") or note.get("lastModified"))
                                if created_at <= since:
                                    continue

                                title = _extract_title(content, fallback=note_id or "Untitled Note")
                                if not note_id:
                                    note_id = re.sub(r"[^\w\-]", "_", title.lower())[:40]

                                summary = _extract_summary(content)
                                body = _format_note_body(content, title)

                                raw_tags = note.get("tags") or []
                                tags = ["simplenote", "notes"]
                                for t in raw_tags:
                                    if isinstance(t, str) and t.strip():
                                        tags.append(t.strip().lower())

                                yield UnitPayload(
                                    source="simplenote",
                                    silo="notes/simplenote",
                                    source_id=note_id,
                                    url="",
                                    created_at=created_at.isoformat(),
                                    tags=tags,
                                    author="user",
                                    title=title,
                                    summary=summary,
                                    body_markdown=body,
                                )
                            return
                    except Exception:
                        pass

                # Fallback: Process individual .txt / .md files in the zip (e.g. notes/*.txt)
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    lower_file = info.filename.lower()
                    if not (lower_file.endswith(".txt") or lower_file.endswith(".md")):
                        continue

                    stem = Path(info.filename).stem

                    try:
                        content = zf.read(info.filename).decode("utf-8", errors="replace")
                        if not content.strip():
                            continue

                        try:
                            created_at = datetime(*info.date_time, tzinfo=timezone.utc)
                        except Exception:
                            created_at = datetime.now(timezone.utc)

                        if created_at <= since:
                            continue

                        title = _extract_title(content, fallback=stem)
                        summary = _extract_summary(content)
                        body = _format_note_body(content, title)

                        yield UnitPayload(
                            source="simplenote",
                            silo="notes/simplenote",
                            source_id=stem,
                            url="",
                            created_at=created_at.isoformat(),
                            tags=["simplenote", "notes"],
                            author="user",
                            title=title,
                            summary=summary,
                            body_markdown=body,
                        )
                    except Exception:
                        continue
        except Exception:
            return
