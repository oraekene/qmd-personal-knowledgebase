"""Tests for PDF ingestion via LiteParse (Feature 7)."""
from datetime import datetime, timezone
from pathlib import Path
import pytest

from connectors.pdfs import PdfsConnector, _summary_from_text


def test_summary_from_text():
    text = "This is the first sentence. This is the second sentence."
    summary = _summary_from_text(text)
    assert summary == "This is the first sentence."

    long_text = "A" * 200 + ". Second sentence."
    summary = _summary_from_text(long_text)
    assert len(summary) <= 125
    assert summary.endswith("...")


def test_liteparse_import():
    """Verify LiteParse package is installed and importable."""
    from liteparse import LiteParse
    parser = LiteParse(output_format="markdown", image_mode="placeholder")
    assert parser is not None


def test_pdfs_connector_with_mock_parse(tmp_path: Path):
    inbox = tmp_path / "inbox" / "pdfs"
    inbox.mkdir(parents=True)
    sample_pdf = inbox / "sample_doc.pdf"
    sample_pdf.write_bytes(b"%PDF-1.4 sample binary content")

    def mock_parse(p: Path) -> str:
        return "# Sample Document\n\nPage 1 text.\n\n-----\n\nPage 2 table:\n| A | B |\n|---|---|\n| 1 | 2 |"

    connector = PdfsConnector(inbox_dir=inbox, parse_func=mock_parse)
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    units = list(connector.fetch_recent(since=since))

    assert len(units) == 1
    unit = units[0]
    assert unit.silo == "pdfs"
    assert unit.source == "pdfs"
    assert unit.source_id == "sample_doc"
    assert "Sample Doc" in unit.title
    assert "-----" in unit.body_markdown
    assert "| A | B |" in unit.body_markdown


def test_pdfs_connector_empty_fallback(tmp_path: Path):
    inbox = tmp_path / "inbox" / "pdfs"
    inbox.mkdir(parents=True)
    bad_pdf = inbox / "empty.pdf"
    bad_pdf.write_bytes(b"")

    connector = PdfsConnector(inbox_dir=inbox)
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    units = list(connector.fetch_recent(since=since))
    assert len(units) == 0
