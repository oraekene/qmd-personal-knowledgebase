import pathlib
import re
import hashlib
import tempfile
import os

# Seam: Unit on disk (writer) — one test observes external behavior: fixtures in, Units out
# Per spec #9 locked schema: 9-field Frontmatter (no title), Summary Line required, first heading = title, path corpus/<silo>/<safe_source_id>.md, blake3-like hash, idempotent


def test_write_unit_creates_file_with_frontmatter_and_summary():
    from connectors.sdk.writer import write_unit
    from connectors.sdk.base import UnitPayload
    import datetime

    with tempfile.TemporaryDirectory() as tmp:
        corpus = pathlib.Path(tmp) / "corpus"
        payload = UnitPayload(
            source="example_github",
            silo="github",
            source_id="oraekene__nebula",
            url="https://github.com/oraekene/nebula",
            created_at="2026-09-01T10:00:00+00:00",
            tags=["python"],
            author="",
            title="Nebula",
            summary="GitHub repo oraekene/nebula — forked, 12 stars.",
            body_markdown="# Nebula\n\nContent here.",
        )
        out = write_unit(payload, corpus)
        assert out.exists(), "Unit file should exist"
        assert out == corpus / "github" / "oraekene__nebula.md"
        text = out.read_text(encoding="utf-8")
        # frontmatter
        assert text.startswith("---\n"), "should start with frontmatter"
        for field in ["source:", "silo:", "source_id:", "url:", "created_at:", "ingested_at:", "content_hash:"]:
            assert field in text, f"missing {field}"
        assert "title:" not in text.lower(), "no title field per spec"
        # summary line blockquote immediately after frontmatter
        # split frontmatter and body
        parts = text.split("---\n", 2)
        # parts[0]='', parts[1]=frontmatter, parts[2]=body
        body = parts[2].lstrip("\n")
        assert body.startswith("> "), "body should start with Summary Line blockquote"
        assert "GitHub repo oraekene/nebula" in body
        # first heading after summary
        assert "# Nebula" in body
        # content_hash is blake2b hex of body (payload.body_markdown + summary+heading?)
        # writer computes over full body after frontmatter (summary+heading+content)
        m = re.search(r"content_hash:\s*([a-f0-9]+)", text)
        assert m, "content_hash should be hex"
        assert len(m.group(1)) == 64, "blake2b hex length 64"


def test_write_unit_requires_summary_line():
    from connectors.sdk.writer import write_unit
    from connectors.sdk.base import UnitPayload

    with tempfile.TemporaryDirectory() as tmp:
        corpus = pathlib.Path(tmp) / "corpus"
        payload = UnitPayload(
            source="test",
            silo="github",
            source_id="id1",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="T",
            summary="",  # empty summary should fail
            body_markdown="# T\nBody",
        )
        try:
            write_unit(payload, corpus)
            assert False, "should raise for missing summary"
        except ValueError as e:
            assert "Summary Line" in str(e) or "summary" in str(e).lower()


def test_write_unit_idempotent_skip_on_same_hash():
    from connectors.sdk.writer import write_unit
    from connectors.sdk.base import UnitPayload

    with tempfile.TemporaryDirectory() as tmp:
        corpus = pathlib.Path(tmp) / "corpus"
        payload = UnitPayload(
            source="test",
            silo="github",
            source_id="dup",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="Dup",
            summary="Dup unit for idempotency.",
            body_markdown="# Dup\nSame content.",
        )
        out1 = write_unit(payload, corpus)
        mtime1 = out1.stat().st_mtime
        # second write same content should be idempotent (skip, mtime unchanged or same hash)
        import time; time.sleep(0.01)
        out2 = write_unit(payload, corpus)
        assert out2 == out1
        # hash unchanged, file not rewritten (or rewritten but same content)
        assert out2.read_text(encoding="utf-8") == out1.read_text(encoding="utf-8")


def test_safe_filename_sanitizes_slashes():
    from connectors.sdk.writer import safe_filename

    assert safe_filename("a/b") == "a__b"
    assert safe_filename("owner/repo") == "owner__repo"
    assert safe_filename("my file") == "my_file" or "my file" in safe_filename("my file")  # allow space or underscore


def test_write_unit_silo_with_subpath():
    from connectors.sdk.writer import write_unit
    from connectors.sdk.base import UnitPayload

    with tempfile.TemporaryDirectory() as tmp:
        corpus = pathlib.Path(tmp) / "corpus"
        payload = UnitPayload(
            source="claude",
            silo="chats/claude",
            source_id="session-123",
            url="https://claude.ai/chat/123",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="user",
            title="Chat Session",
            summary="Claude chat session about OCR decisions.",
            body_markdown="# Chat Session\n\nUser: which OCR?\nAssistant: LiteParse.",
        )
        out = write_unit(payload, corpus)
        assert out == corpus / "chats" / "claude" / "session-123.md"
        assert out.exists()
