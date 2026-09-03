"""Acceptance harness (gate) for #21 — on-demand v1 check.

Usage:
  uv run python scripts/acceptance.py --mock   # no qmd/tunnel needed
  uv run python scripts/acceptance.py --live   # needs qmd + TUNNEL_URL + MIRROR deploy

One-seam: corpus fixtures in, Units/dist/search out. No internal call-sequence asserts.
Live-only checks (sleep/wake, Claude.ai web, fetch-tool, qmd embed timing) fail
with prerequisites message when qmd/tunnel absent — never false-green.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    return ok


def run_mock() -> int:
    from connectors.sdk.base import UnitPayload
    from connectors.sdk.writer import write_unit
    from auth_proxy.proxy import ProxyApp, check_origin
    from scripts.build_mirror import build_mirror
    from scripts.wiki import compile_wiki, validate_citations

    failures = 0
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        corpus = tmp_path / "corpus"

        # 1. OCR decision query fixture in top-5 (mock: file grep over notes/chats)
        ocr = UnitPayload(
            source="notes", silo="notes", source_id="ocr-choice",
            url="", created_at="2026-09-01T00:00:00+00:00", tags=[], author="",
            title="OCR models I selected", summary="OCR models I selected.",
            body_markdown="# OCR models I selected\n\nWe picked LiteParse locally for private PDFs.",
        )
        write_unit(ocr, corpus)
        for i in range(49):
            write_unit(UnitPayload(
                source="notes", silo="notes", source_id=f"filler-{i}",
                url="", created_at="2026-09-01T00:00:00+00:00", tags=[], author="",
                title=f"filler {i}", summary="filler",
                body_markdown=f"# filler {i}\n\nunrelated content {i}.",
            ), corpus)
        hits = [p for p in corpus.rglob("*.md") if "ocr models i selected" in p.read_text(encoding="utf-8").lower()]
        if not _check("mock/ocr-top5", hits and hits[0].name == "ocr-choice.md", f"{len(hits)} hit(s)"):
            failures += 1

        # 2. Silo scoping (path scoping mock)
        scoped = list((corpus / "notes").glob("*.md"))
        unified = list(corpus.rglob("*.md"))
        if not _check("mock/silo-scoping", len(scoped) == 50 and len(unified) >= 50, f"notes={len(scoped)}"):
            failures += 1

        # 3. Dual-account dedup (first-seen-wins on disk)
        gh1 = UnitPayload(
            source="github", silo="github", source_id="oraekene/nebula",
            url="https://github.com/oraekene/nebula", created_at="2026-09-01T00:00:00+00:00",
            tags=[], author="oraekene", title="nebula", summary="Nebula repo.",
            body_markdown="# nebula\n\nContent.",
        )
        gh2 = UnitPayload(
            source="github", silo="github", source_id="oraekene/nebula",
            url="https://github.com/oraekene/nebula", created_at="2026-09-01T00:00:00+00:00",
            tags=[], author="oraekene", title="nebula", summary="Nebula repo dup.",
            body_markdown="# nebula\n\nContent dup.",
        )
        out1 = write_unit(gh1, corpus)
        out2 = write_unit(gh2, corpus)
        dup_files = list((corpus / "github").glob("*.md"))
        if not _check("mock/no-dup-repos", out1 == out2 and len(dup_files) == 1, f"{len(dup_files)} file(s)"):
            failures += 1

        # 4. Auth proxy 200/401 + origin 403 when configured
        app_open = ProxyApp("tok", lambda m, p, h, b: (200, {}, b"ok"))
        app_strict = ProxyApp("tok", lambda m, p, h, b: (200, {}, b"ok"), allowed_origins=("https://claude.ai",))
        ok_auth = (
            app_open.handle("POST", "/mcp", {"Authorization": "Bearer tok"}, b"{}")[0] == 200
            and app_open.handle("POST", "/mcp", {"Authorization": "Bearer wrong"}, b"{}")[0] == 401
            and app_strict.handle("POST", "/mcp", {"Authorization": "Bearer tok", "Origin": "https://attacker.example"}, b"{}")[0] == 403
            and check_origin({"Origin": "https://claude.ai"}, ("https://claude.ai",))
        )
        if not _check("mock/auth-proxy", ok_auth, "200/401/403 matrix"):
            failures += 1

        # 5. Mirror token-gated + root redacted
        dist = tmp_path / "dist"
        token = "a" * 32
        build_mirror(corpus, dist, token, host="https://qmd-mirror.pages.dev")
        token_txt = (dist / token / "llms.txt").read_text(encoding="utf-8")
        root_txt = (dist / "llms.txt").read_text(encoding="utf-8")
        ok_mirror = (
            (dist / token / "github").exists()
            and not (dist / "github").exists()
            and token in token_txt
            and token not in root_txt
            and token_txt.startswith("# Private Knowledgebase")
        )
        if not _check("mock/mirror-gated", ok_mirror, "token 200-file / no-token 404-file / root redacted"):
            failures += 1

        # 6. Wiki citations resolve (mock compile)
        os.environ["LLMWIKI_MOCK"] = "1"
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            res = compile_wiki(corpus, tmp_path / ".llmwiki" / "state.json")
            wiki_files = list((corpus / "wiki").rglob("*.md"))
            broken = []
            for wf in wiki_files:
                broken += validate_citations(wf.read_text(encoding="utf-8"), corpus)
            if not _check("mock/wiki-citations", bool(wiki_files) and not broken, f"{res} files={len(wiki_files)}"):
                failures += 1
        finally:
            os.environ.pop("LLMWIKI_MOCK", None)

        # 7. 50-unit ingest timing (<5min mock)
        dt = time.time() - t0
        if not _check("mock/50-units-timing", dt < 300, f"{dt:.1f}s"):
            failures += 1

    print(f"mock acceptance: {'GREEN' if not failures else f'{failures} FAIL'}")
    return 1 if failures else 0


def run_live() -> int:
    missing = []
    if shutil.which("qmd") is None and not pathlib.Path("qmd-main/package.json").exists():
        missing.append("qmd (binary or qmd-main/)")
    for env in ("TUNNEL_URL", "MIRROR_TOKEN"):
        if not os.environ.get(env, "").strip():
            missing.append(env)
    print("live acceptance prerequisites: " + (", ".join(missing) if missing else "ok"))
    if missing:
        print("FAIL live — prerequisites missing (sleep/wake, Claude.ai web, fetch-tool need live stack). Run --mock for gate.")
        return 2
    print("TODO live: qmd update && embed 50 Units, time <5min, then 7 live checks. Not yet wired — see #21.")
    return 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Acceptance harness gate for #21")
    ap.add_argument("--mock", action="store_true", help="run mockable checks (no qmd/tunnel)")
    ap.add_argument("--live", action="store_true", help="run live checks (needs qmd + tunnel + token)")
    args = ap.parse_args()
    if args.live:
        sys.exit(run_live())
    sys.exit(run_mock())
