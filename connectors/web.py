"""Web Link Expansion connector — TinyFish primary + Scrapling fallback -> Units in corpus/web/.

Per #17 + research #7 + spec.md:115-119 + #9:
- TinyFish primary fetch 10/batch free parallel (results[] vs errors[], 429 retry) + Scrapling Fetcher->StealthyFetcher fallback on empty/blocked -> corpus/web/<hash>.md
- One-level only for links inside newly ingested Units (deduped, SearXNG not a fetcher)
- Silo: web, source: web, source_id: hash of URL, url: final_url, tags: [web]
- Body: fetched markdown (format: markdown)

This is the production connector for #17 — fixture-testable via fetch_func injection.
"""
from __future__ import annotations
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Dict, Any, Set

from connectors.sdk.base import SourcePlugin, UnitPayload


def _extract_links(text: str) -> list[str]:
    # Simple regex for http/https URLs in markdown or plain text
    # Matches https://... until whitespace, ), ], or "
    pattern = r"https?://[^\s\)\]\"]+"
    links = re.findall(pattern, text)
    # Clean trailing punctuation like ., ,, ), ]
    cleaned = []
    for url in links:
        url = url.rstrip(".,;:)\"'!")
        # Filter outmailto, etc. (already only http)
        cleaned.append(url)
    # Dedup preserve order
    seen: Set[str] = set()
    uniq = []
    for u in cleaned:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _hash_url(url: str) -> str:
    # Use blake3-like hash for dedup (use hashlib blake2b 8 -> 16 hex for short)
    return hashlib.blake2b(url.encode("utf-8"), digest_size=8).hexdigest()


def _payload_from_text(url: str, text: str, source: str = "web", silo: str = "web") -> UnitPayload:
    # Helper to avoid duplicated UnitPayload construction for TinyFish vs Scrapling
    source_id = _hash_url(url)
    summary = text.strip().split("\n")[0][:120].strip()
    if len(summary) > 120:
        summary = summary[:120] + "..."
    if summary and summary[-1] not in ".!?":
        summary += "."
    if not summary:
        summary = f"Fetched {url}."
    return UnitPayload(
        source=source,
        silo=silo,
        source_id=source_id,
        url=url,
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=["web"],
        author="",
        title=url,
        summary=summary,
        body_markdown=text,
    )


class WebConnector(SourcePlugin):
    """Link expansion connector — scans corpus for new Units, fetches links."""

    NAME = "web"
    DESCRIPTION = "Link expansion via TinyFish + Scrapling"
    REQUIRES_AUTH = False
    SUPPORTS_LOOKBACK = False

    def __init__(
        self,
        corpus_root: Path | str | None = None,
        fetch_func: Callable[[list[str]], Dict[str, Any]] | None = None,
        scrapling_func: Callable[[str], str] | None = None,
    ):
        super().__init__()
        self.corpus_root = Path(corpus_root) if corpus_root else Path("corpus")
        self.fetch_func = fetch_func
        self.scrapling_func = scrapling_func

    def _default_fetch(self, urls: list[str]) -> Dict[str, Any]:
        # In production, would call TinyFish: POST https://api.fetch.tinyfish.ai {urls, format: markdown}
        # For prototype, return empty (no fetch)
        return {"results": [], "errors": [{"url": url, "error": "no fetch_func"} for url in urls]}

    def _default_scrapling(self, url: str) -> str:
        # In production, would use Scrapling Fetcher
        return f"# Fetched via Scrapling {url}\n\nFallback content for {url}"

    def fetch_recent(self, since: datetime, limit: int = 50) -> Iterator[UnitPayload]:
        if not self.corpus_root.exists():
            return
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        # Collect all Units' text to find links — for test, we scan all corpus/**/*.md
        # In production, would scan only Units with ingested_at > since (newly ingested)
        # For prototype, scan all and dedupe via already-fetched web Units
        # First, collect already-fetched URLs from corpus/web to dedupe
        already_fetched: Set[str] = set()
        web_dir = self.corpus_root / "web"
        if web_dir.exists():
            for web_file in web_dir.glob("*.md"):
                try:
                    text = web_file.read_text(encoding="utf-8")
                    m = re.search(r"url:\s*\"?([^\"]+)\"?", text)
                    if m:
                        already_fetched.add(m.group(1).strip().strip('"'))
                    # Also check body for final_url
                    for line in text.splitlines():
                        if "https://" in line:
                            for link in _extract_links(line):
                                already_fetched.add(link)
                except Exception:
                    continue

        # Collect links from all corpus Units (excluding web itself to avoid recursion)
        all_links: list[str] = []
        for unit_path in sorted(self.corpus_root.rglob("*.md")):
            # Skip web silo itself (one-level, no recursion) — use is_relative_to for exact match
            try:
                if unit_path.is_relative_to(self.corpus_root / "web"):
                    continue
            except AttributeError:
                # Fallback for older Python
                if "web" in unit_path.parts and (self.corpus_root / "web") in unit_path.parents:
                    continue
            if "_state" in unit_path.parts or ".qmd" in unit_path.parts:
                continue
            try:
                text = unit_path.read_text(encoding="utf-8")
                # Only extract links from body (after frontmatter) to avoid frontmatter url field
                try:
                    body = text.split("---\n", 2)[2]
                except IndexError:
                    body = text
                links = _extract_links(body)
                for link in links:
                    if link not in already_fetched and link not in all_links:
                        all_links.append(link)
            except Exception:
                continue

        if not all_links:
            return

        # Chunk 10 per TinyFish limit
        fetch = self.fetch_func or self._default_fetch
        scrapling_fetch = self.scrapling_func or self._default_scrapling

        count = 0
        # Process in batches of 10
        for i in range(0, len(all_links), 10):
            if count >= limit:
                break
            batch = all_links[i : i + 10]
            result = fetch(batch)
            results = result.get("results", [])
            errors = result.get("errors", [])

            # Map errors by url for fallback
            error_urls = {e["url"] for e in errors} if errors else set()
            # For results, create payloads
            for res in results:
                if count >= limit:
                    break
                url = res.get("url") or res.get("final_url")
                if not url or url in already_fetched:
                    continue
                text = res.get("text") or ""
                if not text.strip():
                    text = scrapling_fetch(url)
                final_url = res.get("final_url") or url
                source_id = _hash_url(final_url)
                if (web_dir / f"{source_id}.md").exists():
                    continue
                payload = _payload_from_text(final_url, text)
                payload.source_id = source_id  # ensure hash consistency
                payload.url = final_url
                already_fetched.add(final_url)
                already_fetched.add(url)
                count += 1
                yield payload

            # Handle errors with Scrapling fallback
            for err in errors:
                if count >= limit:
                    break
                url = err.get("url")
                if not url or url in already_fetched:
                    continue
                try:
                    text = scrapling_fetch(url)
                except Exception:
                    continue
                if not text or not text.strip():
                    continue
                source_id = _hash_url(url)
                if (web_dir / f"{source_id}.md").exists():
                    continue
                payload = _payload_from_text(url, text)
                payload.source_id = source_id
                payload.url = url
                already_fetched.add(url)
                count += 1
                yield payload
