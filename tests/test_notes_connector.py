"""Unit tests for NotesConnector (Simplenote ZIPs, Keep, and loose notes)."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from connectors.notes import NotesConnector, _extract_title, _extract_summary, _format_note_body
from connectors.sdk.writer import write_unit


def test_extract_title_and_summary():
    content = "# Project Proposal\n\nThis is the executive summary. Additional details follow."
    assert _extract_title(content) == "Project Proposal"
    assert _extract_summary(content) == "This is the executive summary."

    plain_content = "Shopping List\n- Apples\n- Oranges"
    assert _extract_title(plain_content) == "Shopping List"
    assert _extract_summary(plain_content) == "- Apples - Oranges."


def test_simplenote_json_zip(tmp_path: Path):
    inbox_notes = tmp_path / "inbox" / "notes"
    inbox_notes.mkdir(parents=True)
    zip_path = inbox_notes / "simplenote_export.zip"

    notes_data = {
        "activeNotes": [
            {
                "id": "note-12345",
                "content": "Architecture Rationale\n\nWe decided to use QMD for full-text and vector search. It is fast.",
                "creationDate": "2024-03-10T14:30:00.000Z",
                "lastModified": "2024-03-11T10:00:00.000Z",
                "tags": ["architecture", "search"],
                "pinned": True,
                "deleted": False,
            },
            {
                "id": "note-trashed",
                "content": "Old Draft\n\nDelete this later.",
                "creationDate": "2024-01-01T00:00:00.000Z",
                "deleted": True,
            },
        ],
        "trashedNotes": [],
    }

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("source/notes.json", json.dumps(notes_data))
        zf.writestr("notes/Architecture Rationale.txt", notes_data["activeNotes"][0]["content"])

    connector = NotesConnector(inbox_dir=inbox_notes)
    since = datetime(2023, 1, 1, tzinfo=timezone.utc)
    units = list(connector.fetch_recent(since=since))

    assert len(units) == 1
    u = units[0]
    assert u.source == "simplenote"
    assert u.silo == "notes/simplenote"
    assert u.source_id == "note-12345"
    assert u.title == "Architecture Rationale"
    assert "We decided to use QMD" in u.summary
    assert "architecture" in u.tags
    assert "simplenote" in u.tags
    assert "2024-03-10" in u.created_at

    # Verify write_unit writes to corpus
    corpus = tmp_path / "corpus"
    unit_path = write_unit(u, corpus)
    assert unit_path.exists()
    assert "notes/simplenote" in str(unit_path.as_posix())
    content = unit_path.read_text(encoding="utf-8")
    assert "source: simplenote" in content
    assert "silo: notes/simplenote" in content
    assert "# Architecture Rationale" in content


def test_simplenote_txt_fallback_zip(tmp_path: Path):
    inbox_notes = tmp_path / "inbox" / "notes"
    inbox_notes.mkdir(parents=True)
    zip_path = inbox_notes / "notes_backup.zip"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("notes/Meeting Notes.txt", "Sprint Planning\n\nFocus on search latency.")
        zf.writestr("notes/Ideas.txt", "Book Recommendation\nRead The Pragmatic Programmer.")

    connector = NotesConnector(inbox_dir=inbox_notes)
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    units = list(connector.fetch_recent(since=since))

    assert len(units) == 2
    titles = {u.title for u in units}
    assert "Sprint Planning" in titles or "Meeting Notes" in titles
    assert any("latency" in u.summary for u in units)


def test_loose_notes(tmp_path: Path):
    inbox_notes = tmp_path / "inbox" / "notes"
    inbox_notes.mkdir(parents=True)

    quick_note = inbox_notes / "quick_idea.md"
    quick_note.write_text("# Solar Panel Sizing\n\nCalculate daily kWh output.", encoding="utf-8")

    connector = NotesConnector(inbox_dir=inbox_notes)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    units = list(connector.fetch_recent(since=since))

    assert len(units) == 1
    assert units[0].title == "Solar Panel Sizing"
    assert units[0].silo == "notes"
    assert units[0].source_id == "quick_idea"
