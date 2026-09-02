import pathlib
import tempfile
import zipfile
import json
import pytest
from datetime import datetime, timezone

# Seam: Chat Inbox connector — ZIP drops -> Units in corpus/chats/{platform}/, whole-session, 9-field Frontmatter
# Per #16 + spec.md:109-111 + #9 per-silo templates + ADR-0007 (no connector split)


@pytest.fixture
def tmp_inbox_corpus(tmp_path):
    inbox = tmp_path / "inbox"
    corpus = tmp_path / "corpus"
    inbox.mkdir()
    corpus.mkdir()
    return inbox, corpus


def _make_zip(inbox: pathlib.Path, zip_name: str, sessions: list[dict]):
    zip_path = inbox / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        for sess in sessions:
            zf.writestr(f"{sess['id']}.json", json.dumps(sess, ensure_ascii=False))
    return zip_path


def test_chats_connector_zip_yields_units_in_correct_silo(tmp_inbox_corpus):
    inbox, corpus = tmp_inbox_corpus
    from connectors.chats import ChatsConnector
    from connectors.sdk.writer import write_unit

    _make_zip(
        inbox,
        "claude-export.zip",
        [
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
        ],
    )
    _make_zip(
        inbox,
        "chatgpt-export.zip",
        [
            {
                "id": "gpt-001",
                "platform": "chatgpt",
                "created_at": "2026-09-03T12:00:00+00:00",
                "messages": [{"role": "user", "content": "gpt hello"}],
            }
        ],
    )

    connector = ChatsConnector(inbox_dir=inbox)
    payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
    assert len(payloads) == 3
    silos = {p.silo for p in payloads}
    assert "chats/claude" in silos
    assert "chats/chatgpt" in silos
    ids = {p.source_id for p in payloads}
    assert "sess-001" in ids
    assert "gpt-001" in ids

    for p in payloads:
        out = write_unit(p, corpus)
        assert out.exists()
        assert out.parent == corpus / pathlib.Path(p.silo)
        text = out.read_text(encoding="utf-8")
        for field in ["source:", "silo:", "source_id:", "url:", "created_at:", "ingested_at:", "tags:", "author:", "content_hash:"]:
            assert field in text, f"missing {field} for {p.source_id}"
        assert "tags: [claude]" in text or "tags: [chatgpt]" in text
        assert "author:" in text
        assert "title:" not in text.lower()
        assert text.split("---\n", 2)[2].lstrip().startswith("> ")
        if p.source_id == "sess-001":
            assert "hello" in text
            assert "hi there" in text
            assert (corpus / "chats" / "claude" / "sess-001.md").exists()


def test_chats_connector_long_session_remains_one_file(tmp_inbox_corpus):
    """ADR-0007: no connector-side split, QMD 900/135 owns chunking."""
    inbox, corpus = tmp_inbox_corpus
    from connectors.chats import ChatsConnector
    from connectors.sdk.writer import write_unit

    long_messages = []
    for i in range(50):
        long_messages.append({"role": "user", "content": f"message {i} " + "x" * 200})
        long_messages.append({"role": "assistant", "content": f"response {i} " + "y" * 200})

    _make_zip(
        inbox,
        "claude-long.zip",
        [
            {
                "id": "long-sess",
                "platform": "claude",
                "created_at": "2026-09-01T00:00:00+00:00",
                "messages": long_messages,
            }
        ],
    )

    connector = ChatsConnector(inbox_dir=inbox)
    payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
    assert len(payloads) == 1
    p = payloads[0]
    assert len(p.body_markdown) > 10000
    out = write_unit(p, corpus)
    assert out == corpus / "chats" / "claude" / "long-sess.md"
    assert out.exists()
    assert len(list((corpus / "chats" / "claude").glob("*.md"))) == 1
    # Body should use heading sections for AST-aware chunking
    text = out.read_text(encoding="utf-8")
    assert "## User" in text
    assert "## Assistant" in text


def test_chats_connector_frontmatter_and_summary(tmp_inbox_corpus):
    inbox, corpus = tmp_inbox_corpus
    from connectors.chats import ChatsConnector
    from connectors.sdk.writer import write_unit

    _make_zip(
        inbox,
        "gemini-export.zip",
        [
            {
                "id": "sum-001",
                "platform": "gemini",
                "created_at": "2026-09-01T10:00:00+00:00",
                "messages": [
                    {"role": "user", "content": "which OCR tool did I pick and why?"},
                    {"role": "assistant", "content": "You picked LiteParse because local."},
                ],
            }
        ],
    )

    connector = ChatsConnector(inbox_dir=inbox)
    payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
    assert len(payloads) == 1
    p = payloads[0]
    assert p.source == "chats"
    assert p.silo == "chats/gemini"
    assert p.source_id == "sum-001"
    assert "OCR" in p.summary
    # Title derived from first user prompt, not sess_id
    assert "ocr" in p.title.lower()
    assert p.title != "sum-001"
    assert "tags: [gemini]" in write_unit(p, corpus).read_text(encoding="utf-8")
    # Body uses heading sections, not bold
    assert "## User" in p.body_markdown
    assert "## Assistant" in p.body_markdown
    assert "**User:**" not in p.body_markdown


def test_chats_connector_rejects_unknown_platform(tmp_inbox_corpus):
    inbox, corpus = tmp_inbox_corpus
    from connectors.chats import ChatsConnector

    _make_zip(
        inbox,
        "unknown-export.zip",
        [
            {
                "id": "unk-001",
                "platform": "unknown_platform_xyz",
                "created_at": "2026-09-01T00:00:00+00:00",
                "messages": [{"role": "user", "content": "hello"}],
            }
        ],
    )
    connector = ChatsConnector(inbox_dir=inbox)
    payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
    # Should skip unknown platform instead of misattributing to claude
    assert len(payloads) == 0


def test_chats_connector_qmd_scoped_search(tmp_inbox_corpus):
    """Search scoping: qmd query --collection chats vs chats/claude — file-level + BM25 proof.

    Simulates what `qmd query --collection chats` vs `chats/claude` would do via fastGlob + BM25.
    """
    inbox, corpus = tmp_inbox_corpus
    from connectors.chats import ChatsConnector
    from connectors.sdk.writer import write_unit
    import re

    def simple_score(query: str, text: str) -> int:
        return len(re.findall(rf"\b{re.escape(query.lower())}\b", text.lower()))

    # Create claude and chatgpt sessions with distinct terms
    _make_zip(
        inbox,
        "claude-export.zip",
        [
            {
                "id": "c1",
                "platform": "claude",
                "created_at": "2026-09-01T00:00:00+00:00",
                "messages": [{"role": "user", "content": "hello from claude with term claudeterm"}],
            }
        ],
    )
    _make_zip(
        inbox,
        "chatgpt-export.zip",
        [
            {
                "id": "g1",
                "platform": "chatgpt",
                "created_at": "2026-09-01T00:00:00+00:00",
                "messages": [{"role": "user", "content": "hello from chatgpt with term gptterm"}],
            }
        ],
    )
    connector = ChatsConnector(inbox_dir=inbox)
    payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
    for p in payloads:
        write_unit(p, corpus)

    # fastGlob simulation
    chats_files = list(corpus.glob("chats/**/*.md"))
    claude_files = list(corpus.glob("chats/claude/**/*.md"))
    chatgpt_files = list(corpus.glob("chats/chatgpt/**/*.md"))
    assert len(chats_files) == 2
    assert len(claude_files) == 1
    assert len(chatgpt_files) == 1
    assert any("c1" in f.name for f in claude_files)
    assert any("g1" in f.name for f in chatgpt_files)

    # BM25 scoped: query claudeterm should rank claude file top in chats/claude, not in chatgpt
    def rank(query, files):
        scored = [(simple_score(query, f.read_text(encoding="utf-8")), f) for f in files]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    # Scoped to chats/claude
    ranked_claude = rank("claudeterm", claude_files)
    assert ranked_claude[0][0] > 0
    # Scoped to chats/chatgpt should not find claudeterm
    ranked_gpt = rank("claudeterm", chatgpt_files)
    assert ranked_gpt[0][0] == 0
    # Unified chats should find both, but claudeterm top is c1
    ranked_unified = rank("claudeterm", chats_files)
    assert ranked_unified[0][1].name == "c1.md"
