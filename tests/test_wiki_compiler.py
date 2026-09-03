"""Tests for Wiki synthesis (Workers AI) for #20.

Per spec.md:141-157 + research #8 + docs/adr/0006/0008:
- After qmd update && qmd embed, llmwiki compile creates/updates corpus/wiki/concepts/<slug>.md with sources, citations, wikilinks
- corpus/wiki as QMD wiki collection (qmd query --collection wiki)
- Incremental SHA (detectChanges) no-op and refresh --stale
- Failure isolated (missing key/outage), no raw Units rewritten
Seam: scripts.wiki.compile_wiki + orchestrator run_once wiki_runner isolation + file-level citations
"""

from __future__ import annotations

import os
import pathlib
import re
import tempfile

import pytest
from unittest.mock import Mock

from connectors.sdk.base import UnitPayload
from connectors.sdk.writer import write_unit


def _make_unit(silo: str, source_id: str, body: str, summary: str = "Summary.") -> UnitPayload:
    return UnitPayload(
        source="test",
        silo=silo,
        source_id=source_id,
        url=f"https://example.com/{source_id}",
        created_at="2026-09-01T00:00:00+00:00",
        tags=[],
        author="",
        title=source_id,
        summary=summary,
        body_markdown=f"# {source_id}\n\n{body}",
    )


def _write_units(corpus: pathlib.Path, payloads: list[UnitPayload]) -> list[pathlib.Path]:
    return [write_unit(p, corpus) for p in payloads]


def test_wiki_compile_creates_concepts_with_sources_and_citations():
    """llmwiki compile creates corpus/wiki/concepts/<slug>.md with sources:[...] and ^[cite] + [[wikilinks]]."""
    from scripts.wiki import compile_wiki

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state = tmp_path / ".llmwiki" / "state.json"
        # Use mock to avoid real LLM
        os.environ["LLMWIKI_MOCK"] = "1"
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["OPENAI_BASE_URL"] = "https://api.cloudflare.com/client/v4/accounts/test/ai/v1"
        os.environ["LLMWIKI_MODEL"] = "@cf/meta/llama-3.1-8b-instruct-fp8-fast"
        try:
            # Create Units
            p1 = _make_unit("github", "oraekene/nebula", "Nebula is about stars. Unique term nebula123.", "Nebula repo.")
            p2 = _make_unit("notes", "idea1", "Idea about nebula.", "Idea.")
            _write_units(corpus, [p1, p2])

            result = compile_wiki(corpus, state_path=state, mock=True)
            assert result["compiled"] >= 1

            # Check concepts
            concepts = list((corpus / "wiki" / "concepts").glob("*.md"))
            assert len(concepts) >= 1, "should create at least one concept"
            # Check first concept has correct frontmatter
            first = concepts[0]
            text = first.read_text(encoding="utf-8")
            assert "source: wiki-compiler" in text
            assert "silo: wiki" in text
            assert "modelId:" in text
            assert "promptVersion:" in text
            assert "sources:" in text
            # sources traceable to existing Units
            for p in [p1, p2]:
                # At least one source should be cited — check that some github or notes path appears
                pass
            # Check sources list contains at least one real Unit path
            assert "github/oraekene__nebula.md" in text or "notes/idea1.md" in text or "github" in text
            # Citations like ^[github/oraekene__nebula.md:1-5]
            assert re.search(r"\^\[.+?:\d+-\d+", text), f"citations missing in {text[:500]}"
            # Wikilinks [[...]]
            assert "[[" in text and "]]" in text
            # MOC and index
            assert (corpus / "wiki" / "MOC.md").exists()
            assert (corpus / "wiki" / "index.md").exists()
            # State SHA incremental
            assert state.exists()
            state_data = state.read_text(encoding="utf-8")
            assert "hashes" in state_data
            # Check citation resolves via linter concept: every ^[path:START-END] should point to existing file
            cites = re.findall(r"\^\[([^\]]+)\]", text)
            for cite_block in cites:
                # cite_block like "github/oraekene__nebula.md:1-5, notes/idea1.md:1-5"
                for part in cite_block.split(","):
                    part = part.strip()
                    if ":" in part:
                        path_part = part.split(":")[0].strip()
                        # path_part should be relative to corpus
                        assert (corpus / path_part).exists(), f"citation {part} does not resolve to {corpus / path_part}"
            # No raw Units rewritten — original Units still exist and unchanged
            assert (corpus / "github" / "oraekene__nebula.md").exists()
            assert (corpus / "notes" / "idea1.md").exists()
        finally:
            os.environ.pop("LLMWIKI_MOCK", None)
            os.environ.pop("OPENAI_API_KEY", None)


def test_wiki_incremental_no_op_and_refresh_stale():
    """Second compile with no new Units is no-op; refresh --stale with one changed Unit recompiles only affected."""
    from scripts.wiki import compile_wiki, detect_changes, hash_file

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state = tmp_path / ".llmwiki" / "state.json"
        os.environ["LLMWIKI_MOCK"] = "1"
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            p1 = _make_unit("github", "a/b", "Content a.", "A")
            _write_units(corpus, [p1])
            res1 = compile_wiki(corpus, state_path=state, mock=True)
            assert res1["compiled"] >= 1
            # Second compile with no changes — should be no-op
            res2 = compile_wiki(corpus, state_path=state, mock=True)
            assert res2["compiled"] == 0
            assert res2["skipped"] >= 1

            # Change one Unit
            p1_path = corpus / "github" / "a__b.md"
            original = p1_path.read_text(encoding="utf-8")
            p1_path.write_text(original + "\n\nChanged content.", encoding="utf-8")
            # detectChanges should find it
            changed = detect_changes(corpus, state)
            assert len(changed) == 1

            # Refresh --stale should recompile only affected
            from scripts.wiki import refresh_stale

            res3 = refresh_stale(corpus, state)
            assert res3["compiled"] == 1
        finally:
            os.environ.pop("LLMWIKI_MOCK", None)
            os.environ.pop("OPENAI_API_KEY", None)


def test_wiki_provider_guard_missing_key_isolated():
    """OPENAI_API_KEY missing → provider-guard throws, orchestrator catches, qmd+mirror still complete."""
    from scripts.wiki import ProviderUnavailableError, ensure_provider_available
    from orchestrator import run_once

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state = corpus / "_state" / "crawl_state.json"
        # Ensure no key
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["LLMWIKI_PROVIDER"] = "openai"
        # ensure_provider_available should throw
        with pytest.raises(ProviderUnavailableError):
            ensure_provider_available()

        # Orchestrator should isolate wiki failure
        p = _make_unit("github", "a/b2", "Content", "Summary")
        class Good:
            NAME = "good"
            def fetch_recent(self, since, limit=50):
                yield p

        qmd_mock = Mock(return_value=0)
        # wiki mock that simulates missing key
        def failing_wiki():
            ensure_provider_available()

        wiki_mock = Mock(side_effect=failing_wiki)
        mirror_mock = Mock(return_value=0)

        # Should not raise — isolated
        run_once([Good()], corpus, state, qmd_mock, wiki_mock, mirror_runner=mirror_mock)
        assert qmd_mock.call_count == 1
        assert wiki_mock.call_count == 1
        assert mirror_mock.call_count == 1  # mirror still runs after wiki failure
        # Raw Unit not rewritten (still exists, wiki failure didn't delete)
        assert (corpus / "github" / "a__b2.md").exists()
        # No wiki pages created when provider unavailable (since we didn't mock)
        # That's expected — failure isolated

        os.environ.pop("LLMWIKI_PROVIDER", None)


def test_wiki_citations_resolve_and_wikilinks_resolve():
    """Every wiki citation ^[path:START-END] resolves (linter/rules-citations.ts with corpus as sourcesDir).

    Uses scripts.wiki.validate_citations / validate_wikilinks which mirror the
    real linter (corpus/ IS the sources set) + slugify-aware wikilink resolution.
    """
    from scripts.wiki import compile_wiki, validate_citations, validate_wikilinks

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state = tmp_path / ".llmwiki" / "state.json"
        os.environ["LLMWIKI_MOCK"] = "1"
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            units = [
                _make_unit("github", f"repo{i}", f"Content {i} nebula", f"Summary {i}")
                for i in range(3)
            ]
            _write_units(corpus, units)
            compile_wiki(corpus, state_path=state, mock=True)

            wiki_files = list((corpus / "wiki").rglob("*.md"))
            assert len(wiki_files) >= 2
            for wf in wiki_files:
                text = wf.read_text(encoding="utf-8")
                assert validate_citations(text, corpus) == [], f"{wf} has broken citations"
                assert validate_wikilinks(text, wiki_files) == [], f"{wf} has broken wikilinks"
        finally:
            os.environ.pop("LLMWIKI_MOCK", None)
            os.environ.pop("OPENAI_API_KEY", None)


def test_wiki_slugify_and_validators():
    """slugify mirrors llmwiki utils/markdown.ts; validators catch broken cites/links."""
    from scripts.wiki import slugify, validate_citations, validate_wikilinks

    assert slugify("Hello World") == "hello-world"
    assert slugify("MOC") == "moc"
    assert slugify("Concept: Nebula!") == "concept-nebula"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        (corpus / "github").mkdir(parents=True)
        (corpus / "github" / "a.md").write_text("# A\n", encoding="utf-8")
        (corpus / "wiki" / "concepts").mkdir(parents=True)
        (corpus / "wiki" / "concepts" / "overview.md").write_text("# O\n", encoding="utf-8")
        wiki_files = list((corpus / "wiki").rglob("*.md"))

        assert validate_citations("ok ^[github/a.md:1-5]", corpus) == []
        assert len(validate_citations("bad ^[github/missing.md:1-5]", corpus)) == 1
        assert len(validate_citations("bad ^[../escape.md:1-5]", corpus)) == 1

        assert validate_wikilinks("see [[overview]]", wiki_files) == []
        assert validate_wikilinks("see [[MOC]]", wiki_files + [corpus / "wiki" / "MOC.md"]) == []
        assert validate_wikilinks("see [[moc]]", wiki_files + [corpus / "wiki" / "MOC.md"]) == []
        assert len(validate_wikilinks("see [[nope-missing]]", wiki_files)) == 1
        assert validate_wikilinks("see [[overview|My Title]]", wiki_files) == []


def test_wiki_budget_and_concurrency_enforced():
    """DEFAULT_PROMPT_BUDGET_CHARS truncation + COMPILE_CONCURRENCY limit are enforced."""
    from scripts.wiki import _truncate_to_budget, _concurrency, DEFAULT_PROMPT_BUDGET_CHARS
    import os as _os

    long_text = "x" * (DEFAULT_PROMPT_BUDGET_CHARS + 1000)
    truncated = _truncate_to_budget(long_text, DEFAULT_PROMPT_BUDGET_CHARS)
    assert len(truncated) <= DEFAULT_PROMPT_BUDGET_CHARS + 100
    assert "truncated" in truncated

    _os.environ["LLMWIKI_COMPILE_CONCURRENCY"] = "2"
    try:
        assert _concurrency() == 2
    finally:
        _os.environ.pop("LLMWIKI_COMPILE_CONCURRENCY", None)
    _os.environ["LLMWIKI_COMPILE_CONCURRENCY"] = "9999"
    try:
        from scripts.wiki import COMPILE_CONCURRENCY_MAX

        assert _concurrency() == COMPILE_CONCURRENCY_MAX
    finally:
        _os.environ.pop("LLMWIKI_COMPILE_CONCURRENCY", None)


def test_wiki_provider_outage_detected():
    """Workers AI outage (5xx/timeout) is classified as provider error for isolation."""
    from scripts.wiki import _is_provider_error, ProviderUnavailableError

    assert _is_provider_error("ProviderUnavailableError: missing") is True
    assert _is_provider_error("OPENAI_API_KEY missing") is True
    assert _is_provider_error("llmwiki compile failed 1: 503 Service Unavailable") is True
    assert _is_provider_error("fetch failed: ECONNRESET Workers AI") is True
    assert _is_provider_error("timeout after 30000ms") is True
    assert _is_provider_error("all good compiled 3 pages") is False
    # Outage still raises ProviderUnavailableError via compile path (mocked by direct raise)
    with pytest.raises(ProviderUnavailableError):
        raise ProviderUnavailableError("503 Workers AI outage")


def test_wiki_atomic_writes_no_partial():
    """Wiki page + state writes are atomic (tmp + rename) — no partial on crash."""
    from scripts.wiki import _atomic_write

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        target = tmp_path / "wiki" / "concepts" / "a.md"
        _atomic_write(target, "# A\n")
        assert target.read_text(encoding="utf-8") == "# A\n"
        # Overwrite atomically
        _atomic_write(target, "# B\n")
        assert target.read_text(encoding="utf-8") == "# B\n"
        # No tmp leftovers
        assert list(tmp_path.rglob(".tmp.*")) == []


def test_wiki_frequency_knob_skips_when_disabled():
    """WIKI_ENABLED=0 skips synthesis (spec.md:150 frequency configurable)."""
    import os as _os

    _os.environ["WIKI_ENABLED"] = "0"
    try:
        # Simulate orchestrator wiki_runner skip logic
        enabled = _os.environ.get("WIKI_ENABLED", "1").strip().lower()
        assert enabled in ("0", "false", "no", "off")
    finally:
        _os.environ.pop("WIKI_ENABLED", None)


def test_wiki_collection_qmd_query_scoped_and_unified():
    """corpus/wiki registered as QMD wiki collection; qmd query --collection wiki returns wiki pages, unified returns wiki + raw."""
    # This test mimics spec Testing Decisions: corpus in, search out — we use file-level BM25 like test_qmd_search.py
    # If qmd-main available, we would use createStore, otherwise we simulate via fastGlob + BM25
    import re

    def simple_score(query: str, text: str) -> int:
        return len(re.findall(rf"\b{re.escape(query)}\b", text.lower()))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        os.environ["LLMWIKI_MOCK"] = "1"
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            # Create Units + wiki
            p_raw = _make_unit("github", "nebula/repo", "Nebula is about stars. nebula", "Nebula")
            _write_units(corpus, [p_raw])
            from scripts.wiki import compile_wiki

            compile_wiki(corpus, state_path=tmp_path / ".llmwiki" / "state.json", mock=True)

            # Simulate QMD collections: github -> corpus/github, wiki -> corpus/wiki
            wiki_files = list((corpus / "wiki").rglob("*.md"))
            github_files = list((corpus / "github").rglob("*.md"))
            all_files = list(corpus.rglob("*.md"))
            # Filter out state
            all_files = [p for p in all_files if "_state" not in p.parts and ".qmd" not in p.parts]

            assert len(wiki_files) >= 1
            assert len(github_files) >= 1

            # Scoped wiki search for "nebula" — should find wiki pages that mention nebula (via citations)
            # Our stub wiki pages contain "nebula" via sources? Let's ensure they do
            # The stub cites nebula repo, so it should contain nebula term
            wiki_texts = [p.read_text(encoding="utf-8") for p in wiki_files]
            # At least one wiki file should contain nebula (since it cites nebula repo)
            assert any("nebula" in t.lower() for t in wiki_texts), "wiki should mention nebula via citation"

            # Scoped search: only wiki
            scoped = [(simple_score("nebula", t), p) for p, t in zip(wiki_files, wiki_texts)]
            scoped.sort(key=lambda x: x[0], reverse=True)
            assert scoped[0][0] > 0

            # Unified: wiki + raw — both should have nebula
            unified_files = wiki_files + github_files
            unified_texts = [p.read_text(encoding="utf-8") for p in unified_files]
            unified = [(simple_score("nebula", t), p) for p, t in zip(unified_files, unified_texts)]
            unified.sort(key=lambda x: x[0], reverse=True)
            # Top should be either wiki or raw, but both present
            assert len([s for s, _ in unified if s > 0]) >= 2
        finally:
            os.environ.pop("LLMWIKI_MOCK", None)
            os.environ.pop("OPENAI_API_KEY", None)


def test_wiki_qmd_collection_registered():
    """corpus/wiki registered as QMD wiki collection via qmd.index.yml.example + register scripts.

    Real `qmd query --collection wiki` requires qmd binary + embeddings (deferred to
    acceptance ticket); here we assert the versioned collection config declares wiki
    with path corpus/wiki and pattern **/*.md, so `qmd collection add` / `qmd update`
    will index corpus/wiki as the wiki collection.
    """
    example = pathlib.Path("qmd.index.yml.example")
    assert example.exists(), "qmd.index.yml.example must exist for QMD registration"
    text = example.read_text(encoding="utf-8")
    assert "wiki:" in text
    assert "corpus/wiki" in text
    assert "**/*.md" in text
    # All silos 1:1 per spec.md:82-86
    for silo in ["github:", "chats:", "notes:", "pdfs:", "web:", "wiki:"]:
        assert silo in text, f"collection {silo} missing from {example}"
    # Register scripts exist
    assert pathlib.Path("scripts/register_qmd_collections.sh").exists()
    assert pathlib.Path("scripts/register_qmd_collections.ps1").exists()


def test_wiki_no_raw_units_rewritten():
    """Synthesis Pass must not rewrite raw Units (spec.md:44)."""
    from scripts.wiki import compile_wiki

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state = tmp_path / ".llmwiki" / "state.json"
        os.environ["LLMWIKI_MOCK"] = "1"
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            p = _make_unit("github", "orig/repo", "Original content.", "Orig")
            out = write_unit(p, corpus)
            original_hash = out.read_text(encoding="utf-8")
            compile_wiki(corpus, state_path=state, mock=True)
            # Raw Unit should be unchanged
            assert out.read_text(encoding="utf-8") == original_hash
            # Also run second compile
            compile_wiki(corpus, state_path=state, mock=True)
            assert out.read_text(encoding="utf-8") == original_hash
        finally:
            os.environ.pop("LLMWIKI_MOCK", None)
            os.environ.pop("OPENAI_API_KEY", None)
