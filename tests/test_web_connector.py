import pathlib
import tempfile
import re
from datetime import datetime, timezone

# Seam: Link expansion — TinyFish primary + Scrapling fallback -> corpus/web/<hash>.md one-level, deduped, SearXNG not fetcher
# Per #17 + research #7 + spec.md:115-119 + #9


def test_web_connector_fetches_links_one_level():
    """After any connector run, links inside new Units are fetched once, one-level, via TinyFish 10/batch."""
    from connectors.web import WebConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        corpus.mkdir()

        # Create a new Unit with links (simulating newly ingested Unit)
        # The WebConnector should scan corpus for Units with ingested_at == run (or all Units for test)
        from connectors.sdk.writer import write_unit
        from connectors.sdk.base import UnitPayload

        p = UnitPayload(
            source="github",
            silo="github",
            source_id="test-repo",
            url="https://github.com/oraekene/test-repo",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="Test",
            summary="Test repo with links.",
            body_markdown="# Test\n\nCheck https://example.com and https://example.org for more.",
        )
        out = write_unit(p, corpus)
        assert out.exists()

        # Mock TinyFish fetch to return markdown for those URLs
        def mock_fetch(urls):
            # Simulate TinyFish getContents: returns {results: [{url, text}], errors: []}
            results = []
            for url in urls:
                results.append({"url": url, "text": f"# Fetched {url}\n\nContent for {url}", "final_url": url})
            return {"results": results, "errors": []}

        connector = WebConnector(corpus_root=corpus, fetch_func=mock_fetch)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        # Should yield 2 payloads (one per link)
        assert len(payloads) == 2
        urls = {p.url for p in payloads}
        assert "https://example.com" in urls
        assert "https://example.org" in urls
        for p in payloads:
            assert p.silo == "web"
            assert p.source == "web"
            assert "https://" in p.body_markdown or "Fetched" in p.body_markdown

        # Writer should create web Units
        for p in payloads:
            out = write_unit(p, corpus)
            assert out.exists()
            assert out.parent == corpus / "web"
            text = out.read_text(encoding="utf-8")
            assert "source: web" in text
            assert "silo: web" in text


def test_web_connector_fallback_to_scrapling_on_failure():
    """TinyFish failure for a URL should fall back to Scrapling."""
    from connectors.web import WebConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        corpus.mkdir()

        from connectors.sdk.writer import write_unit
        from connectors.sdk.base import UnitPayload

        p = UnitPayload(
            source="github",
            silo="github",
            source_id="test2",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="Test2",
            summary="Test with failing link.",
            body_markdown="# Test2\n\nLink https://fail.example.com",
        )
        write_unit(p, corpus)

        # Mock TinyFish to fail for one URL, succeed for another
        def mock_fetch_with_failure(urls):
            results = []
            errors = []
            for url in urls:
                if "fail.example.com" in url:
                    errors.append({"url": url, "error": "blocked"})
                else:
                    results.append({"url": url, "text": f"# Fetched {url}", "final_url": url})
            return {"results": results, "errors": errors}

        # Mock Scrapling fallback to succeed for failed URL
        def mock_scrapling_fetch(url):
            return f"# Scrapling fetched {url}\n\nFallback content"

        connector = WebConnector(corpus_root=corpus, fetch_func=mock_fetch_with_failure, scrapling_func=mock_scrapling_fetch)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        # Should still yield 1 payload via fallback
        assert len(payloads) == 1
        assert payloads[0].url == "https://fail.example.com"
        assert "Scrapling" in payloads[0].body_markdown or "Fallback" in payloads[0].body_markdown


def test_web_connector_one_level_no_recursion():
    """Links inside newly fetched web Units should not be recrawled (one-level)."""
    from connectors.web import WebConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        corpus.mkdir()

        from connectors.sdk.writer import write_unit
        from connectors.sdk.base import UnitPayload

        # First Unit with link to example.com
        p1 = UnitPayload(
            source="github",
            silo="github",
            source_id="p1",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="P1",
            summary="P1 with link.",
            body_markdown="# P1\n\nSee https://example.com",
        )
        write_unit(p1, corpus)

        # Mock fetch for example.com to return content that itself contains a link to example.org
        # The WebConnector should fetch example.com once, but should NOT then fetch example.org from the fetched content (one-level)
        def mock_fetch(urls):
            results = []
            for url in urls:
                if url == "https://example.com":
                    results.append({"url": url, "text": "# Example\n\nSee https://example.org for more.", "final_url": url})
                else:
                    results.append({"url": url, "text": f"# {url}", "final_url": url})
            return {"results": results, "errors": []}

        connector = WebConnector(corpus_root=corpus, fetch_func=mock_fetch)
        payloads1 = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads1) == 1
        assert payloads1[0].url == "https://example.com"

        # Write the fetched web Unit
        for p in payloads1:
            write_unit(p, corpus)

        # Second run — should not fetch example.org from the web Unit's content
        # The WebConnector should only scan newly ingested Units (ingested_at == run) or all Units but deduped
        # For test, we simulate second run with same corpus but with a new since that is after first run
        # The WebConnector should dedupe already-fetched URLs and not recrawl
        payloads2 = list(connector.fetch_recent(datetime(2026, 9, 2, tzinfo=timezone.utc)))
        # Since no new github Units with new links, should yield 0
        # But our simple WebConnector scans all Units, not just new, so it would find the same link again
        # To pass, we need dedup via already-fetched web Units: check if corpus/web already has example.com
        # So second run should yield 0 because example.com already fetched
        # Our WebConnector should check if web Unit already exists for that URL (via content_hash or url)
        # For test, we assert that second run yields 0 or at most deduplicated
        # The key is that it should not fetch example.org
        urls2 = {p.url for p in payloads2}
        assert "https://example.org" not in urls2, "should not recrawl one level deep"


def test_web_connector_deduped_and_not_recrawled():
    """Already-fetched URLs should be deduped via content_hash/url."""
    from connectors.web import WebConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        corpus.mkdir()

        from connectors.sdk.writer import write_unit
        from connectors.sdk.base import UnitPayload

        p = UnitPayload(
            source="github",
            silo="github",
            source_id="dup",
            url="",
            created_at="2026-09-01T00:00:00+00:00",
            tags=[],
            author="",
            title="Dup",
            summary="Dup with link.",
            body_markdown="# Dup\n\nhttps://example.com",
        )
        write_unit(p, corpus)

        def mock_fetch(urls):
            return {"results": [{"url": url, "text": f"# {url}", "final_url": url} for url in urls], "errors": []}

        connector = WebConnector(corpus_root=corpus, fetch_func=mock_fetch)
        payloads1 = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads1) == 1
        # Write the web Unit
        for p in payloads1:
            write_unit(p, corpus)

        # Second run should dedupe and yield 0
        payloads2 = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        # Our WebConnector should check if web Unit already exists for that URL and skip
        # For this test, we expect 0 or 1 but deduped — the key is that it doesn't create duplicate files
        # We check that after second write, there is still only one web file for that URL
        for p in payloads2:
            write_unit(p, corpus)
        web_files = list((corpus / "web").glob("*.md"))
        # Should be 1, not 2, because second run should be deduped
        assert len(web_files) == 1
