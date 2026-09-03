import pathlib
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

# Seam: Orchestrator — isolates failures, persists CrawlState, single qmd update+embed
# Per #15 + #10 locked contract + research #2


def test_orchestrator_isolates_single_connector_failure():
    """One failing connector (e.g. expired X cookie) should not stop others; other Units still indexed."""
    from orchestrator import run_once
    from connectors.sdk.base import UnitPayload
    from connectors.sdk.state import CrawlState

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state_path = corpus / "_state" / "crawl_state.json"

        # Mock connectors: one fails, one succeeds
        good_payload = UnitPayload(
            source="github",
            silo="github",
            source_id="oraekene/good",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="Good",
            summary="Good unit.",
            body_markdown="# Good\nBody",
        )

        class GoodConnector:
            NAME = "good"
            def fetch_recent(self, since, limit=50):
                yield good_payload

        class BadConnector:
            NAME = "bad"
            def fetch_recent(self, since, limit=50):
                raise RuntimeError("expired X cookie 401")

        # Mock qmd runner — should be called exactly once after all connectors, even though one failed
        qmd_mock = Mock(return_value=0)
        wiki_mock = Mock(return_value=0)

        # Need to mock connectors as SourcePlugin-like objects with NAME and fetch_recent
        # run_once should isolate BadConnector failure and still process GoodConnector
        run_once(
            connectors=[GoodConnector(), BadConnector()],
            corpus_root=corpus,
            state_path=state_path,
            qmd_runner=qmd_mock,
            wiki_runner=wiki_mock,
        )

        # Good unit should be written
        assert (corpus / "github" / "oraekene__good.md").exists()
        # qmd should have been called exactly once despite one failure
        assert qmd_mock.call_count == 1
        # wiki should also have been called (isolated)
        assert wiki_mock.call_count == 1
        # CrawlState: good's last_seen should have advanced, bad's should not (still default)
        state = CrawlState(state_path)
        default = datetime(2025, 1, 1, tzinfo=timezone.utc)
        good_last = state.get_last_seen("good", default)
        bad_last = state.get_last_seen("bad", default)
        assert good_last != default, "good should have advanced"
        assert bad_last == default, "bad should not have advanced on failure"


def test_orchestrator_crawlstate_persists_and_resumes():
    """CrawlState last_seen only on success; second run with same since yields 0 (resume not re-crawl)."""
    from orchestrator import run_once
    from connectors.sdk.base import UnitPayload
    from connectors.sdk.state import CrawlState

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state_path = corpus / "_state" / "crawl_state.json"

        payload = UnitPayload(
            source="test",
            silo="github",
            source_id="oraekene/resume",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="Resume",
            summary="Resume unit.",
            body_markdown="# Resume\nBody",
        )

        class OnceConnector:
            NAME = "resume_test"
            def __init__(self):
                self.calls = 0
            def fetch_recent(self, since, limit=50):
                self.calls += 1
                # Only yield on first call (since is default far past)
                # On second call, since will be after fake_created, so yield nothing
                fake_created = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
                if since and fake_created <= since:
                    return
                    yield
                yield payload

        connector = OnceConnector()
        qmd_mock = Mock(return_value=0)
        # Use fixed now to make test deterministic (avoid flakiness when now-2days crosses fake_created)
        fixed_now = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)

        # First run — should write and advance last_seen
        run_once([connector], corpus, state_path, qmd_mock, Mock(), now=fixed_now)
        assert (corpus / "github" / "oraekene__resume.md").exists()
        assert qmd_mock.call_count == 1
        state = CrawlState(state_path)
        first_last = state.get_last_seen("resume_test", datetime(2025, 1, 1, tzinfo=timezone.utc))
        assert first_last != datetime(2025, 1, 1, tzinfo=timezone.utc)

        # Second run — since is now first_last (after fake_created), should yield 0 and not write duplicate
        qmd_mock2 = Mock(return_value=0)
        run_once([connector], corpus, state_path, qmd_mock2, Mock(), now=fixed_now + timedelta(hours=4))
        # Still only one file, no duplicate
        assert len(list(corpus.glob("github/**/*.md"))) == 1
        # qmd still called exactly once per run (even though no new Units, the single qmd update still runs)
        assert qmd_mock2.call_count == 1
        # CrawlState should have advanced again (or stayed same if no new Units? For #15, last_seen advances only on success, even if 0 new Units, it still advances to now)
        # Our run_once advances last_seen to now on every successful run, regardless of count
        state2 = CrawlState(state_path)
        second_last = state2.get_last_seen("resume_test", datetime(2025, 1, 1, tzinfo=timezone.utc))
        assert second_last >= first_last


def test_orchestrator_single_qmd_update_and_wiki_isolated():
    """After all connectors, exactly one qmd update && embed, and wiki failure doesn't block qmd or mirror."""
    from orchestrator import run_once
    from connectors.sdk.base import UnitPayload

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        state_path = corpus / "_state" / "crawl_state.json"

        payload = UnitPayload(
            source="good",
            silo="github",
            source_id="a/b",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="A",
            summary="Summary.",
            body_markdown="# A\nBody",
        )

        class Good:
            NAME = "good"
            def fetch_recent(self, since, limit=50):
                yield payload

        qmd_mock = Mock(return_value=0)
        # Wiki mock that fails
        def failing_wiki():
            raise RuntimeError("missing OPENAI_API_KEY")

        wiki_mock = Mock(side_effect=failing_wiki)

        # Should not raise, should still have called qmd exactly once, and wiki attempted
        run_once([Good()], corpus, state_path, qmd_mock, wiki_mock)

        assert qmd_mock.call_count == 1
        assert wiki_mock.call_count == 1
        # Corpus file should still exist despite wiki failure
        assert (corpus / "github" / "a__b.md").exists()


def test_orchestrator_corpus_state_gitignored_not_deployed():
    """corpus/_state/crawl_state.json is gitignored and not deployed to Pages (checked via .gitignore)."""
    gitignore = pathlib.Path(".gitignore").read_text(encoding="utf-8")
    assert "corpus/_state/" in gitignore
    assert "corpus/.qmd/" in gitignore
    # Also check that state file would be under corpus/_state, not corpus/
    from orchestrator import DEFAULT_STATE_PATH

    assert "_state" in str(DEFAULT_STATE_PATH)
    assert "crawl_state.json" in str(DEFAULT_STATE_PATH)
