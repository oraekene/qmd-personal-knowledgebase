import pathlib
import tempfile
from datetime import datetime, timezone, timedelta

# CrawlState persistence seam — forward last_seen only on success, lookback cursor, file atomic


def test_crawl_state_forward_last_seen_only_on_success():
    from connectors.sdk.state import CrawlState

    with tempfile.TemporaryDirectory() as tmp:
        state_path = pathlib.Path(tmp) / "crawl_state.json"
        state = CrawlState(state_path)
        default = datetime(2025, 1, 1, tzinfo=timezone.utc)
        # initially returns default
        assert state.get_last_seen("example_github", default) == default
        now = datetime.now(timezone.utc)
        state.set_last_seen("example_github", now)
        state.save()
        # reload
        state2 = CrawlState(state_path)
        assert state2.get_last_seen("example_github", default) == now
        # simulate failure: don't call set_last_seen, save shouldn't advance
        state3 = CrawlState(state_path)
        before = state3.get_last_seen("example_github", default)
        # no set, save
        state3.save()
        state4 = CrawlState(state_path)
        assert state4.get_last_seen("example_github", default) == before


def test_crawl_state_lookback_cursor_and_complete():
    from connectors.sdk.state import CrawlState

    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "crawl_state.json"
        state = CrawlState(path)
        assert state.get_lookback_cursor("x") is None
        assert not state.is_history_complete("x")
        state.set_lookback_cursor("x", {"page": 1})
        assert state.get_lookback_cursor("x") == {"page": 1}
        state.mark_history_complete("x")
        assert state.is_history_complete("x")
        state.save()
        state2 = CrawlState(path)
        assert state2.get_lookback_cursor("x") == {"page": 1}
        assert state2.is_history_complete("x")
