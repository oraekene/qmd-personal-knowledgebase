"""Build Static Mirror — token-gated Cloudflare Pages deploy (prototype/static-mirror).

Per research #5 + spec.md:26-30,132-135 + docs/adr/0002/0003:
- Option A: dist/<TOKEN>/ containing full corpus copy (build-time directory copy)
- dist/ root has llms.txt, 404.html, robots.txt, _headers, _redirects — no corpus untokenized
- llms.txt H1 + blockquote + ## Wiki/## Silos lists with tokenized URLs, predictable https://host/<TOKEN>/<silo>/<path>.md
- Token rotation = new rand + redeploy (old prefix gone after rebuild cleans dist)
- Orchestrator hook: build_mirror(corpus, dist, token) then wrangler pages deploy dist --branch main

Prototype (HITL) — throwaway, does not ship.
"""
from __future__ import annotations
import shutil
import pathlib
from typing import List


def _collect_units(corpus: pathlib.Path) -> List[pathlib.Path]:
    # Collect all markdown Units under corpus (pattern **/*.md), ignore _state and .qmd
    units: List[pathlib.Path] = []
    for p in corpus.rglob("*.md"):
        # Skip hidden/state
        if "_state" in p.parts or ".qmd" in p.parts:
            continue
        units.append(p)
    units.sort()
    return units


def build_mirror(corpus: pathlib.Path, dist: pathlib.Path, token: str, mirror_host: str = "https://example.pages.dev") -> pathlib.Path:
    """Build mirror dist from corpus with token prefix.

    Returns dist path. Cleans dist first (so token rotation removes old prefix).
    """
    # Clean dist
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True, exist_ok=True)

    token_dir = dist / token
    token_dir.mkdir(parents=True, exist_ok=True)

    # Copy corpus tree into dist/<TOKEN>/ (preserve silo structure)
    for unit in _collect_units(corpus):
        rel = unit.relative_to(corpus)
        dest = token_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(unit, dest)
        # Also ensure we copy any non-md assets? For prototype, md only

    # Also copy corpus structure for any non-md? Not needed

    # Generate llms.txt at root and under token
    # Collect tokenized URLs for all Units
    units = _collect_units(corpus)
    # Build llms.txt content
    # H1 required, blockquote summary, then sections
    host = mirror_host.rstrip("/")
    llms_lines = [
        "# Private Knowledgebase",
        "",
        "> Personal search corpus — GitHub, chats, notes, PDFs, web fetches — compiled wiki + raw Units.",
        "",
        "This map lists token-gated URLs. The Mirror Token is required in the path prefix.",
        "",
        "## Wiki",
    ]
    # Wiki first (primary surface per spec.md:147)
    wiki_units = [u for u in units if "wiki" in u.parts]
    other_units = [u for u in units if "wiki" not in u.parts]
    for u in wiki_units:
        rel_str = u.relative_to(corpus).as_posix()
        url = f"{host}/{token}/{rel_str}"
        name = u.stem
        llms_lines.append(f"- [{name}]({url}): Wiki page")
    llms_lines.append("")
    llms_lines.append("## Silos")
    for u in other_units:
        rel_str = u.relative_to(corpus).as_posix()
        url = f"{host}/{token}/{rel_str}"
        name = u.stem
        silo = "/".join(u.relative_to(corpus).parent.parts) or "root"
        llms_lines.append(f"- [{name}]({url}): {silo}")
    # Optional section
    llms_lines.extend([
        "",
        "## Optional",
        f"- [Token root]({host}/{token}/): Mirror root (token required)",
    ])
    llms_content = "\n".join(llms_lines) + "\n"

    (dist / "llms.txt").write_text(llms_content, encoding="utf-8")
    (token_dir / "llms.txt").write_text(llms_content, encoding="utf-8")

    # 404.html disables SPA fallback (spec Testing Decisions: untokenized 404)
    (dist / "404.html").write_text("<html><head><title>404 Not Found</title></head><body><h1>404 Not Found</h1><p>Token required.</p></body></html>\n", encoding="utf-8")

    # robots.txt disallow all except llms.txt
    (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\nAllow: /llms.txt\n", encoding="utf-8")

    # _headers with markdown MIME and noindex for tokenized paths
    headers_content = f"""/llms.txt
  Content-Type: text/markdown; charset=utf-8
/{token}/llms.txt
  Content-Type: text/markdown; charset=utf-8
/*.md
  Content-Type: text/markdown; charset=utf-8
/{token}/*
  X-Robots-Tag: noindex
  Cache-Control: public, max-age=3600
/404.html
  Cache-Control: no-store
"""
    (dist / "_headers").write_text(headers_content, encoding="utf-8")

    # _redirects — no corpus at root, but ensure SPA not triggered; rely on 404.html existence
    # Keep minimal: if someone hits /<TOKEN>/*, serve 200 (already via file), else 404.html handles
    (dist / "_redirects").write_text(f"/{token}/*  /{token}/:splat  200\n/*  /404.html  404\n", encoding="utf-8")

    # Also ensure token dir has its own 404? Not needed, root 404 covers
    return dist


if __name__ == "__main__":
    import os
    import argparse

    parser = argparse.ArgumentParser(description="Build Static Mirror for Cloudflare Pages")
    parser.add_argument("--corpus", default="corpus", help="corpus dir")
    parser.add_argument("--dist", default="dist", help="output dist dir")
    parser.add_argument("--token", default=os.environ.get("MIRROR_TOKEN") or os.environ.get("TOKEN") or "devtoken123", help="Mirror Token (hex)")
    parser.add_argument("--host", default=os.environ.get("MIRROR_HOST", "https://example.pages.dev"), help="mirror host")
    args = parser.parse_args()
    corpus = pathlib.Path(args.corpus)
    dist = pathlib.Path(args.dist)
    token = args.token
    host = args.host
    out = build_mirror(corpus, dist, token, host)
    print(f"Built mirror to {out} with token {token} host {host}")
    print(f"Smoke: curl -s http://127.0.0.1:8788/{token}/github/ -I  # via wrangler pages dev ./dist")
    print(f"Deploy: npx wrangler pages deploy {out} --project-name qmd-mirror --branch main")
