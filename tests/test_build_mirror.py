import pathlib
import tempfile
import os

# Seam: Static Mirror build — token-gated path, llms.txt, 404, predictable URLs (spec Testing Decisions smoke)


def _make_fixture_corpus(tmp: pathlib.Path) -> pathlib.Path:
    corpus = tmp / "corpus"
    # Create one Unit per locked schema #9
    (corpus / "github").mkdir(parents=True, exist_ok=True)
    (corpus / "wiki").mkdir(parents=True, exist_ok=True)
    unit = corpus / "github" / "oraekene__nebula.md"
    unit.write_text("""---
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
""", encoding="utf-8")
    (corpus / "wiki" / "index.md").write_text("""---
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
""", encoding="utf-8")
    return corpus


def test_build_mirror_token_gated_and_llms():
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token = "a3f9c123deadbeef"

        result = build_mirror(corpus, dist, token, mirror_host="https://example.pages.dev")

        # dist/<TOKEN>/ should contain corpus copy
        assert (dist / token / "github" / "oraekene__nebula.md").exists()
        assert (dist / token / "wiki" / "index.md").exists()
        # root should NOT contain corpus untokenized
        assert not (dist / "github" / "oraekene__nebula.md").exists()
        # llms.txt at root and under token
        assert (dist / "llms.txt").exists()
        assert (dist / token / "llms.txt").exists()
        txt = (dist / "llms.txt").read_text(encoding="utf-8")
        assert "# Private Knowledgebase" in txt or "# " in txt  # H1 required
        assert "> " in txt  # blockquote
        assert token in txt  # tokenized URLs
        assert "github/oraekene__nebula.md" in txt
        # 404 disables SPA
        assert (dist / "404.html").exists()
        # _headers with markdown MIME and noindex
        headers = (dist / "_headers").read_text(encoding="utf-8")
        assert "Content-Type: text/markdown" in headers
        assert "X-Robots-Tag: noindex" in headers
        # result should contain dist path
        assert result == dist


def test_build_mirror_idempotent_and_token_rotation():
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token1 = "token1abc123"
        build_mirror(corpus, dist, token1, mirror_host="https://example.pages.dev")
        assert (dist / token1 / "github" / "oraekene__nebula.md").exists()
        # rotate token -> new dist/<new> should exist, old remains until rebuild cleans
        # Our build cleans dist first, so old token should be gone after second build
        token2 = "token2xyz789"
        build_mirror(corpus, dist, token2, mirror_host="https://example.pages.dev")
        assert (dist / token2 / "github" / "oraekene__nebula.md").exists()
        assert not (dist / token1 / "github" / "oraekene__nebula.md").exists()
        assert token2 in (dist / "llms.txt").read_text(encoding="utf-8")
        assert token1 not in (dist / "llms.txt").read_text(encoding="utf-8")


def test_build_mirror_predictable_urls():
    from scripts.build_mirror import build_mirror

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = _make_fixture_corpus(tmp_path)
        dist = tmp_path / "dist"
        token = "tok123"
        build_mirror(corpus, dist, token, mirror_host="https://qmd.example.com")
        # Unit URL predictable: https://host/<TOKEN>/<silo>/<path>.md
        txt = (dist / "llms.txt").read_text(encoding="utf-8")
        assert f"https://qmd.example.com/{token}/github/oraekene__nebula.md" in txt
        assert f"https://qmd.example.com/{token}/wiki/index.md" in txt
