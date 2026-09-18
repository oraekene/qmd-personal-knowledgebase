# tests/test_progressive_tools.py
"""Tests for Hermes Progressive Tool Calling & Skill Disclosure Engine (Feature 5)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from auth_proxy.progressive_tools import (
    TOOL_REGISTRY,
    _parse_frontmatter,
    call_tool,
    describe_tool,
    get_progressive_tools_manifest,
    handle_progressive_tool_call,
    list_skills,
    search_tools,
    view_skill,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_parse_frontmatter() -> None:
    content = "---\nname: my-skill\ndescription: A test skill\n---\n# Markdown Body\nHello world"
    meta, body = _parse_frontmatter(content)
    assert meta["name"] == "my-skill"
    assert meta["description"] == "A test skill"
    assert body.startswith("# Markdown Body")

    no_fm = "# Just body"
    meta2, body2 = _parse_frontmatter(no_fm)
    assert meta2 == {}
    assert body2 == no_fm


def test_list_skills() -> None:
    skills = list_skills()
    assert len(skills) >= 4
    names = {s["name"] for s in skills}
    assert "knowledge-retrieval" in names
    assert "media-ingestion" in names
    assert "wiki-synthesis" in names
    assert "deep-investigation" in names

    for s in skills:
        assert "description" in s
        assert len(s["description"]) <= 145


def test_view_skill() -> None:
    text = view_skill("knowledge-retrieval")
    assert "# Knowledge Retrieval Protocol" in text
    assert "search" in text.lower()

    # Invalid skill name traversal
    with pytest.raises(ValueError):
        view_skill("../secrets")

    with pytest.raises(ValueError):
        view_skill("sub/dir")

    # Non-existent skill
    with pytest.raises(FileNotFoundError):
        view_skill("non-existent-skill-xyz")


def test_search_tools() -> None:
    # Empty query returns full registry
    all_tools = search_tools("")
    assert len(all_tools) == len(TOOL_REGISTRY)

    # Search for youtube / video ingestion
    yt_tools = search_tools("youtube")
    assert any(t["name"] == "ingest_url" for t in yt_tools)

    # Search for search / query
    search_res = search_tools("search")
    assert any(t["name"] in ("search", "tool_search") for t in search_res)

    # Search for wiki
    wiki_res = search_tools("wiki")
    assert any(t["name"] == "compile_wiki" for t in wiki_res)


def test_describe_tool() -> None:
    desc = describe_tool("search")
    assert desc["name"] == "search"
    assert "query" in desc["inputSchema"]["properties"]

    desc_ingest = describe_tool("ingest_url")
    assert "url" in desc_ingest["inputSchema"]["properties"]

    with pytest.raises(ValueError):
        describe_tool("invalid_tool_unknown")


def test_call_tool_skills_and_meta() -> None:
    # 1. skills_list
    res_skills = call_tool("skills_list", {}, repo_root=REPO_ROOT)
    assert isinstance(res_skills, list)
    assert any(s["name"] == "knowledge-retrieval" for s in res_skills)

    # 2. skill_view
    res_view = call_tool("skill_view", {"name": "knowledge-retrieval"}, repo_root=REPO_ROOT)
    assert isinstance(res_view, str)
    assert "# Knowledge Retrieval Protocol" in res_view

    # 3. tool_search
    res_search = call_tool("tool_search", {"query": "transcript"}, repo_root=REPO_ROOT)
    assert isinstance(res_search, list)
    assert any(t["name"] == "ingest_url" for t in res_search)

    # 4. tool_describe
    res_desc = call_tool("tool_describe", {"name": "get"}, repo_root=REPO_ROOT)
    assert res_desc["name"] == "get"

    # 5. tool_call recursion
    res_nested = call_tool(
        "tool_call",
        {"name": "tool_describe", "arguments": {"name": "skills_list"}},
        repo_root=REPO_ROOT,
    )
    assert res_nested["name"] == "skills_list"


def test_call_tool_get(tmp_path: Path) -> None:
    test_file = tmp_path / "sample.md"
    test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n", encoding="utf-8")

    # Full get
    content = call_tool("get", {"file": str(test_file)}, repo_root=REPO_ROOT)
    assert "Line 1" in content
    assert "Line 5" in content

    # Offset and count
    slice_content = call_tool("get", {"file": str(test_file), "offset": 2, "count": 2}, repo_root=REPO_ROOT)
    assert slice_content == "Line 2\nLine 3"

    # File not found
    missing = call_tool("get", {"file": "nonexistent/file.md"}, repo_root=REPO_ROOT)
    assert "File not found" in missing


def test_get_progressive_tools_manifest() -> None:
    manifest = get_progressive_tools_manifest()
    assert len(manifest) == 7
    names = {t["name"] for t in manifest}
    assert "skills_list" in names
    assert "skill_view" in names
    assert "tool_search" in names
    assert "tool_describe" in names
    assert "tool_call" in names
    assert "search" in names
    assert "get" in names

    for tool in manifest:
        assert "inputSchema" in tool
        assert "description" in tool


def test_handle_progressive_tool_call() -> None:
    # Successful call
    mcp_res = handle_progressive_tool_call("skills_list", {}, repo_root=REPO_ROOT)
    assert mcp_res["isError"] is False
    assert len(mcp_res["content"]) == 1
    assert mcp_res["content"][0]["type"] == "text"
    parsed = json.loads(mcp_res["content"][0]["text"])
    assert isinstance(parsed, list)

    # Errored call
    err_res = handle_progressive_tool_call("nonexistent_tool", {}, repo_root=REPO_ROOT)
    assert err_res["isError"] is True
    assert "Error executing tool" in err_res["content"][0]["text"]
