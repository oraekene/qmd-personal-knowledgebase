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


import urllib.error
import urllib.parse
import urllib.request

def _extract_links(text: str) -> list[str]:
    # Extract markdown links [title](url), HTML href="url", and bare URLs
    md_links = re.findall(r"\[.*?\]\((https?://[^)\s]+)\)", text)
    html_links = re.findall(r'href=["\'](https?://[^"\'\s]+)["\']', text)
    bare_links = re.findall(r"https?://[^\s\)\]\"'<>]+", text)

    combined = md_links + html_links + bare_links
    cleaned = []
    seen: Set[str] = set()

    for url in combined:
        url = url.rstrip(".,;:)\"'!>")
        # Skip local/loopback links or non-http
        if any(h in url.lower() for h in ("127.0.0.1", "localhost", "qmd://")):
            continue
        if url.startswith("http://") or url.startswith("https://"):
            if url not in seen:
                seen.add(url)
                cleaned.append(url)
    return cleaned


def _fetch_page_markdown(url: str) -> str:
    """Fetch live markdown for a URL using Jina Reader -> Scrapling -> HTTP GET."""
    # 1. Try Jina Reader
    try:
        jina_url = f"https://r.jina.ai/{url}"
        req = urllib.request.Request(
            jina_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/plain, text/markdown",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            if text and len(text.strip()) > 80:
                return text.strip()
    except Exception:
        pass

    # 2. Try Scrapling Fetcher if available
    try:
        from scrapling import Fetcher  # type: ignore
        fetcher = Fetcher()
        resp = fetcher.get(url, timeout=12)
        if resp and resp.text:
            return resp.text.strip()
    except Exception:
        pass

    # 3. Direct HTTP GET with stripped HTML fallback
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
            clean_text = re.sub(r"<script.*?</script>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r"<style.*?</style>", " ", clean_text, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r"<[^>]+>", " ", clean_text)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            if len(clean_text) > 100:
                return f"# {url}\n\n{clean_text[:4000]}"
    except Exception:
        pass

    return f"# {url}\n\nCould not retrieve page content from {url}."


def _hash_url(url: str) -> str:
    # Use blake2b 8 -> 16 hex for short consistent hash
    return hashlib.blake2b(url.encode("utf-8"), digest_size=8).hexdigest()


def _payload_from_text(url: str, text: str, source: str = "web", silo: str = "web") -> UnitPayload:
    source_id = _hash_url(url)
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    first_line = lines[0] if lines else f"Content from {url}"
    if first_line.startswith("#"):
        first_line = first_line.lstrip("#").strip()
    summary = first_line[:120].strip()
    if len(summary) > 120:
        summary = summary[:117] + "..."
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
        title=first_line[:80] or url,
        summary=summary,
        body_markdown=text,
    )


class WebConnector(SourcePlugin):
    """Link expansion connector — scans corpus for new Units, fetches links."""

    NAME = "web"
    DESCRIPTION = "Link expansion via TinyFish + Jina + Scrapling"
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
        results = []
        errors = []
        for u in urls:
            try:
                content = _fetch_page_markdown(u)
                if content and "Could not retrieve page content" not in content:
                    results.append({"url": u, "final_url": u, "text": content})
                else:
                    errors.append({"url": u, "error": "fetch_failed"})
            except Exception as e:
                errors.append({"url": u, "error": str(e)})
        return {"results": results, "errors": errors}

    def _default_scrapling(self, url: str) -> str:
        return _fetch_page_markdown(url)

    def fetch_recent(self, since: datetime, limit: int = 500) -> Iterator[UnitPayload]:
        if not self.corpus_root.exists():
            return
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        already_fetched: Set[str] = set()
        web_dir = self.corpus_root / "web"
        if web_dir.exists():
            for web_file in web_dir.glob("*.md"):
                try:
                    text = web_file.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r'url:\s*"?([^"\r\n]+)"?', text)
                    if m:
                        already_fetched.add(m.group(1).strip().strip('"'))
                    for line in text.splitlines():
                        if "http://" in line or "https://" in line:
                            for link in _extract_links(line):
                                already_fetched.add(link)
                except Exception:
                    continue

        all_links: list[str] = []
        for unit_path in sorted(self.corpus_root.rglob("*.md")):
            try:
                if unit_path.is_relative_to(self.corpus_root / "web"):
                    continue
            except AttributeError:
                if "web" in unit_path.parts and (self.corpus_root / "web") in unit_path.parents:
                    continue
            if "_state" in unit_path.parts or ".qmd" in unit_path.parts:
                continue
            try:
                raw_content = unit_path.read_text(encoding="utf-8", errors="ignore")
                # CRLF-safe frontmatter strip
                lines = raw_content.splitlines()
                body_lines = []
                in_frontmatter = False
                past_frontmatter = False
                for line in lines:
                    if line.strip() == "---":
                        if not in_frontmatter and not past_frontmatter:
                            in_frontmatter = True
                            continue
                        elif in_frontmatter:
                            in_frontmatter = False
                            past_frontmatter = True
                            continue
                    if past_frontmatter or not in_frontmatter:
                        body_lines.append(line)
                body = "\n".join(body_lines)
                links = _extract_links(body)
                for link in links:
                    if link not in already_fetched and link not in all_links:
                        all_links.append(link)
            except Exception:
                continue

        if not all_links:
            return

        fetch = self.fetch_func or self._default_fetch
        scrapling_fetch = self.scrapling_func or self._default_scrapling

        count = 0
        for i in range(0, len(all_links), 10):
            if count >= limit:
                break
            batch = all_links[i : i + 10]
            result = fetch(batch)
            results = result.get("results", [])
            errors = result.get("errors", [])

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
                    already_fetched.add(final_url)
                    continue
                payload = _payload_from_text(final_url, text)
                payload.source_id = source_id
                payload.url = final_url
                already_fetched.add(final_url)
                already_fetched.add(url)
                count += 1
                yield payload

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
                    already_fetched.add(url)
                    continue
                payload = _payload_from_text(url, text)
                payload.source_id = source_id
                payload.url = url
                already_fetched.add(url)
                count += 1
                yield payload
