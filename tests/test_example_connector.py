import pathlib
import tempfile
from datetime import datetime, timezone

# Second seam test: connector yields UnitPayload, writer persists, corpus structure correct


def test_example_connector_yields_unit_and_writer_persists():
    from connectors.example_github import ExampleGithubConnector
    from connectors.sdk.writer import write_unit

    connector = ExampleGithubConnector()
    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    payloads = list(connector.fetch_recent(since))
    assert len(payloads) == 1
    p = payloads[0]
    assert p.source == "example_github"
    assert p.silo == "github"
    assert p.source_id == "oraekene__nebula"
    assert p.summary
    assert p.title == "Nebula"

    with tempfile.TemporaryDirectory() as tmp:
        corpus = pathlib.Path(tmp) / "corpus"
        out = write_unit(p, corpus)
        assert out == corpus / "github" / "oraekene__nebula.md"
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "source: example_github" in text
        assert "silo: github" in text
        assert "oraekene/nebula" in text
        assert "> GitHub repo oraekene/nebula" in text
        assert "# Nebula" in text
        # provenance jump-back url present
        assert "https://github.com/oraekene/nebula" in text


def test_example_connector_respects_since():
    from connectors.example_github import ExampleGithubConnector

    connector = ExampleGithubConnector()
    # since after fake_created should yield nothing
    since_future = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert list(connector.fetch_recent(since_future)) == []
    # since before should yield
    since_past = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert len(list(connector.fetch_recent(since_past))) == 1


def test_discovery_loads_example_plugin():
    from connectors.sdk.discovery import load_plugins
    import pathlib

    plugins = load_plugins(pathlib.Path("connectors"))
    assert "example_github" in plugins
    assert plugins["example_github"].NAME == "example_github"


def test_corpus_silo_structure_matches_qmd_collection():
    # Verify corpus/<silo>/ layout is QMD-ready (pattern **/*.md, per research #3)
    # QMD collections are silos via path; this test ensures writer respects that
    from connectors.sdk.writer import write_unit
    from connectors.sdk.base import UnitPayload
    import pathlib, tempfile

    with tempfile.TemporaryDirectory() as tmp:
        corpus = pathlib.Path(tmp) / "corpus"
        for silo, sid in [("github", "repo1"), ("chats/claude", "sess1"), ("twitter/bookmarks", "tweet1")]:
            p = UnitPayload(
                source="test",
                silo=silo,
                source_id=sid,
                url="",
                created_at="2026-09-01T00:00:00+00:00",
                tags=[],
                author="",
                title="T",
                summary="Test summary for silo check.",
                body_markdown="# T\nBody",
            )
            out = write_unit(p, corpus)
            assert out.parent == corpus / pathlib.Path(silo), f"silo subpath {silo} should be preserved"
            assert out.exists()
        # Check that corpus has expected top-level silos
        silos = {p.name for p in corpus.iterdir() if p.is_dir()}
        assert "github" in silos
        assert "chats" in silos
