import pathlib
import tempfile
import zipfile
import json
from datetime import datetime, timezone

# Seam: Chat Inbox connector — ZIP drops -> Units in corpus/chats/{platform}/, whole-session, 9-field Frontmatter
# Per #16 + spec.md:109-111 + #9 per-silo templates + ADR-0007 (no connector split)


def _make_zip_with_sessions(zip_path: pathlib.Path, sessions: list[dict]):
    """Helper: create a ZIP containing one JSON per session."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for sess in sessions:
            name = f"{sess['id']}.json"
            zf.writestrings = getattr(zf, "writestr", None)  # compat
            zf.writestr(name, json.dumps(sess, ensure_ascii=False))


def test_chats_connector_zip_yields_units_in_correct_silo():
    from connectors.chats import ChatsConnector

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        inbox = tmp_path / "inbox"
        corpus = tmp_path / "corpus"
        inbox.mkdir()
        corpus.mkdir()

        # Create claude ZIP with 2 sessions
        claude_zip = inbox / "claude-export.zip"
        sessions = [
            {
                "id": "sess-001",
                "platform": "claude",
                "created_at": "2026-09-01T10:00:00+00:00",
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi there"},
                ],
            },
            {
                "id": "sess-002",
                "platform": "claude",
                "created_at": "2026-09-02T11:00:00+00:00",
                "messages": [
                    {"role": "user", "content": "second session"},
                    {"role": "assistant", "content": "response"},
                ],
            },
        ]
        with zipfile.ZipFile(claude_zip, "w") as zf:
            for sess in sessions:
                zf.writestr(f"{sess['id']}.json", json.dumps(sess))

        # Also create chatgpt ZIP with 1 session
        gpt_zip = inbox / "chatgpt-export.zip"
        with zipfile.ZipFile(gpt_zip, "w") as zf:
            zf.writestr(
                "gpt-001.json",
                json.dumps(
                    {
                        "id": "gpt-001",
                        "platform": "chatgpt",
                        "created_at": "2026-09-03T12:00:00+00:00",
                        "messages": [{"role": "user", "content": "gpt hello"}],
                    }
                ),
            )

        connector = ChatsConnector(inbox_dir=inbox, corpus_root=corpus)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        # Should yield 3 payloads
        assert len(payloads) == 3
        # Check silos
        silos = {p.silo for p in payloads}
        assert "chats/claude" in silos
        assert "chats/chatgpt" in silos
        # Check source_ids
        ids = {p.source_id for p in payloads}
        assert "sess-001" in ids
        assert "gpt-001" in ids

        # Now test that writer would place them correctly (via connector's write path)
        # Simulate orchestrator writing
        from connectors.sdk.writer import write_unit

        for p in payloads:
            out = write_unit(p, corpus)
            assert out.exists()
            # Check silo subpath preserved
            assert out.parent == corpus / pathlib.Path(p.silo)
            text = out.read_text(encoding="utf-8")
            for field in ["source:", "silo:", "source_id:", "url:", "created_at:", "ingested_at:", "content_hash:"]:
                assert field in text
            assert "title:" not in text.lower()
            assert text.split("---\n", 2)[2].lstrip().startswith("> ")
            # Whole-session: body should contain both messages in one file, no split
            if p.source_id == "sess-001":
                assert "hello" in text
                assert "hi there" in text
                # Should be one file, not two
                assert (corpus / "chats" / "claude" / "sess-001.md").exists()


def test_chats_connector_long_session_remains_one_file():
    """ADR-0007: no connector-side split, QMD 900/135 owns chunking."""
    from connectors.chats import ChatsConnector
    import json, zipfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        inbox = tmp_path / "inbox"
        corpus = tmp_path / "corpus"
        inbox.mkdir()
        corpus.mkdir()

        # Create a long session with many messages (simulate 10k tokens)
        long_messages = []
        for i in range(50):
            long_messages.append({"role": "user", "content": f"message {i} " + "x" * 200})
            long_messages.append({"role": "assistant", "content": f"response {i} " + "y" * 200})

        sess = {
            "id": "long-sess",
            "platform": "claude",
            "created_at": "2026-09-01T00:00:00+00:00",
            "messages": long_messages,
        }
        zip_path = inbox / "claude-long.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("long-sess.json", json.dumps(sess))

        connector = ChatsConnector(inbox_dir=inbox, corpus_root=corpus)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads) == 1
        p = payloads[0]
        # Body should be large but still one payload
        assert len(p.body_markdown) > 10000
        # Writer should still create one file
        from connectors.sdk.writer import write_unit

        out = write_unit(p, corpus)
        assert out == corpus / "chats" / "claude" / "long-sess.md"
        assert out.exists()
        # No split files
        assert len(list((corpus / "chats" / "claude").glob("*.md"))) == 1
        # QMD would chunk, not connector


def test_chats_connector_frontmatter_and_summary():
    from connectors.chats import ChatsConnector
    import json, zipfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        inbox = tmp_path / "inbox"
        corpus = tmp_path / "corpus"
        inbox.mkdir()
        corpus.mkdir()

        sess = {
            "id": "sum-001",
            "platform": "gemini",
            "created_at": "2026-09-01T10:00:00+00:00",
            "messages": [
                {"role": "user", "content": "which OCR tool did I pick and why?"},
                {"role": "assistant", "content": "You picked LiteParse because local."},
            ],
        }
        zip_path = inbox / "gemini-export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("sum-001.json", json.dumps(sess))

        connector = ChatsConnector(inbox_dir=inbox, corpus_root=corpus)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads) == 1
        p = payloads[0]
        assert p.source == "chats"
        assert p.silo == "chats/gemini"
        assert p.source_id == "sum-001"
        assert p.summary  # Summary Line should be derived from first user message
        assert "OCR" in p.summary or "which OCR" in p.summary.lower()
        # Title should be derived
        assert p.title
        # Body should have alternating speaker sections
        assert "user" in p.body_markdown.lower() or "User:" in p.body_markdown
        assert "assistant" in p.body_markdown.lower() or "Assistant:" in p.body_markdown
