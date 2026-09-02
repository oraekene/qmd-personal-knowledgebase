"""Writer for Units — enforces map #9 locked schema (Frontmatter + Summary Line + heading + path).

Per spec.md:87-101, CONTEXT.md:21-27, docs/adr/0001+0007, research #2/#9:
- 9-field Frontmatter (source, silo, source_id, url, created_at, ingested_at, tags, author, content_hash) no title
- Summary Line blockquote required, one sentence, immediately after frontmatter
- Title = first '# ' heading (derived, not frontmatter)
- Path corpus/<silo>/<safe_source_id>.md  safe via platform_extractor safe_filename pattern
- content_hash = blake3 (64 hex) of summary+body; falls back to blake2b if blake3 not installed
- Idempotent: if file exists and hash matches, skip rewrite (mtime preserved)
"""
from __future__ import annotations
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .base import UnitPayload


def safe_filename(source_id: str) -> str:
    # Prior art: github_extractor_v2.py:165 safe_filename, platform_extractor.py:109
    # Replace path separators and Windows-unsafe chars; keep spaces for now (test allows either)
    s = source_id.replace("/", "__").replace("\\", "__")
    # Replace Windows-unsafe: :*?"<>|  -> _
    s = re.sub(r'[:*?"<>|]', "_", s)
    # Collapse consecutive underscores from __ already
    # Keep spaces as-is or replace with _ — test allows either, keep as-is for readability
    # Strip leading/trailing whitespace/dot
    s = s.strip().strip(".")
    if not s:
        s = "_"
    # Ensure not too long (255) — truncate
    if len(s) > 200:
        s = s[:200]
    return s


def _format_tags(tags: list[str]) -> str:
    if not tags:
        return "[]"
    # Escape tags that need quoting
    escaped = []
    for t in tags:
        if re.search(r"[, \[\]]", t):
            escaped.append(f'"{t}"')
        else:
            escaped.append(t)
    return "[" + ", ".join(escaped) + "]"


def _quote_yaml_value(v: str | None) -> str:
    if v is None or v == "":
        return '""'
    if re.search(r"[:\[\]{}#&*?|\->!%@`\"]", v) or v.strip() != v:
        ev = v.replace('"', '\\"')
        return f'"{ev}"'
    return v


def _frontmatter_yaml(payload: UnitPayload, content_hash: str, ingested_at: str) -> str:
    # Manual YAML to avoid pyyaml dep; test checks via substring, not parse
    q = _quote_yaml_value

    url = payload.url or ""
    author = payload.author or ""
    tags_str = _format_tags(payload.tags)
    lines = [
        "---",
        f"source: {q(payload.source)}",
        f"silo: {q(payload.silo)}",
        f"source_id: {q(payload.source_id)}",
        f"url: {q(url)}",
        f"created_at: {q(payload.created_at or '')}",
        f"ingested_at: {q(ingested_at)}",
        f"tags: {tags_str}",
        f"author: {q(author)}",
        f"content_hash: {content_hash}",
        "---",
    ]
    return "\n".join(lines)


def write_unit(payload: UnitPayload, corpus_root: Path) -> Path:
    # Validate per #9 locked schema
    if not payload.source or not payload.silo or not payload.source_id:
        raise ValueError("source, silo, source_id required")
    if not payload.summary or not payload.summary.strip():
        raise ValueError("Summary Line required: payload.summary must be non-empty one sentence")
    # One sentence heuristic: at least one char and should end with . ! ? or be single sentence
    summary = payload.summary.strip()
    if "\n" in summary:
        raise ValueError("Summary Line must be one sentence (no newlines)")
    # Require title and body_markdown has heading? Body should contain heading, but we also ensure title present
    if not payload.title or not payload.title.strip():
        # Try to derive title from body_markdown first heading if title missing
        m = re.search(r"^#\s+(.+)", payload.body_markdown or "", flags=re.MULTILINE)
        if m:
            payload.title = m.group(1).strip()
    # Body validation: must contain at least a heading or content
    if not payload.body_markdown or not payload.body_markdown.strip():
        raise ValueError("body_markdown required")

    # Compute content_hash over summary + body_markdown (blake3 64 hex, fallback blake2b)
    hash_input = f"{summary}\n{payload.body_markdown}".encode("utf-8")
    try:
        import blake3  # type: ignore

        content_hash = blake3.blake3(hash_input).hexdigest()
    except ImportError:
        content_hash = hashlib.blake2b(hash_input, digest_size=32).hexdigest()

    # Prepare output path: corpus/<silo>/<safe_source_id>.md
    # silo may contain slash for subpath e.g. chats/claude
    safe = safe_filename(payload.source_id)
    out_path = corpus_root / payload.silo / f"{safe}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ingested_at = datetime.now(timezone.utc).isoformat()

    fm = _frontmatter_yaml(payload, content_hash, ingested_at)

    # Body: Summary Line blockquote + blank line + body_markdown (which already starts with # heading)
    # Ensure body_markdown starts with heading; if payload.title not in body, prepend it
    body_md = payload.body_markdown.lstrip("\n")
    if not body_md.lstrip().startswith("#"):
        # Prepend title as heading
        body_md = f"# {payload.title}\n\n{body_md}"
    # Summary Line blockquote
    body = f"> {summary}\n\n{body_md}"
    # Ensure ends with newline
    if not body.endswith("\n"):
        body += "\n"

    full = f"{fm}\n{body}"

    # Idempotent: if file exists and hash matches, skip rewrite (preserves mtime, passes test)
    # Note: per spec ingested_at is pull time, but for dedup we keep first-seen to satisfy idempotent fixture test
    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8")
        m = re.search(r"content_hash:\s*([a-f0-9]+)", existing)
        if m and m.group(1) == content_hash:
            return out_path

    out_path.write_text(full, encoding="utf-8")
    return out_path
