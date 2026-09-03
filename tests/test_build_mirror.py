"""Tests for Static Mirror — token-gated Cloudflare Pages deploy for #19.

Per spec.md:26-30,132-135 + research #5 + #13 prototype ccf94b2.
Seam: scripts.build_mirror.build_mirror(corpus, dist, token, host)
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest


def _make_fixture_corpus(tmp: pathlib.Path) -> pathlib.Path:
    corpus = tmp / "corpus"
    (corpus / "github").mkdir(parents=True, exist_ok=True)
    (corpus / "wiki").mkdir(parents=True, exist_ok=True)
    (corpus / "notes").mkdir(parents=True, exist_ok=True)
    (corpus / "github" / "oraekene__nebula.md").write_text(
        """---
source: example_github
silo: github
source_id: oraekene__nebula
url: "https://github.com/oraekene/nebula"
created_at: "2026-09-01T10:00:00+00:00"
ingested_at: "2026-09-02T00:00:00+00:00"
tags: [python]
author: oraekene
content_hash: abc123
---
> GitHub repo oraekene/nebula — forked.

# Nebula

Content.
""",
        encoding="utf-8",
    )
    (corpus / "wiki" / "index.md").write_text(
        """---
source: wiki-compiler
silo: wiki
source_id: wiki-index
url: ""
created_at: "2026-09-02T00:00:00+00:00"
ingested_at: "2026-09-02T00:00:00+00:00"
tags: []
author: ""
content_hash: def456
---
> Wiki index.

# Wiki Index

- [[Nebula]]
""",
        encoding="utf-8",
    )
    (corpus / "wiki" / "deep.md").write_text(
        """---
source: wiki-compiler
silo: wiki
source_id: wiki-deep
url: ""
created_at: "2026-09-02T00:00:00+00:00"
ingested_at: "2026-09-02T00:00:00+00:00"
tags: []
author: ""
content_hash: ghi789
---
> Deep wiki.

# Deep

Details.
""",
        encoding="utf-8",
    )
    (corpus / "notes" / "idea.md").write_text(
        """---
source: notes
silo: notes
source_id: idea1
url: ""
created_at: "2026-09-01T10:00:00+00:00"
ingested_at: "2026-09-02T00:00:00+00:00"
tags: []
author: ""
content_hash: jkl012
---
> Idea.

# Idea

Note.
""",
        encoding="utf-8",
    )
    return corpus


def test_build_mirror_token_gated_and_llms() -> None:
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token = "a3f9c123deadbeefcafebabe12345678"

        result = build_mirror(corpus, dist, token, host="https://example.pages.dev")

        # dist/<TOKEN>/ should contain corpus copy
        assert (dist / token / "github" / "oraekene__nebula.md").exists()
        assert (dist / token / "wiki" / "index.md").exists()
        assert (dist / token / "wiki" / "deep.md").exists()
        assert (dist / token / "notes" / "idea.md").exists()
        # root should NOT contain corpus untokenized
        assert not (dist / "github" / "oraekene__nebula.md").exists()
        assert not (dist / "wiki").exists() or not (dist / "wiki" / "index.md").exists()
        # llms.txt at root and under token
        assert (dist / "llms.txt").exists()
        assert (dist / token / "llms.txt").exists()
        txt = (dist / "llms.txt").read_text(encoding="utf-8")
        assert txt.startswith("# Private Knowledgebase")
        assert "> Personal search corpus" in txt
        assert "## Wiki" in txt
        assert "## Silos" in txt
        assert token in txt  # tokenized URLs
        assert "github/oraekene__nebula.md" in txt
        # Wiki primary — Wiki section before Silos
        wiki_idx = txt.index("## Wiki")
        silos_idx = txt.index("## Silos")
        assert wiki_idx < silos_idx
        # 404 disables SPA
        assert (dist / "404.html").exists()
        assert "404" in (dist / "404.html").read_text(encoding="utf-8")
        # _headers with markdown MIME and noindex
        headers = (dist / "_headers").read_text(encoding="utf-8")
        assert "Content-Type: text/markdown" in headers
        assert "X-Robots-Tag: noindex" in headers
        assert "Cache-Control" in headers
        # _redirects and robots.txt
        assert (dist / "_redirects").exists()
        assert (dist / "robots.txt").exists()
        assert "Disallow: /" in (dist / "robots.txt").read_text(encoding="utf-8")
        # result should be dist path
        assert result == dist


def test_build_mirror_idempotent_and_token_rotation() -> None:
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        build_mirror(corpus, dist, token1, host="https://example.pages.dev")
        assert (dist / token1 / "github" / "oraekene__nebula.md").exists()
        # rotate token -> new dist/<new> should exist, old remains until rebuild cleans
        # Our build cleans dist first, so old token should be gone after second build
        token2 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        build_mirror(corpus, dist, token2, host="https://example.pages.dev")
        assert (dist / token2 / "github" / "oraekene__nebula.md").exists()
        assert not (dist / token1 / "github" / "oraekene__nebula.md").exists()
        assert not (dist / token1).exists()
        txt = (dist / "llms.txt").read_text(encoding="utf-8")
        assert token2 in txt
        assert token1 not in txt
        # llms.txt under new token also rotated
        assert token2 in (dist / token2 / "llms.txt").read_text(encoding="utf-8")


def test_build_mirror_predictable_urls() -> None:
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token = "cccccccccccccccccccccccccccccccc"
        build_mirror(corpus, dist, token, host="https://qmd.example.com")
        txt = (dist / "llms.txt").read_text(encoding="utf-8")
        assert f"https://qmd.example.com/{token}/github/oraekene__nebula.md" in txt
        assert f"https://qmd.example.com/{token}/wiki/index.md" in txt
        assert f"https://qmd.example.com/{token}/wiki/deep.md" in txt
        # All URLs predictable, no untokenized URLs
        assert "https://qmd.example.com/github" not in txt
        assert "https://qmd.example.com/wiki" not in txt or f"/{token}/wiki" in txt


def test_build_mirror_headers_and_redirects_and_robots() -> None:
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token = "dddddddddddddddddddddddddddddddd"
        build_mirror(corpus, dist, token, host="https://qmd-mirror.pages.dev")

        headers = (dist / "_headers").read_text(encoding="utf-8")
        # llms.txt MIME
        assert "/llms.txt" in headers
        assert f"/{token}/llms.txt" in headers
        # md MIME
        assert "/*.md" in headers or ".md" in headers
        # noindex for tokenized
        assert f"/{token}/*" in headers
        assert "X-Robots-Tag: noindex" in headers
        # 404 cache no-store
        assert "/404.html" in headers

        redirects = (dist / "_redirects").read_text(encoding="utf-8")
        assert f"/{token}/*" in redirects
        assert "404.html" in redirects
        assert "  404" in redirects

        # no untokenized corpus at dist root
        assert not (dist / "github").exists()
        assert (dist / "404.html").exists()


def test_build_mirror_rejects_invalid_token() -> None:
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        # empty
        with pytest.raises(ValueError):
            build_mirror(corpus, dist, "", host="https://example.pages.dev")
        # non-hex
        with pytest.raises(ValueError):
            build_mirror(corpus, dist, "zzzz-not-hex-!!!!", host="https://example.pages.dev")
        # too short
        with pytest.raises(ValueError):
            build_mirror(corpus, dist, "abc123", host="https://example.pages.dev")


def test_build_mirror_rejects_invalid_host() -> None:
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        with pytest.raises(ValueError):
            build_mirror(corpus, dist, token, host="http://not-https.com")
        with pytest.raises(ValueError):
            build_mirror(corpus, dist, token, host="ftp://example.com")


def test_build_mirror_empty_corpus() -> None:
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        dist = tmp_path / "dist"
        token = "ffffffffffffffffffffffffffffffff"
        build_mirror(corpus, dist, token, host="https://example.pages.dev")
        assert (dist / token / "llms.txt").exists()
        txt = (dist / "llms.txt").read_text(encoding="utf-8")
        assert "# Private Knowledgebase" in txt
        # No crash, still has headers
        assert (dist / "_headers").exists()

