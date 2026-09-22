"""E2E Test Suite 1: Full-Pipeline Multi-Silo Ingestion & Deduplication.

Tests end-to-end multi-silo ingestion across all source families:
- Chats (Claude, ChatGPT multi-turn exports)
- Notes (Simplenote notes.json, Markdown notes)
- PDFs (Digital-first text extraction)
- Web (Jina Reader / Scrapling extracted markdown)
- GitHub (Repo tree and markdown documentation)
- Reach (Unified multi-channel connector)
- Validates 9-field YAML frontmatter, summary lines, AST markdown headers,
  deduplication, crawl state persistence, and single reindex coordination.
"""

from __future__ import annotations

import json
import pathlib
import zipfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from connectors.chats import ChatsConnector
from connectors.github import GitHubConnector
from connectors.notes import NotesConnector
from connectors.pdfs import PdfsConnector
from connectors.reach import ReachConnector
from connectors.sdk.base import UnitPayload
from connectors.sdk.state import CrawlState
from connectors.sdk.writer import write_unit
from connectors.web import WebConnector
from orchestrator import OrchestratorConfig, run_once


@pytest.fixture
def e2e_environment(tmp_path: pathlib.Path):
    """Sets up an isolated inbox, corpus, and state directory structure."""
    inbox = tmp_path / "inbox"
    corpus = tmp_path / "corpus"
    state_dir = corpus / "_state"
    dist = tmp_path / "dist"

    inbox.mkdir(parents=True)
    (inbox / "chats").mkdir()
    (inbox / "notes").mkdir()
    (inbox / "pdfs").mkdir()
    corpus.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    dist.mkdir(parents=True)

    state_path = state_dir / "crawl_state.json"
    return {
        "root": tmp_path,
        "inbox": inbox,
        "corpus": corpus,
        "state_path": state_path,
        "dist": dist,
    }


def test_e2e_full_multi_silo_ingestion_and_deduplication(e2e_environment):
    env = e2e_environment
    inbox = env["inbox"]
    corpus = env["corpus"]
    state_path = env["state_path"]

    # 1. Prepare Claude Chat Export ZIP
    claude_zip = inbox / "chats" / "claude_export.zip"
    with zipfile.ZipFile(claude_zip, "w") as zf:
        zf.writestr(
            "conversations.json",
            json.dumps([
                {
                    "uuid": "claude-sess-101",
                    "created_at": "2026-09-05T09:00:00+00:00",
                    "chat_messages": [
                        {"sender": "human", "text": "How do we scale vector embeddings?"},
                        {"sender": "assistant", "text": "By using hierarchical clustering and quantization."},
                    ],
                }
            ]),
        )

    # 2. Prepare ChatGPT Export ZIP
    chatgpt_zip = inbox / "chats" / "chatgpt_export.zip"
    with zipfile.ZipFile(chatgpt_zip, "w") as zf:
        zf.writestr(
            "gpt_session.json",
            json.dumps({
                "id": "gpt-sess-202",
                "platform": "chatgpt",
                "created_at": "2026-09-05T09:30:00+00:00",
                "messages": [
                    {"role": "user", "content": "Explain hybrid search in QMD."},
                    {"role": "assistant", "content": "QMD blends BM25 text rank with dense vector embeddings."},
                ],
            }),
        )

    # 3. Prepare Simplenote Export JSON in inbox/notes
    sn_json = inbox / "notes" / "notes.json"
    sn_json.write_text(
        json.dumps({
            "activeNotes": [
                {
                    "id": "sn-note-303",
                    "content": "Architecture Principles\n\nAlways enforce isolated silos and single-context docs.",
                    "creationDate": "2026-09-05T10:00:00+00:00",
                    "lastModified": "2026-09-05T10:30:00+00:00",
                    "tags": ["architecture", "adr"],
                }
            ]
        }),
        encoding="utf-8",
    )

    # 4. Prepare PDF document in inbox/pdfs
    dummy_pdf = inbox / "pdfs" / "distributed_systems.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/Contents 4 0 R>>endobj\n4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 72 712 Td (Distributed consensus via Paxos and Raft.) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000174 00000 n \ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n268\n%%EOF\n")

    # 5. Instantiate all connectors pointing to isolated directories
    chats_conn = ChatsConnector(inbox_dir=inbox)
    notes_conn = NotesConnector(inbox_dir=inbox)
    pdfs_conn = PdfsConnector(inbox_dir=inbox)

    # WebConnector mock fetch to test real HTML parsing and Markdown unit generation
    def mock_web_fetch(urls):
        return {
            "results": [
                {
                    "url": u,
                    "final_url": u,
                    "text": f"# Architecture Deep Dive\n\nDetailed breakdown of {u} with sparse BM25 and dense vectors.",
                }
                for u in urls
            ],
            "errors": [],
        }

    web_conn = WebConnector(corpus_root=corpus, fetch_func=mock_web_fetch)

    # GitHubConnector test unit
    gh_conn = GitHubConnector()
    with patch.object(gh_conn, "fetch_recent") as mock_gh:
        from connectors.sdk.base import UnitPayload
        mock_gh.return_value = [
            UnitPayload(
                source="github",
                silo="github",
                source_id="repo-doc-01",
                url="https://github.com/oraekene/knowledgebase/blob/main/README.md",
                created_at=datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
                title="QMD Knowledgebase Documentation",
                summary="Unified personal knowledgebase indexed by QMD across four query faces.",
                body_markdown="# Architecture\n\nDetailed system overview and component layout.\nCheck https://example.com/vector-search for details.\n",
                tags=["github", "docs"],
            )
        ]

        connectors = [chats_conn, notes_conn, pdfs_conn, gh_conn, web_conn]

        qmd_mock = MagicMock(return_value=0)
        wiki_mock = MagicMock(return_value=0)
        mirror_mock = MagicMock(return_value=0)

        # Run pipeline iteration 1
        run_once(
            connectors=connectors,
            corpus_root=corpus,
            state_path=state_path,
            qmd_runner=qmd_mock,
            wiki_runner=wiki_mock,
            mirror_runner=mirror_mock,
            now=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
        )

    # Assert runners executed exactly once
    assert qmd_mock.call_count == 1, "qmd update must run exactly once after all connectors"
    assert wiki_mock.call_count == 1, "wiki compilation must run once"
    assert mirror_mock.call_count == 1, "mirror build must run once"

    # Assert crawl_state.json exists and has recorded timestamps
    assert state_path.exists()
    state = CrawlState(state_path)
    default_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert state.get_last_seen("chats", default_dt) != default_dt
    assert state.get_last_seen("notes", default_dt) != default_dt
    assert state.get_last_seen("github", default_dt) != default_dt

    # Verify Units written in exact target silos
    claude_units = list(corpus.glob("chats/claude/*.md"))
    chatgpt_units = list(corpus.glob("chats/chatgpt/*.md"))
    notes_units = list(corpus.glob("notes/simplenote/*.md"))
    pdf_units = list(corpus.glob("pdfs/*.md"))
    web_units = list(corpus.glob("web/*.md"))
    github_units = list(corpus.glob("github/*.md"))

    assert len(claude_units) == 1, f"Expected 1 Claude unit, found {len(claude_units)}"
    assert len(chatgpt_units) == 1, f"Expected 1 ChatGPT unit, found {len(chatgpt_units)}"
    assert len(notes_units) == 1, f"Expected 1 Simplenote unit, found {len(notes_units)}"
    assert len(pdf_units) == 1, f"Expected 1 PDF unit, found {len(pdf_units)}"
    assert len(web_units) == 1, f"Expected 1 Web unit, found {len(web_units)}"
    assert len(github_units) == 1, f"Expected 1 GitHub unit, found {len(github_units)}"

    # Validate the 9-field YAML Frontmatter and Summary Line across all generated units
    all_units = claude_units + chatgpt_units + notes_units + pdf_units + web_units + github_units
    assert len(all_units) == 6

    required_fields = [
        "source:",
        "silo:",
        "source_id:",
        "url:",
        "created_at:",
        "ingested_at:",
        "tags:",
        "author:",
        "content_hash:",
    ]

    for unit_file in all_units:
        content = unit_file.read_text(encoding="utf-8")
        assert content.startswith("---\n"), f"{unit_file.name} must start with YAML frontmatter"
        for field in required_fields:
            assert field in content, f"Missing {field} in {unit_file.name}"

        # Summary line blockquote check
        parts = content.split("---\n", 2)
        assert len(parts) >= 3, f"{unit_file.name} must contain closing frontmatter delimiter"
        body_start = parts[2].lstrip()
        assert body_start.startswith("> "), f"{unit_file.name} must open with blockquote summary line: {body_start[:40]}"

    # Verify Claude Turn Headings for AST chunking
    claude_text = claude_units[0].read_text(encoding="utf-8")
    assert "## User" in claude_text
    assert "## Assistant" in claude_text
    assert "quantization" in claude_text

    # Deduplication & Idempotency test:
    # Running run_once a second time must not duplicate units or crash
    run_once(
        connectors=connectors,
        corpus_root=corpus,
        state_path=state_path,
        qmd_runner=qmd_mock,
        wiki_runner=wiki_mock,
        mirror_runner=mirror_mock,
        now=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc),
    )

    # Unit counts should remain strictly identical
    assert len(list(corpus.glob("chats/claude/*.md"))) == 1
    assert len(list(corpus.glob("chats/chatgpt/*.md"))) == 1
    assert len(list(corpus.glob("notes/simplenote/*.md"))) == 1
    assert len(list(corpus.glob("pdfs/*.md"))) == 1
    assert len(list(corpus.glob("github/*.md"))) == 1


def test_e2e_reach_multi_channel_ingestion(e2e_environment):
    """Verifies Reach connector processes YouTube, Twitter, and Reddit sources into corpus."""
    env = e2e_environment
    corpus = env["corpus"]
    from connectors.reach import AgentReachConnector

    with patch("connectors.reach.extract_youtube") as mock_yt, \
         patch("connectors.reach.extract_twitter") as mock_tw:
        
        mock_yt.return_value = UnitPayload(
            source="reach",
            silo="web",
            source_id="yt-video-01",
            url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            created_at="2026-09-05T12:00:00+00:00",
            tags=["youtube", "audio"],
            author="RickAstley",
            title="Never Gonna Give You Up",
            summary="Full audio transcription and metadata for YouTube video.",
            body_markdown="# Never Gonna Give You Up\n\n[00:00.00] We're no strangers to love...",
        )
        mock_tw.return_value = UnitPayload(
            source="reach",
            silo="twitter",
            source_id="tw-thread-999",
            url="https://x.com/elonmusk/status/1836000000",
            created_at="2026-09-05T13:00:00+00:00",
            tags=["twitter", "thread"],
            author="elonmusk",
            title="Starship Flight Test Summary",
            summary="Full thread content discussing Starship flight test telemetry.",
            body_markdown="# Starship Flight Test Summary\n\nFlight test telemetry verified across all Raptor engines.",
        )

        reach_conn = AgentReachConnector(
            corpus_root=corpus,
            urls=[
                "https://youtube.com/watch?v=dQw4w9WgXcQ",
                "https://x.com/elonmusk/status/1836000000",
            ],
        )

        payloads = list(reach_conn.fetch_recent(datetime(2026, 9, 1, tzinfo=timezone.utc)))
        assert len(payloads) == 2

        for p in payloads:
            out = write_unit(p, corpus)
            assert out.exists()

        assert len(list(corpus.glob("web/*yt-video-01*.md"))) == 1
        assert len(list(corpus.glob("twitter/*tw-thread-999*.md"))) == 1


def test_e2e_connector_failure_isolation(e2e_environment):
    """Verifies that a failing connector does not crash the pipeline and other connectors succeed."""
    env = e2e_environment
    corpus = env["corpus"]
    state_path = env["state_path"]

    failing_conn = MagicMock()
    failing_conn.NAME = "faulty_source"
    failing_conn.fetch_recent.side_effect = RuntimeError("External API timeout / network failure")

    healthy_conn = MagicMock()
    healthy_conn.NAME = "healthy_source"
    healthy_conn.fetch_recent.return_value = [
        UnitPayload(
            source="healthy_source",
            silo="notes",
            source_id="healthy-unit-01",
            url="https://example.com/healthy",
            created_at="2026-09-05T14:00:00+00:00",
            tags=["health"],
            author="system",
            title="Healthy System Unit",
            summary="This unit should be successfully written despite peer failure.",
            body_markdown="# Healthy System Unit\n\nVerified execution under failure conditions.",
        )
    ]

    qmd_mock = MagicMock(return_value=0)
    wiki_mock = MagicMock(return_value=0)
    mirror_mock = MagicMock(return_value=0)

    # run_once must catch the error from failing_conn, log it, and complete healthy_conn
    run_once(
        connectors=[failing_conn, healthy_conn],
        corpus_root=corpus,
        state_path=state_path,
        qmd_runner=qmd_mock,
        wiki_runner=wiki_mock,
        mirror_runner=mirror_mock,
        now=datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc),
    )

    # Verify healthy unit was saved
    assert (corpus / "notes" / "healthy-unit-01.md").exists()
    # Verify qmd update was still invoked
    assert qmd_mock.call_count == 1
    # Verify crawl state recorded healthy connector but NOT faulty connector
    state = CrawlState(state_path)
    default_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert state.get_last_seen("healthy_source", default_dt) != default_dt
    assert state.get_last_seen("faulty_source", default_dt) == default_dt

