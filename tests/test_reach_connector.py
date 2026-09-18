"""Tests for Agent-Reach Unified Connector (Feature 4).

Verifies multi-channel URL extraction, UnitPayload construction,
schema compliance (frontmatter, summary blockquote, # Title),
and file writing across YouTube, Twitter, Reddit, Web, and GitHub silos.
"""

from __future__ import annotations

import tempfile
import shutil
from pathlib import Path
import pytest

from connectors.reach import (
    detect_channel,
    extract_youtube_id,
    extract_twitter_info,
    extract_reddit_info,
    extract_github_repo,
    extract_youtube,
    extract_twitter,
    extract_reddit,
    extract_web,
    extract_github,
    ingest_url,
    AgentReachConnector,
)


def test_url_detection():
    # YouTube
    yt1 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    yt2 = "https://youtu.be/dQw4w9WgXcQ"
    yt3 = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
    assert extract_youtube_id(yt1) == "dQw4w9WgXcQ"
    assert extract_youtube_id(yt2) == "dQw4w9WgXcQ"
    assert extract_youtube_id(yt3) == "dQw4w9WgXcQ"
    assert detect_channel(yt1) == "youtube"

    # Twitter / X
    tw1 = "https://x.com/jack/status/20"
    tw2 = "https://twitter.com/elonmusk/status/1836000000000000000"
    assert extract_twitter_info(tw1) == ("jack", "20")
    assert extract_twitter_info(tw2) == ("elonmusk", "1836000000000000000")
    assert detect_channel(tw1) == "twitter"
    assert detect_channel(tw2) == "twitter"

    # Reddit
    rd1 = "https://www.reddit.com/r/programming/comments/16g8v29/rust_vs_go_benchmarks/"
    rd2 = "https://redd.it/16g8v29"
    assert extract_reddit_info(rd1) == ("programming", "16g8v29")
    assert extract_reddit_info(rd2) == ("reddit", "16g8v29")
    assert detect_channel(rd1) == "reddit"
    assert detect_channel(rd2) == "reddit"

    # GitHub
    gh1 = "https://github.com/torvalds/linux"
    gh2 = "https://github.com/astral-sh/uv.git"
    assert extract_github_repo(gh1) == "torvalds/linux"
    assert extract_github_repo(gh2) == "astral-sh/uv"
    assert detect_channel(gh1) == "github"

    # Web fallback
    web1 = "https://news.ycombinator.com/item?id=123456"
    assert detect_channel(web1) == "web"


def test_extract_youtube_mock():
    mock_data = {
        "title": "Quantum Computing in 10 Minutes",
        "author": "TechExplained",
        "summary": "An accessible overview of qubits, superposition, and quantum algorithms.",
        "transcript": "Quantum computers utilize quantum mechanical phenomena such as superposition.",
        "duration": "10:15",
        "tags": ["quantum", "physics", "computing"],
    }
    payload = extract_youtube("https://youtu.be/12345678901", fetch_func=lambda u: mock_data)
    assert payload.source == "youtube"
    assert payload.silo == "web"
    assert payload.source_id == "youtube_12345678901"
    assert payload.author == "TechExplained"
    assert payload.title == "Quantum Computing in 10 Minutes"
    assert "qubits" in payload.summary
    assert "\n" not in payload.summary
    assert "# Quantum Computing in 10 Minutes" in payload.body_markdown
    assert "TechExplained" in payload.body_markdown


def test_extract_twitter_mock():
    mock_data = {
        "title": "Post by @sama",
        "author": "@sama",
        "text": "Excited to share our latest research on agentic alignment and reasoning models.",
        "summary": "Latest research breakthrough on agentic reasoning models.",
        "tags": ["ai", "openai"],
    }
    payload = extract_twitter("https://x.com/sama/status/9876543210", fetch_func=lambda u: mock_data)
    assert payload.source == "twitter"
    assert payload.silo == "twitter"
    assert payload.source_id == "tweet_9876543210"
    assert payload.author == "@sama"
    assert "\n" not in payload.summary
    assert "agentic alignment" in payload.body_markdown


def test_extract_reddit_mock():
    mock_data = {
        "title": "Why SQLite is the unsung hero of local knowledge systems",
        "author": "u/data_engineer",
        "summary": "Discussion examining SQLite FTS5 vector hybrid search architectures.",
        "text": "SQLite FTS5 provides instant BM25 scoring with zero server daemon overhead.",
        "comments": [
            {"author": "u/search_dev", "body": "BM25 combined with vector embeddings works wonders."},
            {"author": "u/sysadmin", "body": "Single-file backups make disaster recovery effortless."}
        ],
    }
    payload = extract_reddit(
        "https://www.reddit.com/r/programming/comments/abcdef/why_sqlite_is_awesome/",
        fetch_func=lambda u: mock_data,
    )
    assert payload.source == "reddit"
    assert payload.silo == "web"
    assert payload.source_id == "reddit_abcdef"
    assert "SQLite" in payload.title
    assert "u/search_dev" in payload.body_markdown
    assert "\n" not in payload.summary


def test_extract_web_and_github_mock():
    # Web
    web_payload = extract_web(
        "https://example.com/article",
        fetch_func=lambda u: {
            "title": "Modern Architecture Patterns",
            "author": "Architect",
            "summary": "Deep dive into event-driven and local-first software patterns.",
            "text": "Local-first software ensures user ownership and high reliability.",
        }
    )
    assert web_payload.source == "web"
    assert web_payload.silo == "web"
    assert web_payload.title == "Modern Architecture Patterns"
    assert "\n" not in web_payload.summary

    # GitHub
    gh_payload = extract_github(
        "https://github.com/facebook/react",
        fetch_func=lambda u: {
            "title": "facebook/react",
            "author": "facebook",
            "summary": "The library for web and native user interfaces.",
            "text": "React lets you build user interfaces out of individual pieces called components.",
        }
    )
    assert gh_payload.source == "github"
    assert gh_payload.silo == "github"
    assert gh_payload.source_id == "repo_facebook__react"
    assert "facebook/react" in gh_payload.title


def test_ingest_url_end_to_end():
    tmp_corpus = Path(tempfile.mkdtemp())
    try:
        # Ingest YouTube
        path_yt, unit_yt = ingest_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            corpus_root=tmp_corpus,
            fetch_func=lambda u: {
                "title": "Rick Astley Song",
                "author": "Rick Astley",
                "summary": "Classic pop song from 1987.",
                "transcript": "Never gonna give you up, never gonna let you down.",
            }
        )
        assert path_yt.exists()
        assert path_yt.parent.name == "web"
        content_yt = path_yt.read_text(encoding="utf-8")
        assert "source: youtube" in content_yt
        assert "silo: web" in content_yt
        assert "> Classic pop song from 1987." in content_yt
        assert "# Rick Astley Song" in content_yt

        # Ingest Twitter
        path_tw, unit_tw = ingest_url(
            "https://x.com/jack/status/20",
            corpus_root=tmp_corpus,
            fetch_func=lambda u: {
                "title": "Jack's First Tweet",
                "author": "@jack",
                "text": "just setting up my twttr",
                "summary": "The very first tweet on Twitter.",
            }
        )
        assert path_tw.exists()
        assert path_tw.parent.name == "twitter"
        content_tw = path_tw.read_text(encoding="utf-8")
        assert "source: twitter" in content_tw
        assert "silo: twitter" in content_tw
        assert "> The very first tweet on Twitter." in content_tw

        # Ingest GitHub
        path_gh, unit_gh = ingest_url(
            "https://github.com/torvalds/linux",
            corpus_root=tmp_corpus,
            fetch_func=lambda u: {
                "title": "torvalds/linux",
                "author": "torvalds",
                "summary": "Linux kernel source tree.",
                "text": "Linux is a clone of the operating system Unix.",
            }
        )
        assert path_gh.exists()
        assert path_gh.parent.name == "github"
        content_gh = path_gh.read_text(encoding="utf-8")
        assert "source: github" in content_gh
        assert "silo: github" in content_gh

    finally:
        shutil.rmtree(tmp_corpus, ignore_errors=True)


def test_agent_reach_connector_plugin():
    tmp_corpus = Path(tempfile.mkdtemp())
    try:
        connector = AgentReachConnector(corpus_root=tmp_corpus)
        ok, msg = connector.health_check()
        assert ok is True
        assert "Agent-Reach" in msg
    finally:
        shutil.rmtree(tmp_corpus, ignore_errors=True)
