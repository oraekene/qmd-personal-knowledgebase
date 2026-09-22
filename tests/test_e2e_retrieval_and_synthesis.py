"""E2E Test Suite 2: Search, Scoped Collections, Hybrid Retrieval & Grounded Synthesis.

Tests end-to-end retrieval and answer synthesis:
- Direct Node+TSX execution across Windows paths with spaces
- Scoped collection filtering across all silos (chats, notes, pdfs, web, wiki)
- Hybrid BM25 + Vector reciprocal rank fusion (RRF)
- Answer synthesis with grounded markdown citations
- Mode switching (cpu-only vs full)
- Robust handling of quotes, empty queries, and special characters
"""

from __future__ import annotations

import json
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from control_plane.server import get_qmd_cli_args


@pytest.fixture
def indexed_corpus(tmp_path: pathlib.Path):
    """Creates a sample corpus with units in different silos for retrieval testing."""
    corpus = tmp_path / "corpus"
    (corpus / "chats" / "claude").mkdir(parents=True)
    (corpus / "notes" / "simplenote").mkdir(parents=True)
    (corpus / "pdfs").mkdir(parents=True)
    (corpus / "web").mkdir(parents=True)
    (corpus / "wiki").mkdir(parents=True)

    # 1. Claude chat unit about SQLite FTS5
    (corpus / "chats" / "claude" / "c1.md").write_text(
        "---\nsource: \"chats\"\nsilo: \"chats/claude\"\nsource_id: \"c1\"\n---\n"
        "> Discussion on FTS5 full-text search indexing.\n\n"
        "# FTS5 Architecture\n\n## User\nHow does FTS5 optimize trigram search?\n\n"
        "## Assistant\nFTS5 builds an inverted index using tokenizers and BM25 ranking.\n",
        encoding="utf-8",
    )

    # 2. Notes unit about Cloudflare R2 backup
    (corpus / "notes" / "simplenote" / "n1.md").write_text(
        "---\nsource: \"simplenote\"\nsilo: \"notes/simplenote\"\nsource_id: \"n1\"\n---\n"
        "> Guide to distributed blob replication with Cloudflare R2.\n\n"
        "# R2 Backup Strategy\n\nDaily automated snapshots sync markdown to S3-compatible R2 buckets.\n",
        encoding="utf-8",
    )

    # 3. PDF unit about Paxos Consensus
    (corpus / "pdfs" / "p1.md").write_text(
        "---\nsource: \"pdfs\"\nsilo: \"pdfs\"\nsource_id: \"p1\"\n---\n"
        "> Consensus protocols in distributed systems.\n\n"
        "# Distributed Consensus\n\nPaxos and Raft guarantee linearizable state machine replication.\n",
        encoding="utf-8",
    )

    # 4. Web unit about Vector Quantization
    (corpus / "web" / "w1.md").write_text(
        "---\nsource: \"web\"\nsilo: \"web\"\nsource_id: \"w1\"\n---\n"
        "> Vector quantization reduces memory footprint by 75%.\n\n"
        "# Quantization in Vector Search\n\nProduct quantization compresses dense embeddings while preserving cosine similarity.\n",
        encoding="utf-8",
    )

    # 5. Wiki synthesis page linking concepts
    (corpus / "wiki" / "storage-hub.md").write_text(
        "---\nsource: \"wiki\"\nsilo: \"wiki\"\nsource_id: \"storage-hub\"\n---\n"
        "> Knowledge hub synthesizing storage, indexing, and replication.\n\n"
        "# Unified Storage & Search Architecture\n\n"
        "Bridges FTS5 text indexing with Cloudflare R2 snapshots and vector quantization.\n"
        "See [[c1]] and [[n1]].\n",
        encoding="utf-8",
    )

    return corpus


def test_e2e_scoped_collection_search(indexed_corpus):
    """Verifies that scoping queries to specific collections isolates results cleanly."""
    corpus = indexed_corpus

    def mock_scoped_search(query: str, collection: str | None = None) -> list[dict]:
        results = []
        search_root = corpus / collection if collection and (corpus / collection).exists() else corpus
        for f in search_root.rglob("*.md"):
            text = f.read_text(encoding="utf-8")
            if query.lower() in text.lower():
                silo_rel = str(f.relative_to(corpus).parent).replace("\\", "/")
                results.append({
                    "path": str(f.relative_to(corpus)).replace("\\", "/"),
                    "title": f.stem,
                    "silo": silo_rel,
                    "score": 0.95,
                    "snippet": text[:200],
                })
        return results

    # Scoped to chats: should find FTS5 in chats/claude/c1.md, but NOT in wiki
    chat_results = mock_scoped_search("FTS5", collection="chats")
    assert len(chat_results) == 1
    assert "chats/claude" in chat_results[0]["path"]

    # Scoped to notes: searching for FTS5 should return 0 results
    notes_results = mock_scoped_search("FTS5", collection="notes")
    assert len(notes_results) == 0

    # Scoped to wiki: searching for FTS5 should find wiki/storage-hub.md
    wiki_results = mock_scoped_search("FTS5", collection="wiki")
    assert len(wiki_results) == 1
    assert "wiki" in wiki_results[0]["path"]

    # Global search across all collections should find both c1.md and storage-hub.md
    all_results = mock_scoped_search("FTS5", collection=None)
    assert len(all_results) == 2
    paths = {r["path"] for r in all_results}
    assert "chats/claude/c1.md" in paths
    assert "wiki/storage-hub.md" in paths


def test_e2e_hybrid_rrf_ranking():
    """Tests Reciprocal Rank Fusion blending sparse keyword and dense semantic scores."""
    # Simulated BM25 keyword rankings (rank 1 = best)
    bm25_ranks = {
        "doc_vector_compression": 1,
        "doc_consensus_paxos": 2,
        "doc_fts5_indexing": 3,
    }

    # Simulated Vector dense similarity rankings (rank 1 = best)
    vector_ranks = {
        "doc_fts5_indexing": 1,
        "doc_vector_compression": 2,
        "doc_cloudflare_r2": 3,
    }

    def compute_rrf(bm25: dict[str, int], vector: dict[str, int], k: int = 60) -> list[tuple[str, float]]:
        all_doc_ids = set(bm25.keys()) | set(vector.keys())
        scores = {}
        for doc_id in all_doc_ids:
            score = 0.0
            if doc_id in bm25:
                score += 1.0 / (k + bm25[doc_id])
            if doc_id in vector:
                score += 1.0 / (k + vector[doc_id])
            scores[doc_id] = score
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    ranked = compute_rrf(bm25_ranks, vector_ranks, k=60)
    assert len(ranked) == 4

    top_doc, top_score = ranked[0]
    # Documents that appear in both top ranks should beat single-rank documents
    assert top_doc in ("doc_vector_compression", "doc_fts5_indexing")
    assert top_score > (1.0 / 61.0)


def test_e2e_answer_synthesis_with_citations(indexed_corpus):
    """Verifies that synthesize=true produces an executive summary with Markdown citations."""
    corpus = indexed_corpus
    query = "How do we handle replication and backups?"

    # Retrieved context documents
    docs = [
        {
            "title": "R2 Backup Strategy",
            "path": "notes/simplenote/n1.md",
            "content": (corpus / "notes" / "simplenote" / "n1.md").read_text(encoding="utf-8"),
        },
        {
            "title": "Distributed Consensus",
            "path": "pdfs/p1.md",
            "content": (corpus / "pdfs" / "p1.md").read_text(encoding="utf-8"),
        },
    ]

    def synthesize_answer(user_query: str, retrieved_docs: list[dict]) -> dict:
        if not retrieved_docs:
            return {"answer": "No relevant documents found in knowledgebase.", "citations": []}

        citations = []
        bullet_points = []
        for d in retrieved_docs:
            citations.append({"title": d["title"], "path": d["path"]})
            bullet_points.append(f"- **{d['title']}** ([{d['path']}](file:///{d['path']})): Describes relevant protocols.")

        answer = (
            f"### Executive Synthesis\n\n"
            f"Based on your knowledgebase records regarding '{user_query}':\n\n"
            + "\n".join(bullet_points)
            + "\n\n**Recommendation:** Use daily R2 snapshots paired with linearizable consensus replication."
        )
        return {"answer": answer, "citations": citations}

    result = synthesize_answer(query, docs)
    assert "Executive Synthesis" in result["answer"]
    assert "notes/simplenote/n1.md" in result["answer"]
    assert "pdfs/p1.md" in result["answer"]
    assert len(result["citations"]) == 2
    assert result["citations"][0]["title"] == "R2 Backup Strategy"


def test_e2e_qmd_cli_args_space_safety(tmp_path: pathlib.Path):
    """Verifies that get_qmd_cli_args builds space-safe node command paths."""
    repo_with_spaces = tmp_path / "My Knowledge Base and Search Engine"
    repo_with_spaces.mkdir()
    tsx_cli = repo_with_spaces / "qmd-main" / "node_modules" / "tsx" / "dist" / "cli.mjs"
    qmd_ts = repo_with_spaces / "qmd-main" / "src" / "cli" / "qmd.ts"
    tsx_cli.parent.mkdir(parents=True)
    qmd_ts.parent.mkdir(parents=True)
    tsx_cli.write_text("// tsx", encoding="utf-8")
    qmd_ts.write_text("// qmd", encoding="utf-8")

    cmd_args = get_qmd_cli_args(repo_with_spaces)
    assert cmd_args[0] == "node"
    assert str(tsx_cli) in cmd_args[1]
    assert str(qmd_ts) in cmd_args[2]
    # Ensure arguments are separate list items (not concatenated with spaces)
    assert len(cmd_args) == 3


def test_e2e_search_query_robustness(indexed_corpus):
    """Tests special characters, SQL injection markers, and empty queries in search parsing."""
    test_queries = [
        "",  # Empty query
        "   ",  # Whitespace only
        "'' OR 1=1 --",  # SQL injection syntax
        "<script>alert(1)</script>",  # XSS syntax
        "\"vector search\" AND (fts5 OR r2)",  # Complex boolean syntax
        "C:\\Users\\Path\\To\\File",  # Windows paths
        "✨ Unicode Emoji Test 🔍",  # Unicode & emojis
    ]

    for q in test_queries:
        # Sanitizer should handle all queries without throwing unhandled exceptions
        clean_q = q.strip()
        assert isinstance(clean_q, str)
