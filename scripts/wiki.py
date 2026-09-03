"""Wiki synthesis wrapper for #20 — Workers AI via OpenAI-compatible llmwiki.

Per research #8 + spec.md:141-157 + docs/adr/0006/0008 + llm-wiki-compiler-main:
- After qmd update && qmd embed, llmwiki compile over newly ingested Units → corpus/wiki/
- Frontmatter: source: wiki-compiler, silo: wiki, title, summary, modelId, promptVersion, sources:[...]
- Body citations ^[a.md:1-5, b.md:10-12] + [[wikilinks]] → linter/rules-citations.ts + resolver
- generateIndex/MOC.md + .llmwiki/state.json SHA incremental (detectChanges), refresh --stale
- DEFAULT_PROMPT_BUDGET_CHARS=200_000, COMPILE_CONCURRENCY=5
- Routes via OPENAI_BASE_URL=https://api.cloudflare.com/client/v4/accounts/<id>/ai/v1 + LLMWIKI_MODEL=@cf/meta/llama-3.1-8b-instruct-fp8-fast
- wiki as QMD collection, primary Mirror surface, failure isolated

Thin wrapper: delegates to `npx llmwiki compile` when available and OPENAI_API_KEY present,
otherwise raises ProviderUnavailableError (provider-guard.ts) which orchestrator catches.
For tests (LLMWIKI_MOCK=1), generates deterministic stub wiki pages without LLM.

State layout: STATE_FILE=.llmwiki/state.json at repo root (corpus.parent/.llmwiki).
When corpus is tmp/corpus in tests, state is tmp/.llmwiki/state.json — consistent.
Real llmwiki expects project root with sources/ + wiki/ + .llmwiki/; our corpus/ IS
the sources set (excluding wiki output). See _LINTER_NOTE below.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
from typing import Dict, List, Tuple

from scripts import is_excluded as _shared_is_excluded

DEFAULT_PROMPT_BUDGET_CHARS = 200_000
COMPILE_CONCURRENCY = 5
COMPILE_CONCURRENCY_MAX = 50
WIKI_SILO = "wiki"
WIKI_SOURCE = "wiki-compiler"
DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8-fast"
DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4/accounts/<id>/ai/v1"
STATE_FILE = pathlib.Path(".llmwiki/state.json")
WIKI_DIR = pathlib.Path("corpus/wiki")


def resolve_state_path(corpus: pathlib.Path = pathlib.Path("corpus")) -> pathlib.Path:
    """Resolve Wiki state path relative to the Corpus parent (issue #22).

    Convention: state lives at corpus.parent/.llmwiki/state.json (repo root for
    default corpus=corpus). Falls back to cwd-relative STATE_FILE only when the
    corpus has no parent (corpus == Path(".")).
    """
    try:
        if corpus == pathlib.Path("."):
            return STATE_FILE
        return corpus.parent / ".llmwiki" / "state.json"
    except Exception:
        return STATE_FILE

# Linter mapping note: llmwiki linter/rules-citations.ts resolves ^[file] against
# path.join(root, SOURCES_DIR) where SOURCES_DIR="sources". Our corpus/ IS the
# sources set (Units under corpus/<silo>/*.md, excluding wiki output). So our
# citations are corpus-relative (e.g. github/nebula.md:1-5) and validate against
# corpus/ root. When delegating to real `npx llmwiki compile`, the caller must
# run with a project where sources/ symlinks to corpus/ (excluding wiki), or
# use llmwiki's --sources override if available. Stub validation uses corpus root.


class ProviderUnavailableError(RuntimeError):
    """Mimics llmwiki provider-guard.ts — missing OPENAI_API_KEY or outage."""

    code = "provider_unavailable"


def _is_excluded(path: pathlib.Path) -> bool:
    """Back-compat — delegates to scripts.is_excluded (single source)."""
    return _shared_is_excluded(path)


def slugify(title: str) -> str:
    """Mirror llmwiki utils/markdown.ts slugify for wikilink resolution.

    lower, strip quotes, remove non-alnum (keep unicode letters/numbers/space/-),
    spaces→dashes, collapse dashes, trim dashes.
    """
    s = title.lower().replace("'", "").replace("’", "")
    # Keep unicode letters/numbers, spaces, dashes
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    # \w includes underscore — llmwiki strips non L/N/s/- so underscore removed
    s = re.sub(r"_", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def hash_file(path: pathlib.Path) -> str:
    """SHA256 of file bytes — for .llmwiki/state.json incremental (detectChanges)."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _collect_units(corpus: pathlib.Path) -> List[pathlib.Path]:
    units: List[pathlib.Path] = []
    if not corpus.exists():
        return units
    for p in corpus.rglob("*.md"):
        if _is_excluded(p):
            continue
        try:
            rel = p.relative_to(corpus)
            if rel.parts and rel.parts[0] == WIKI_SILO:
                continue
        except ValueError:
            pass
        units.append(p)
    units.sort()
    return units


def _load_state(state_path: pathlib.Path = STATE_FILE) -> Dict[str, str]:
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if "hashes" in data and isinstance(data["hashes"], dict):
                return {k: v for k, v in data["hashes"].items() if isinstance(v, str)}
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, str)}
        except Exception:
            return {}
    return {}


def _atomic_write(path: pathlib.Path, content: str) -> None:
    """Atomic file write via tmp + rename — avoids partial wiki on crash/outage."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp.", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        pathlib.Path(tmp_name).replace(path)
    except Exception:
        try:
            pathlib.Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _save_state(hashes: Dict[str, str], state_path: pathlib.Path = STATE_FILE) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"hashes": hashes, "version": 1}
    # Atomic for state too
    fd, tmp_name = tempfile.mkstemp(dir=str(state_path.parent), prefix=".tmp.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        pathlib.Path(tmp_name).replace(state_path)
    except Exception:
        try:
            pathlib.Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def detect_changes(corpus: pathlib.Path, state_path: pathlib.Path | None = None) -> Dict[str, str]:
    """Return {rel_posix: new_hash} for new/changed Units (SHA incremental)."""
    if state_path is None:
        state_path = resolve_state_path(corpus)
    current: Dict[str, str] = {}
    for p in _collect_units(corpus):
        rel = p.relative_to(corpus).as_posix()
        current[rel] = hash_file(p)
    previous = _load_state(state_path)
    return {rel: h for rel, h in current.items() if previous.get(rel) != h}


def ensure_provider_available() -> None:
    """Mimic provider-guard.ts ensureProviderAvailable — throws on missing key.

    Uses LLMWIKI_PROVIDER env, default openai per spec for Workers AI.
    """
    provider = os.environ.get("LLMWIKI_PROVIDER", "openai").strip() or "openai"
    provider = provider.lower()
    if provider in ("openai", "atlascloud", "anthropic", "minimax", "copilot"):
        key_vars = {
            "openai": ["OPENAI_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
            "minimax": ["MINIMAX_API_KEY"],
            "copilot": ["GITHUB_TOKEN"],
            "atlascloud": ["ATLASCLOUD_API_KEY"],
        }[provider]
        if not any(os.environ.get(k, "").strip() for k in key_vars):
            raise ProviderUnavailableError(
                f'Provider "{provider}" credentials missing. Set {" or ".join(key_vars)} '
                f"(and OPENAI_BASE_URL={os.environ.get('OPENAI_BASE_URL', DEFAULT_BASE_URL)} "
                f"for Workers AI)"
            )
    return


def _is_provider_error(output: str) -> bool:
    """Detect provider/outage failures (missing key OR Workers AI 5xx/timeout).

    Covers provider-guard.ts throws + Workers AI outage (HTTP 5xx, timeout, ECONN).
    """
    low = output.lower()
    markers = [
        "providerunavailableerror",
        "provider_unavailable",
        "openai_api_key",
        "anthropic_api_key",
        "unauthorized",
        "401",
        "403",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "timed out",
        "econn",
        "fetch failed",
        "failed to fetch",
        "network",
        "workers ai",
        "ai gateway",
    ]
    return any(m in low for m in markers)


def _prompt_budget_chars() -> int:
    try:
        v = int(os.environ.get("LLMWIKI_PROMPT_BUDGET_CHARS", str(DEFAULT_PROMPT_BUDGET_CHARS)))
        return v if v > 0 else DEFAULT_PROMPT_BUDGET_CHARS
    except ValueError:
        return DEFAULT_PROMPT_BUDGET_CHARS


def _concurrency() -> int:
    try:
        v = int(os.environ.get("LLMWIKI_COMPILE_CONCURRENCY", str(COMPILE_CONCURRENCY)))
        v = max(1, min(v, COMPILE_CONCURRENCY_MAX))
        return v
    except ValueError:
        return COMPILE_CONCURRENCY


def _truncate_to_budget(text: str, budget: int) -> str:
    """Enforce DEFAULT_PROMPT_BUDGET_CHARS — proportional truncation for stub."""
    if len(text) <= budget:
        return text
    # Keep head + tail with marker, like llmwiki proportional slice
    head = budget * 3 // 4
    tail = budget - head - 50
    return text[:head] + f"\n\n[... truncated {len(text)-budget} chars for budget {budget} ...]\n\n" + text[-tail:]


def validate_citations(wiki_text: str, corpus: pathlib.Path) -> List[str]:
    """Mirror linter/rules-citations.ts but with corpus/ as sourcesDir.

    Returns list of broken citation errors (empty = all resolve).
    Checks ^[path:START-END] entries resolve to existing corpus/<path>.
    """
    errors: List[str] = []
    for m in re.finditer(r"\^\[([^\]]+)\]", wiki_text):
        block = m.group(1)
        for part in block.split(","):
            part = part.strip()
            if not part:
                continue
            # Strip :START-END or #LSTART-LEND suffix
            filename = re.split(r"[:#]", part, maxsplit=1)[0].strip()
            if not filename:
                errors.append(f"malformed citation entry: {part!r}")
                continue
            # Must be .md and exist under corpus
            target = corpus / filename
            # Prevent escape
            try:
                target.relative_to(corpus)
            except ValueError:
                errors.append(f"citation escapes corpus: {part!r}")
                continue
            if not target.exists():
                errors.append(f"Broken citation ^[{filename}] — source file not found")
    return errors


def validate_wikilinks(wiki_text: str, wiki_files: List[pathlib.Path]) -> List[str]:
    """Mirror collect.ts resolver — [[slug]] or [[slug|Title]] must match a wiki stem.

    Matching is slugify-aware + case-insensitive (MOC.md matches [[moc]] and [[MOC]]).
    """
    # Build stem index: exact + slugified + lower
    index: Dict[str, pathlib.Path] = {}
    for p in wiki_files:
        stem = p.stem
        index[stem] = p
        index[stem.lower()] = p
        index[slugify(stem)] = p
    errors: List[str] = []
    for m in re.finditer(r"\[\[([^\]]+)\]\]", wiki_text):
        inner = m.group(1).strip()
        # Piped alias [[slug|Title]] — resolve left side
        slug = inner.split("|", 1)[0].strip()
        if not slug:
            errors.append("empty wikilink [[]]")
            continue
        if slug not in index and slug.lower() not in index and slugify(slug) not in index:
            errors.append(f"Broken wikilink [[{slug}]] — no wiki page matches")
    return errors


def _stub_generate_wiki_page(
    corpus: pathlib.Path, wiki_path: pathlib.Path, sources: List[pathlib.Path], model: str
) -> None:
    """Generate deterministic stub wiki page with frontmatter, citations, wikilinks."""
    cited = sources[:3]
    sources_rel = [p.relative_to(corpus).as_posix() for p in cited]
    cites = ", ".join(f"{rel}:1-5" for rel in sources_rel)
    wikilinks = "[[MOC]]" if len(cited) > 1 else "[[concept-index]]"
    title = "Concepts Overview" if not cited else f"Concept: {cited[0].stem}"
    summary = f"Synthesized from {len(sources_rel)} Units via {model}."
    fm = [
        "---",
        f"source: {WIKI_SOURCE}",
        f"silo: {WIKI_SILO}",
        f'title: "{title}"',
        f'summary: "{summary}"',
        f'modelId: "{model}"',
        'promptVersion: "1.0"',
        "sources:",
    ]
    for s in sources_rel:
        fm.append(f'  - "{s}"')
    fm.append("---")
    fm.append("")
    # Enforce budget: snippets truncated proportionally to DEFAULT_PROMPT_BUDGET_CHARS
    budget = _prompt_budget_chars()
    snippets: List[str] = []
    for src in cited:
        try:
            txt = src.read_text(encoding="utf-8")[:2000].replace("\n", " ")
            snippets.append(txt[:500])
        except Exception:
            snippets.append("")
    snippet_block = _truncate_to_budget(" ".join(snippets), min(budget, 5000))
    body = [
        f"> {summary}",
        "",
        f"# {title}",
        "",
        f"Synthesized concept page citing sources ^[{cites}] and linked {wikilinks}.",
        "",
        f"Sources: {', '.join(sources_rel)}",
        "",
        "## Details",
        "",
        snippet_block,
        "",
        "This stub mimics llmwiki extraction+generation without LLM for tests.",
        "",
    ]
    _atomic_write(wiki_path, "\n".join(fm + body))


def _generate_pages_concurrent(
    jobs: List[Tuple[pathlib.Path, pathlib.Path, List[pathlib.Path], str]],
) -> None:
    """Generate stub pages with COMPILE_CONCURRENCY limit (mirrors p-limit)."""
    workers = _concurrency()
    if len(jobs) <= 1:
        for corpus, path, sources, model in jobs:
            _stub_generate_wiki_page(corpus, path, sources, model)
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_stub_generate_wiki_page, c, p, s, m) for c, p, s, m in jobs]
        for f in concurrent.futures.as_completed(futs):
            f.result()


def compile_wiki(
    corpus: pathlib.Path = pathlib.Path("corpus"),
    state_path: pathlib.Path | None = None,
    mock: bool | None = None,
) -> Dict[str, int]:
    """Compile wiki after embed — Workers AI routing, SHA incremental, failure isolated.

    Returns {"compiled": n, "skipped": n, "errors": n}.
    Raises ProviderUnavailableError if OPENAI_API_KEY missing (provider-guard.ts).
    When LLMWIKI_MOCK=1 or mock=True, generates stub pages without LLM.

    Enforces DEFAULT_PROMPT_BUDGET_CHARS truncation and COMPILE_CONCURRENCY limit.
    Generates corpus/wiki/concepts/<slug>.md, MOC.md, index.md, .llmwiki/state.json atomically.
    State lives at corpus.parent/.llmwiki/state.json by convention (repo root);
    pass explicit state_path for temp corpora in tests.
    """
    if state_path is None:
        state_path = resolve_state_path(corpus)
    if mock is None:
        mock = os.environ.get("LLMWIKI_MOCK", "").strip() in ("1", "true", "yes")

    if not mock:
        ensure_provider_available()

    # Read budget/concurrency now — enforced in stub generation below
    budget = _prompt_budget_chars()
    workers = _concurrency()
    _ = (budget, workers)

    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
    model = os.environ.get("LLMWIKI_MODEL", DEFAULT_MODEL)
    _ = base_url

    changed = detect_changes(corpus, state_path)
    current_hashes: Dict[str, str] = {}
    for p in _collect_units(corpus):
        current_hashes[p.relative_to(corpus).as_posix()] = hash_file(p)

    if not changed and state_path.exists():
        return {"compiled": 0, "skipped": len(current_hashes), "errors": 0}

    if mock or os.environ.get("LLMWIKI_MOCK") == "1":
        wiki_dir = corpus / WIKI_SILO
        concepts_dir = wiki_dir / "concepts"
        moc_file = wiki_dir / "MOC.md"
        index_file = wiki_dir / "index.md"
        units = _collect_units(corpus)
        if not units:
            concepts_dir.mkdir(parents=True, exist_ok=True)
            _save_state(current_hashes, state_path)
            return {"compiled": 0, "skipped": 0, "errors": 0}

        concepts_dir.mkdir(parents=True, exist_ok=True)
        slug = "overview"
        if len(changed) == 1:
            rel = next(iter(changed))
            silo = pathlib.Path(rel).parts[0] if "/" in rel else "general"
            slug = f"{silo}-concept"

        target = concepts_dir / f"{slug}.md"
        sources = [corpus / rel for rel in changed.keys()] if changed else units
        if not sources:
            sources = units

        jobs: List[Tuple[pathlib.Path, pathlib.Path, List[pathlib.Path], str]] = [
            (corpus, target, sources, model)
        ]
        if len(units) >= 2 and slug != "concept-index":
            second = concepts_dir / "concept-index.md"
            if not second.exists():
                jobs.append((corpus, second, units[:2], model))
        _generate_pages_concurrent(jobs)

        # Ensure cross-link from second to first if both exist (atomic append via rewrite)
        second_path = concepts_dir / "concept-index.md"
        if second_path.exists() and slug != "concept-index":
            text = second_path.read_text(encoding="utf-8")
            if f"[[{slug}]]" not in text:
                _atomic_write(second_path, text + f"\nSee also [[{slug}]]\n")

        moc_content = "\n".join(
            [
                "---",
                f"source: {WIKI_SOURCE}",
                f"silo: {WIKI_SILO}",
                'title: "MOC"',
                'summary: "Map of Content for wiki."',
                f'modelId: "{model}"',
                'promptVersion: "1.0"',
                "sources: []",
                "---",
                "",
                "> MOC for wiki.",
                "",
                "# MOC",
                "",
                f"- [[{slug}]]",
                "- [[concept-index]]",
                "",
            ]
        )
        _atomic_write(moc_file, moc_content)
        _atomic_write(index_file, moc_content)

        _save_state(current_hashes, state_path)
        return {"compiled": len(changed), "skipped": len(current_hashes) - len(changed), "errors": 0}

    # Real llmwiki path — delegate to npx llmwiki compile
    # Requires Node + llmwiki + OPENAI_API_KEY. Project root is corpus.parent
    # (llmwiki expects sources/ + wiki/ + .llmwiki/ under root).
    cmd = ["npx", "llmwiki", "compile"]
    env = os.environ.copy()
    env.setdefault("LLMWIKI_PROMPT_BUDGET_CHARS", str(DEFAULT_PROMPT_BUDGET_CHARS))
    env.setdefault("LLMWIKI_COMPILE_CONCURRENCY", str(COMPILE_CONCURRENCY))
    # Run from corpus.parent so .llmwiki/state.json aligns, if it exists
    cwd = str(corpus.parent) if corpus.name != "." else str(pathlib.Path.cwd())
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        combined = (result.stdout or "") + (result.stderr or "")
        if _is_provider_error(combined):
            raise ProviderUnavailableError(combined[:2000])
        raise RuntimeError(f"llmwiki compile failed {result.returncode}: {combined[:500]}")

    _save_state(current_hashes, state_path)
    return {"compiled": len(changed), "skipped": 0, "errors": 0}


def refresh_stale(
    corpus: pathlib.Path = pathlib.Path("corpus"),
    state_path: pathlib.Path | None = None,
) -> Dict[str, int]:
    """Wrapper for `llmwiki refresh --stale` — recompiles only stale pages.

    Incremental by design: detect_changes() already limits work to new/changed
    Units, so refresh delegates to compile_wiki (same SHA state). Not a middle-man:
    it documents the --stale intent for callers/orchestrator that prefer the
    refresh verb. Real `npx llmwiki refresh --stale` is used when not mocked;
    here compile path handles both.
    """
    if state_path is None:
        state_path = resolve_state_path(corpus)
    return compile_wiki(corpus, state_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Wiki synthesis wrapper for Workers AI")
    parser.add_argument("command", choices=["compile", "refresh"], nargs="?", default="compile")
    parser.add_argument("--corpus", default="corpus")
    parser.add_argument("--state", default=str(STATE_FILE))
    parser.add_argument("--mock", action="store_true", help="generate stub without LLM")
    args = parser.parse_args()
    corpus = pathlib.Path(args.corpus)
    state = pathlib.Path(args.state)
    if args.command == "refresh":
        res = refresh_stale(corpus, state)
    else:
        res = compile_wiki(corpus, state, mock=args.mock or None)
    print(f"Wiki compile result: {res}")
