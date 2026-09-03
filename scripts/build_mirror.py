"""Build Static Mirror — token-gated Cloudflare Pages deploy for #19.

Per research #5 + spec.md:26-30,132-135 + docs/adr/0002/0003 + #13 prototype ccf94b2:
- Option A: dist/<TOKEN>/ containing full corpus copy (build-time copy, cleans dist for rotation)
- dist/ root has llms.txt, 404.html, robots.txt, _headers, _redirects — no corpus untokenized
- llms.txt H1 + blockquote + ## Wiki (primary) + ## Silos tokenized URLs, predictable https://host/<TOKEN>/<silo>/<path>.md
- Token rotation = new `openssl rand -hex 16` + redeploy (old prefix gone after rebuild cleans dist)
- Orchestrator hook: build_mirror(corpus, dist, token) then wrangler pages deploy

Production promotion of prototype/static-mirror ccf94b2.
"""

from __future__ import annotations

import pathlib
import re
import shutil
from typing import List

_TOKEN_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def _is_excluded(path: pathlib.Path) -> bool:
    """Single helper for state/qmd exclusion — fixes Duplicated Code."""
    return "_state" in path.parts or ".qmd" in path.parts


def _collect_units(corpus: pathlib.Path) -> List[pathlib.Path]:
    """Collect markdown Units under corpus, sorted, excluding state/qmd."""
    units: List[pathlib.Path] = []
    if not corpus.exists():
        return units
    for p in corpus.rglob("*.md"):
        if _is_excluded(p):
            continue
        units.append(p)
    units.sort()
    return units


def _validate_token(token: str) -> None:
    if not token:
        raise ValueError("Mirror Token must not be empty — generate via `openssl rand -hex 16`")
    if not _TOKEN_HEX_RE.match(token):
        raise ValueError(f"Mirror Token must be hex (openssl rand -hex 16), got {token!r}")
    if len(token) < 16:
        raise ValueError(f"Mirror Token too short ({len(token)}), expected >=16 hex chars")


def _validate_host(host: str) -> str:
    host = host.rstrip("/")
    if not host.startswith("https://"):
        raise ValueError(f"mirror_host must be https://, got {host!r}")
    return host


def build_mirror(
    corpus: pathlib.Path,
    dist: pathlib.Path,
    token: str,
    host: str = "https://qmd-mirror.pages.dev",
    mirror_host: str | None = None,
) -> pathlib.Path:
    """Build mirror dist from corpus with token prefix.

    Returns dist path. Cleans dist first (so token rotation removes old prefix).
    Mirrors entire corpus tree into dist/<TOKEN>/, generates llms.txt at root and token,
    plus 404.html, _headers, _redirects, robots.txt.

    Predictable URLs: https://host/<TOKEN>/<silo>/<path>.md

    Accepts `host` (spec #19) and alias `mirror_host` (prototype compat).
    """
    if mirror_host is not None:
        host = mirror_host
    _validate_token(token)
    host = _validate_host(host)

    # Atomic build: write to tmp then swap — avoids losing previous dist on crash
    tmp_dist = dist.with_name(dist.name + ".tmp.build")
    if tmp_dist.exists():
        shutil.rmtree(tmp_dist)
    tmp_dist.mkdir(parents=True, exist_ok=True)

    token_dir = tmp_dist / token
    token_dir.mkdir(parents=True, exist_ok=True)

    # Collect Units (for llms.txt) — before copy, sorted
    units = _collect_units(corpus)

    # Copy corpus tree into tmp_dist/<TOKEN>/ preserving silo structure
    # Copy all files (not just md) for full mirror, but tests focus on md Units
    if corpus.exists():
        for src in corpus.rglob("*"):
            if src.is_dir():
                continue
            if _is_excluded(src):
                continue
            try:
                rel = src.relative_to(corpus)
            except ValueError:
                continue
            dest = token_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # Generate llms.txt at root and under token — both with tokenized URLs
    llms_lines: List[str] = [
        "# Private Knowledgebase",
        "",
        "> Personal search corpus — GitHub, chats, notes, PDFs, web fetches — compiled wiki + raw Units.",
        "",
        "This map lists token-gated URLs. The Mirror Token is required in the path prefix.",
        "",
        "## Wiki",
    ]
    # Strict silo check — only top-level wiki silo is Wiki (fixes Feature Envy / misclassify)
    def _is_wiki(u: pathlib.Path) -> bool:
        try:
            rel = u.relative_to(corpus)
            return rel.parts[0] == "wiki" if rel.parts else False
        except ValueError:
            return False

    wiki_units = [u for u in units if _is_wiki(u)]
    other_units = [u for u in units if not _is_wiki(u)]

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
        rel_parent = u.relative_to(corpus).parent
        silo = "/".join(rel_parent.parts) if rel_parent.parts else "root"
        llms_lines.append(f"- [{name}]({url}): {silo}")

    llms_lines.extend(
        [
            "",
            "## Optional",
            f"- [Token root]({host}/{token}/): Mirror root (token required)",
        ]
    )
    llms_content = "\n".join(llms_lines) + "\n"

    (tmp_dist / "llms.txt").write_text(llms_content, encoding="utf-8")
    (token_dir / "llms.txt").write_text(llms_content, encoding="utf-8")

    # 404.html disables SPA fallback — untokenized paths must 404
    (tmp_dist / "404.html").write_text(
        "<html><head><title>404 Not Found</title></head><body><h1>404 Not Found</h1><p>Token required.</p></body></html>\n",
        encoding="utf-8",
    )

    # robots.txt — disallow all but llms.txt
    (tmp_dist / "robots.txt").write_text("User-agent: *\nDisallow: /\nAllow: /llms.txt\n", encoding="utf-8")

    # _headers — Cloudflare Pages headers: markdown MIME, noindex, cache
    # Fix glob for nested md: Pages needs explicit depth patterns; include noindex for all tokenized
    headers_content = f"""/llms.txt
  Content-Type: text/markdown; charset=utf-8
  X-Robots-Tag: noindex
/{token}/llms.txt
  Content-Type: text/markdown; charset=utf-8
  X-Robots-Tag: noindex
/*.md
  Content-Type: text/markdown; charset=utf-8
  X-Robots-Tag: noindex
/*/*.md
  Content-Type: text/markdown; charset=utf-8
  X-Robots-Tag: noindex
/*/*/*.md
  Content-Type: text/markdown; charset=utf-8
  X-Robots-Tag: noindex
/{token}/*
  X-Robots-Tag: noindex
  Cache-Control: public, max-age=3600
/{token}/*.md
  Content-Type: text/markdown; charset=utf-8
/{token}/*/*.md
  Content-Type: text/markdown; charset=utf-8
/{token}/*/*/*.md
  Content-Type: text/markdown; charset=utf-8
/404.html
  Cache-Control: no-store
"""
    (tmp_dist / "_headers").write_text(headers_content, encoding="utf-8")

    # _redirects — no SPA; token prefix 200, else 404.html
    (tmp_dist / "_redirects").write_text(f"/{token}/*  /{token}/:splat  200\n/*  /404.html  404\n", encoding="utf-8")

    # Atomic swap: replace dist with tmp_dist (preserves previous on failure, fixes rotation)
    if dist.exists():
        shutil.rmtree(dist)
    tmp_dist.rename(dist)
    return dist


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Build Static Mirror for Cloudflare Pages")
    parser.add_argument("--corpus", default="corpus", help="corpus dir")
    parser.add_argument("--dist", default="dist", help="output dist dir")
    parser.add_argument(
        "--token",
        default=os.environ.get("MIRROR_TOKEN") or os.environ.get("TOKEN") or "",
        help="Mirror Token (hex, via openssl rand -hex 16)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MIRROR_HOST", "https://qmd-mirror.pages.dev"),
        help="mirror host https://",
    )
    args = parser.parse_args()

    if not args.token:
        # Fallback for local smoke if mirror-token.txt exists
        token_file = pathlib.Path("mirror-token.txt")
        if token_file.exists():
            args.token = token_file.read_text(encoding="utf-8").strip()
    if not args.token:
        parser.error("Mirror Token required: --token <hex> or env MIRROR_TOKEN or mirror-token.txt")

    corpus = pathlib.Path(args.corpus)
    dist = pathlib.Path(args.dist)
    out = build_mirror(corpus, dist, args.token, args.host)
    print(f"Built mirror to {out} with token {args.token} host {args.host}")
    print(f"Smoke: npx wrangler pages dev {out} --port 8788  # then curl -s http://127.0.0.1:8788/{args.token}/llms.txt")
    print(f"Deploy: npx wrangler pages deploy {out} --project-name qmd-mirror --branch main")
