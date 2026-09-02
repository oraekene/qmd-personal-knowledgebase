import pathlib
import tempfile
from datetime import datetime, timezone

# Seam: PDFs local — inbox/pdfs/ watched LiteParse -> corpus/pdfs/ with ---- page separators, Summary Line, searchable
# Per #17 + research #6 + spec.md:115-116 + #9 per-silo templates


def test_pdfs_connector_yields_units_with_page_separators(tmp_path_factory=None):
    # Test via fixture: create a fake PDF file (just bytes) and mock LiteParse
    # For #17, LiteParse is local but we mock it to return markdown with ----
    from connectors.pdfs import PdfsConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        inbox = tmp_path / "inbox" / "pdfs"
        corpus = tmp_path / "corpus"
        inbox.mkdir(parents=True)
        corpus.mkdir()

        # Create a fake PDF file (just a placeholder, LiteParse will be mocked)
        pdf_path = inbox / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")

        # Mock LiteParse to return markdown with page separators
        def mock_parse(pdf_path: pathlib.Path) -> str:
            # Simulate LiteParse output: pages joined by \n\n-----\n\n
            return "Page 1 content\n\n-----\n\nPage 2 content"

        connector = PdfsConnector(inbox_dir=inbox, corpus_root=corpus, parse_func=mock_parse)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads) == 1
        p = payloads[0]
        assert p.silo == "pdfs"
        assert p.source == "pdfs"
        assert p.source_id == "test"
        assert "----" in p.body_markdown
        assert p.body_markdown.count("----") == 1
        # Summary Line should be present
        assert p.summary
        # Body should have heading
        assert "# test" in p.body_markdown.lower() or "# Test" in p.body_markdown

        # Writer should create file with 9-field frontmatter
        from connectors.sdk.writer import write_unit

        out = write_unit(p, corpus)
        assert out == corpus / "pdfs" / "test.md"
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        for field in ["source:", "silo:", "source_id:", "url:", "created_at:", "ingested_at:", "tags:", "author:", "content_hash:"]:
            assert field in text
        assert "----" in text
        assert "> " in text


def test_pdfs_connector_handles_scanned_pdf_fallback():
    """Scanned PDF with no text should still yield a Unit, with fallback handling."""
    from connectors.pdfs import PdfsConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        inbox = tmp_path / "inbox" / "pdfs"
        corpus = tmp_path / "corpus"
        inbox.mkdir(parents=True)
        corpus.mkdir()

        pdf_path = inbox / "scanned.pdf"
        pdf_path.write_bytes(b"%PDF scanned fake")

        def mock_parse_scanned(pdf_path: pathlib.Path) -> str:
            # Simulate scanned PDF that after OCR still has minimal text
            # LiteParse would return something, but we simulate the fallback case
            # For #17, the connector should still yield a Unit, even if scanned
            return "Scanned page content after OCR\n\n-----\n\nSecond scanned page"

        connector = PdfsConnector(inbox_dir=inbox, corpus_root=corpus, parse_func=mock_parse_scanned)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads) == 1
        p = payloads[0]
        assert "Scanned" in p.body_markdown or "scanned" in p.body_markdown.lower()


def test_pdfs_connector_continue_on_page_error():
    """continue_on_page_error should keep partial content even if one page fails."""
    from connectors.pdfs import PdfsConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        inbox = tmp_path / "inbox" / "pdfs"
        corpus = tmp_path / "corpus"
        inbox.mkdir(parents=True)
        corpus.mkdir()

        pdf_path = inbox / "partial.pdf"
        pdf_path.write_bytes(b"%PDF partial")

        def mock_parse_partial(pdf_path: pathlib.Path) -> str:
            # Simulate LiteParse with continue_on_page_error: one page failed, but we still get partial
            # The connector should still yield a Unit with partial content
            return "Page 1 ok\n\n-----\n\n[Page 3 skipped due to error]"

        connector = PdfsConnector(inbox_dir=inbox, corpus_root=corpus, parse_func=mock_parse_partial)
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads) == 1
        assert "Page 1" in payloads[0].body_markdown


def test_pdfs_connector_dedup_via_content_hash():
    """Same PDF content should be deduped via blake3 content_hash (first-seen-wins)."""
    from connectors.pdfs import PdfsConnector
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        inbox = tmp_path / "inbox" / "pdfs"
        corpus = tmp_path / "corpus"
        inbox.mkdir(parents=True)
        corpus.mkdir()

        # Create two PDFs with same content (same hash)
        pdf1 = inbox / "a.pdf"
        pdf1.write_bytes(b"same content")
        pdf2 = inbox / "b.pdf"
        pdf2.write_bytes(b"same content")

        def mock_parse_same(pdf_path: pathlib.Path) -> str:
            return "Same content for both"

        connector = PdfsConnector(inbox_dir=inbox, corpus_root=corpus, parse_func=mock_parse_same)
        # First run should yield 2 (both PDFs), but writer dedup via content_hash should handle second run
        # For connector, we just test that it yields both, and the orchestrator/writer will dedup via file existence
        payloads = list(connector.fetch_recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        assert len(payloads) == 2
        # Simulate writer dedup: first write succeeds, second with same content_hash should be idempotent if same source_id?
        # For PDFs, source_id is filename without extension, so a.pdf and b.pdf have different source_ids, so they would be different Units
        # But if same content and same source_id, second would be skipped
        from connectors.sdk.writer import write_unit
        from connectors.sdk.base import UnitPayload

        # Two payloads with same source_id and same body should dedupe second write
        p1 = payloads[0]
        p1.source_id = "same"
        p2 = payloads[1]
        p2.source_id = "same"
        p2.body_markdown = p1.body_markdown
        p2.summary = p1.summary
        out1 = write_unit(p1, corpus)
        out2 = write_unit(p2, corpus)
        # Second write should be idempotent (same file, same hash, no duplicate)
        assert out1 == out2
        assert len(list((corpus / "pdfs").glob("*.md"))) == 1
