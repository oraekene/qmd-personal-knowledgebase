"""Agent-Reach Unified Connector — bridging YouTube, Twitter/X, Reddit, Web, and GitHub into QMD corpus.

Per Feature 4 specs + spec.md:87-101 + CONTEXT.md:14-30:
- YouTube video URL -> metadata + transcript/subtitles -> Units in corpus/web/
- Twitter / X thread URL -> tweet content + author -> Units in corpus/twitter/
- Reddit post URL -> discussion + thread comments -> Units in corpus/web/
- Web URL -> clean Markdown via Jina Reader / authenticated browser sessions -> Units in corpus/web/
- GitHub URL -> repo overview and README -> Units in corpus/github/

Enforces locked QMD schema (9-field Frontmatter, Summary blockquote, # Title heading, safe filenames).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_REACH_DIR = REPO_ROOT / "Agent-Reach-main"
if str(AGENT_REACH_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_REACH_DIR))

from connectors.sdk.base import SourcePlugin, UnitPayload
from connectors.sdk.writer import write_unit, safe_filename


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract 11-char YouTube video ID from various URL formats."""
    patterns = [
        r"(?:youtube\.com/(?:watch\?v=|embed/|v/|shorts/)|youtu\.be/)([\w\-]{11})",
        r"youtube\.com/watch\?.*[&?]v=([\w\-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def extract_twitter_info(url: str) -> Optional[Tuple[str, str]]:
    """Extract (username, tweet_id) from Twitter/X URL."""
    m = re.search(r"(?:twitter\.com|x\.com)/(?:#!/)?([^/?#]+)/status(?:es)?/(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    return None


def extract_reddit_info(url: str) -> Optional[Tuple[str, str]]:
    """Extract (subreddit, post_id) from Reddit URL."""
    m = re.search(r"reddit\.com/r/([^/?#]+)/comments/([^/?#]+)", url)
    if m:
        return m.group(1), m.group(2)
    m2 = re.search(r"redd\.it/([^/?#]+)", url)
    if m2:
        return "reddit", m2.group(1)
    return None


def extract_github_repo(url: str) -> Optional[str]:
    """Extract owner/repo from GitHub URL."""
    m = re.search(r"github\.com/([^/?#]+)/([^/?#]+)", url)
    if m:
        repo = m.group(2)
        if repo.endswith(".git"):
            repo = repo[:-4]
        return f"{m.group(1)}/{repo}"
    return None


def detect_channel(url: str) -> str:
    """Auto-detect target channel type from URL."""
    clean_url = url.strip()
    if extract_youtube_id(clean_url):
        return "youtube"
    if extract_twitter_info(clean_url):
        return "twitter"
    if extract_reddit_info(clean_url):
        return "reddit"
    if extract_github_repo(clean_url):
        return "github"
    return "web"


def _make_clean_summary(text: str, fallback: str = "Ingested knowledge unit.") -> str:
    """Build a compliant single-sentence summary without newlines (max 120 chars)."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return fallback
    for sep in [". ", "! ", "? "]:
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0] + sep.strip()
            break
    if len(cleaned) > 120:
        cleaned = cleaned[:117].rstrip() + "..."
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned or fallback


# ----------------------------------------------------------------------
# Channel Extractors
# ----------------------------------------------------------------------

def extract_youtube(
    url: str,
    transcribe_audio: bool = False,
    fetch_func: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> UnitPayload:
    """Extract YouTube video metadata and subtitles/transcript into UnitPayload."""
    video_id = extract_youtube_id(url)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL: {url}")

    if fetch_func:
        data = fetch_func(url)
        title = data.get("title", f"YouTube Video {video_id}")
        author = data.get("author", "YouTube Creator")
        summary = _make_clean_summary(data.get("summary", f"YouTube video {title} by {author}."))
        transcript = data.get("transcript", "No transcript provided.")
        duration = data.get("duration", "Unknown")
        tags = data.get("tags", ["youtube", "video", "reach"])
    else:
        title = f"YouTube Video {video_id}"
        author = "YouTube"
        transcript = ""
        duration = "Unknown"
        tags = ["youtube", "video", "reach"]

        # 1. Try yt-dlp if installed
        if shutil.which("yt-dlp"):
            try:
                cmd = ["yt-dlp", "-j", "--skip-download", f"https://www.youtube.com/watch?v={video_id}"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if proc.returncode == 0 and proc.stdout:
                    info = json.loads(proc.stdout)
                    title = info.get("title") or title
                    author = info.get("uploader") or info.get("channel") or author
                    duration = str(info.get("duration_string") or info.get("duration") or duration)
                    if info.get("tags"):
                        tags.extend([t.lower() for t in info["tags"][:5]])
                    desc = info.get("description", "")
                    if desc:
                        transcript = f"### Video Description\n\n{desc[:1500]}\n"
            except Exception:
                pass

        # 2. Audio transcription requested via Agent-Reach transcribe module
        if transcribe_audio:
            try:
                from agent_reach.transcribe import transcribe as _ar_transcribe
                audio_transcript = _ar_transcribe(f"https://www.youtube.com/watch?v={video_id}")
                if audio_transcript:
                    transcript += f"\n### Audio Transcript (Whisper)\n\n{audio_transcript}\n"
            except Exception as e:
                transcript += f"\n*(Audio transcription attempted: {e})*\n"

        # 3. Fallback to YouTube oEmbed API for zero-config metadata
        if title == f"YouTube Video {video_id}":
            try:
                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    oembed = json.loads(resp.read().decode("utf-8"))
                    title = oembed.get("title") or title
                    author = oembed.get("author_name") or author
            except Exception:
                pass

        summary = _make_clean_summary(f"YouTube video '{title}' by {author}.")

    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    body = (
        f"# {title}\n\n"
        f"- **Channel / Creator:** {author}\n"
        f"- **Video URL:** {clean_url}\n"
        f"- **Duration:** {duration}\n\n"
        f"## Content & Transcript\n\n"
        f"{transcript if transcript.strip() else 'No transcript or captions available for this video.'}\n"
    )

    return UnitPayload(
        source="youtube",
        silo="web",
        source_id=f"youtube_{video_id}",
        url=clean_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=tags,
        author=author,
        title=title,
        summary=summary,
        body_markdown=body,
    )


def extract_twitter(
    url: str,
    fetch_func: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> UnitPayload:
    """Extract Twitter / X tweet or thread content into UnitPayload."""
    info = extract_twitter_info(url)
    if not info:
        raise ValueError(f"Invalid Twitter/X URL: {url}")
    username, tweet_id = info

    if fetch_func:
        data = fetch_func(url)
        title = data.get("title", f"Post by @{username}")
        author = data.get("author", f"@{username}")
        text = data.get("text", "")
        summary = _make_clean_summary(data.get("summary", text or f"Tweet by @{username}."))
        tags = data.get("tags", ["twitter", "x", "social"])
    else:
        text = ""
        author = f"@{username}"
        tags = ["twitter", "x", "social"]

        # 1. Try syndication twimg API
        try:
            syn_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=x"
            req = urllib.request.Request(syn_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                tdata = json.loads(resp.read().decode("utf-8"))
                text = tdata.get("text", "")
                user_info = tdata.get("user", {})
                if user_info.get("screen_name"):
                    author = f"@{user_info['screen_name']}"
                elif user_info.get("name"):
                    author = user_info["name"]
        except Exception:
            pass

        # 2. Fallback to Jina Reader
        if not text:
            try:
                jina_url = f"https://r.jina.ai/{url}"
                req = urllib.request.Request(jina_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
            except Exception:
                text = f"Tweet from {url}"

        title = f"Post by {author}: {text[:45].strip() if text else tweet_id}"
        summary = _make_clean_summary(text or f"Post by {author} on X.")

    clean_url = f"https://x.com/{username}/status/{tweet_id}"
    body = (
        f"# {title}\n\n"
        f"- **Author:** {author}\n"
        f"- **Tweet ID:** {tweet_id}\n"
        f"- **URL:** {clean_url}\n\n"
        f"## Tweet Content\n\n"
        f"{text}\n"
    )

    return UnitPayload(
        source="twitter",
        silo="twitter",
        source_id=f"tweet_{tweet_id}",
        url=clean_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=tags,
        author=author,
        title=title,
        summary=summary,
        body_markdown=body,
    )


def extract_reddit(
    url: str,
    fetch_func: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> UnitPayload:
    """Extract Reddit discussion post and top comments into UnitPayload."""
    info = extract_reddit_info(url)
    subreddit = info[0] if info else "reddit"
    post_id = info[1] if info else hashlib.blake2b(url.encode(), digest_size=6).hexdigest()

    if fetch_func:
        data = fetch_func(url)
        title = data.get("title", f"Reddit discussion in r/{subreddit}")
        author = data.get("author", "u/redditor")
        summary = _make_clean_summary(data.get("summary", f"Reddit thread in r/{subreddit}: {title}"))
        selftext = data.get("text", "")
        comments = data.get("comments", [])
        tags = data.get("tags", ["reddit", "web", "discussion", f"r/{subreddit}"])
    else:
        title = f"Reddit discussion in r/{subreddit}"
        author = "u/reddit"
        selftext = ""
        comments = []
        tags = ["reddit", "web", "discussion", f"r/{subreddit}"]

        # Try Jina Reader
        try:
            jina_url = f"https://r.jina.ai/{url}"
            req = urllib.request.Request(jina_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                jina_text = resp.read().decode("utf-8", errors="replace")
                if "Title:" in jina_text:
                    lines = jina_text.splitlines()
                    for line in lines:
                        if line.startswith("Title:"):
                            title = line.replace("Title:", "").strip()
                            break
                selftext = jina_text
        except Exception:
            selftext = f"Reddit post {url}"

        summary = _make_clean_summary(f"Reddit thread in r/{subreddit}: {title}")

    comments_block = ""
    if comments:
        comments_block = "\n### Discussion Highlights\n\n" + "\n\n".join(
            f"> **{c.get('author', 'u/user')}**: {c.get('body', '')}" for c in comments
        )

    body = (
        f"# {title}\n\n"
        f"- **Subreddit:** r/{subreddit}\n"
        f"- **Author:** {author}\n"
        f"- **Post URL:** {url}\n\n"
        f"## Post\n\n"
        f"{selftext}\n"
        f"{comments_block}\n"
    )

    return UnitPayload(
        source="reddit",
        silo="web",
        source_id=f"reddit_{post_id}",
        url=url,
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=tags,
        author=author,
        title=title,
        summary=summary,
        body_markdown=body,
    )


def extract_web(
    url: str,
    fetch_func: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> UnitPayload:
    """Extract standard web page via Jina Reader or HTTP into UnitPayload."""
    url = url.strip()
    source_id = hashlib.blake2b(url.encode("utf-8"), digest_size=8).hexdigest()

    if fetch_func:
        data = fetch_func(url)
        title = data.get("title", f"Web Page {source_id}")
        author = data.get("author", "Web")
        text = data.get("text", "")
        summary = _make_clean_summary(data.get("summary", f"Web page {title}."))
        tags = data.get("tags", ["web", "reach"])
    else:
        title = f"Web Page {source_id}"
        author = "Web"
        tags = ["web", "reach"]
        text = ""

        # Use Agent-Reach WebChannel if available
        try:
            from agent_reach.channels.web import WebChannel
            wc = WebChannel()
            text = wc.read(url)
        except Exception:
            # Direct Jina Reader / HTTP fallback
            try:
                jina_url = f"https://r.jina.ai/{url}"
                req = urllib.request.Request(jina_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
            except Exception as e:
                text = f"Failed to fetch content from {url}: {e}"

        # Extract title from text if present
        m = re.search(r"^Title:\s*(.+)", text, flags=re.MULTILINE)
        if m:
            title = m.group(1).strip()
        else:
            m2 = re.search(r"^#\s+(.+)", text, flags=re.MULTILINE)
            if m2:
                title = m2.group(1).strip()

        summary = _make_clean_summary(text or f"Web document from {url}.")

    body = (
        f"# {title}\n\n"
        f"- **Source URL:** {url}\n\n"
        f"## Content\n\n"
        f"{text}\n"
    )

    return UnitPayload(
        source="web",
        silo="web",
        source_id=f"web_{source_id}",
        url=url,
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=tags,
        author=author,
        title=title,
        summary=summary,
        body_markdown=body,
    )


def extract_github(
    url: str,
    fetch_func: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> UnitPayload:
    """Extract GitHub repository overview and README into UnitPayload."""
    repo = extract_github_repo(url)
    if not repo:
        raise ValueError(f"Invalid GitHub repo URL: {url}")
    safe_repo_id = repo.replace("/", "__")

    if fetch_func:
        data = fetch_func(url)
        title = data.get("title", repo)
        author = data.get("author", repo.split("/")[0])
        summary = _make_clean_summary(data.get("summary", f"GitHub repository {repo}."))
        body_text = data.get("text", "")
        tags = data.get("tags", ["github", "code", "reach"])
    else:
        author = repo.split("/")[0]
        title = repo
        body_text = ""
        tags = ["github", "code", "reach"]

        # Try gh CLI if available
        if shutil.which("gh"):
            try:
                proc = subprocess.run(["gh", "repo", "view", repo], capture_output=True, text=True, timeout=15)
                if proc.returncode == 0:
                    body_text = proc.stdout
            except Exception:
                pass

        # Fallback to Jina Reader or raw GitHub user content
        if not body_text:
            try:
                raw_url = f"https://raw.githubusercontent.com/{repo}/main/README.md"
                req = urllib.request.Request(raw_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body_text = resp.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = f"GitHub repository {repo} (clone or view at https://github.com/{repo})"

        summary = _make_clean_summary(f"GitHub repository {repo} by {author}.")

    body = (
        f"# {title}\n\n"
        f"- **Repository:** https://github.com/{repo}\n"
        f"- **Owner:** {author}\n\n"
        f"## Repository Readme & Info\n\n"
        f"{body_text}\n"
    )

    return UnitPayload(
        source="github",
        silo="github",
        source_id=f"repo_{safe_repo_id}",
        url=f"https://github.com/{repo}",
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=tags,
        author=author,
        title=title,
        summary=summary,
        body_markdown=body,
    )


# ----------------------------------------------------------------------
# Ingestion Entry Point
# ----------------------------------------------------------------------

def ingest_url(
    url: str,
    corpus_root: Path | str,
    channel_type: Optional[str] = None,
    transcribe_audio: bool = False,
    fetch_func: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Tuple[Path, UnitPayload]:
    """Route any supported URL to its channel extractor and write Unit to corpus.

    Returns (created_file_path, unit_payload).
    """
    clean_url = url.strip()
    if not clean_url:
        raise ValueError("URL cannot be empty")

    ch = channel_type.lower().strip() if channel_type and channel_type.lower().strip() != "auto" else detect_channel(clean_url)

    if ch == "youtube":
        payload = extract_youtube(clean_url, transcribe_audio=transcribe_audio, fetch_func=fetch_func)
    elif ch in ("twitter", "x"):
        payload = extract_twitter(clean_url, fetch_func=fetch_func)
    elif ch == "reddit":
        payload = extract_reddit(clean_url, fetch_func=fetch_func)
    elif ch == "github":
        payload = extract_github(clean_url, fetch_func=fetch_func)
    else:
        payload = extract_web(clean_url, fetch_func=fetch_func)

    target_path = write_unit(payload, Path(corpus_root))
    return target_path, payload


class AgentReachConnector(SourcePlugin):
    """SourcePlugin compliant connector for Agent-Reach channels."""

    NAME = "reach"
    DESCRIPTION = "Multi-channel internet ingestion (YouTube, Twitter/X, Reddit, Web, GitHub)"
    REQUIRES_AUTH = False
    SUPPORTS_LOOKBACK = False

    def __init__(self, corpus_root: Path | str | None = None, urls: Optional[List[str]] = None):
        super().__init__()
        self.corpus_root = Path(corpus_root) if corpus_root else REPO_ROOT / "corpus"
        self.urls = urls or []

    def fetch_recent(self, since: datetime, limit: int = 50) -> Iterator[UnitPayload]:
        count = 0
        for u in self.urls:
            if count >= limit:
                break
            try:
                _, payload = ingest_url(u, self.corpus_root)
                count += 1
                yield payload
            except Exception:
                continue

    def health_check(self) -> Tuple[bool, str]:
        available = []
        if shutil.which("yt-dlp"):
            available.append("yt-dlp")
        if shutil.which("ffmpeg"):
            available.append("ffmpeg")
        if shutil.which("gh"):
            available.append("gh")
        return True, f"Agent-Reach active (available CLI backends: {', '.join(available) or 'web fallback'})"
