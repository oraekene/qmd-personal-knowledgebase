import pathlib
import tempfile
from datetime import datetime, timezone

# Second seam for #14: dual-account dedup first-seen-wins, per-account CrawlState, QMD collection path


def test_github_dual_account_dedup_first_seen_wins():
    from connectors.github import GithubConnector, dedupe_by_source_id
    from connectors.sdk.base import UnitPayload

    # Simulate two accounts yielding same full_name
    p1 = UnitPayload(source="github", silo="github", source_id="oraekene/nebula", url="https://github.com/oraekene/nebula", created_at="2026-09-01T00:00:00+00:00", tags=[], author="", title="Nebula", summary="Repo nebula.", body_markdown="# Nebula\nBody")
    p2 = UnitPayload(source="github", silo="github", source_id="oraekene/Nebula", url="https://github.com/oraekene/nebula", created_at="2026-09-01T00:00:00+00:00", tags=[], author="", title="Nebula", summary="Repo nebula dup.", body_markdown="# Nebula\nBody dup")

    # First account's payload wins, second is skipped (case-insensitive)
    seen: set[str] = set()
    batch1 = dedupe_by_source_id([p1], seen)
    assert len(batch1) == 1
    assert "oraekene/nebula" in seen or "oraekene/nebula".lower() in seen
    batch2 = dedupe_by_source_id([p2], seen)
    assert len(batch2) == 0, "second account duplicate should be skipped"

    # Different repo should not be deduped
    p3 = UnitPayload(source="github", silo="github", source_id="oraekene/other", url="", created_at="", tags=[], author="", title="Other", summary="Other.", body_markdown="# Other")
    batch3 = dedupe_by_source_id([p3], seen)
    assert len(batch3) == 1


def test_github_connector_per_account_crawlstate():
    from connectors.github import GithubConnector
    from connectors.sdk.state import CrawlState
    import pathlib, tempfile
    from datetime import datetime, timezone

    with tempfile.TemporaryDirectory() as tmp:
        state_path = pathlib.Path(tmp) / "crawl_state.json"
        state = CrawlState(state_path)

        # Two accounts with distinct CrawlState keys
        since_a = state.get_last_seen("github:account_a", datetime(2025, 1, 1, tzinfo=timezone.utc))
        since_b = state.get_last_seen("github:account_b", datetime(2025, 1, 1, tzinfo=timezone.utc))
        assert since_a == since_b  # both default

        # Simulate successful fetch for account_a — advance its cursor
        now = datetime.now(timezone.utc)
        state.set_last_seen("github:account_a", now)
        state.save()

        # Reload — account_b should still be at default, account_a advanced
        state2 = CrawlState(state_path)
        assert state2.get_last_seen("github:account_a", datetime(2025, 1, 1, tzinfo=timezone.utc)) == now
        assert state2.get_last_seen("github:account_b", datetime(2025, 1, 1, tzinfo=timezone.utc)) == datetime(2025, 1, 1, tzinfo=timezone.utc)

        # Even when dedup skips write, CrawlState still advances (tested via set_last_seen after fetch, before dedup)


def test_github_connector_yields_unit_with_frontmatter():
    from connectors.github import GithubConnector
    from connectors.sdk.writer import write_unit
    import tempfile, pathlib

    connector = GithubConnector(account_label="primary")
    connector.configure({"full_name": "oraekene/test-repo", "token_env": "GITHUB_TOKEN_A"})
    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    payloads = list(connector.fetch_recent(since))
    assert len(payloads) == 1
    p = payloads[0]
    assert p.silo == "github"
    assert p.source_id == "oraekene/test-repo"
    # Writer should create file with 9-field frontmatter
    with tempfile.TemporaryDirectory() as tmp:
        corpus = pathlib.Path(tmp) / "corpus"
        out = write_unit(p, corpus)
        assert out == corpus / "github" / "oraekene__test-repo.md"
        text = out.read_text(encoding="utf-8")
        for field in ["source:", "silo:", "source_id:", "url:", "created_at:", "ingested_at:", "content_hash:"]:
            assert field in text
        assert "title:" not in text.lower()
        assert "> " in text
        assert "test-repo" in text.lower()


def test_github_connector_respects_since_and_limit():
    from connectors.github import GithubConnector
    from datetime import datetime, timezone

    connector = GithubConnector()
    # since after fake_created should yield 0
    since_future = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert list(connector.fetch_recent(since_future, limit=10)) == []
    # limit 0 should yield 0 even when since is past
    assert list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc), limit=0)) == []
    # normal should yield 1
    assert len(list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc), limit=10))) == 1
