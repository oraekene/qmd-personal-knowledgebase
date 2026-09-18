"""Unit tests for the System Prompt & User Customization Engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auth_proxy.prompt_engine import (
    get_prompt_response,
    get_silo_summary,
    list_prompts,
    load_agents_context,
    load_soul,
    load_system_prompt,
    synthesize_system_prompt,
)


def test_prompt_loaders(tmp_path: Path):
    soul_file = tmp_path / "SOUL.md"
    soul_file.write_text("Persona tone: direct, no fluff.", encoding="utf-8")

    sys_file = tmp_path / "SYSTEM_PROMPT.md"
    sys_file.write_text("Operational rules: search before answering.", encoding="utf-8")

    assert load_soul(tmp_path) == "Persona tone: direct, no fluff."
    assert load_system_prompt(tmp_path) == "Operational rules: search before answering."
    assert load_agents_context(tmp_path) == ""


def test_silo_summary(tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "notes").mkdir(parents=True)
    (corpus / "wiki").mkdir(parents=True)
    (corpus / "notes" / "n1.md").write_text("note 1", encoding="utf-8")
    (corpus / "wiki" / "w1.md").write_text("wiki 1", encoding="utf-8")

    summary = get_silo_summary(tmp_path)
    assert "Active Corpus Silos Status" in summary
    assert "**notes**: 1" in summary
    assert "**wiki**: 1" in summary


def test_synthesize_system_prompt(tmp_path: Path):
    (tmp_path / "SOUL.md").write_text("Soul content", encoding="utf-8")
    (tmp_path / "SYSTEM_PROMPT.md").write_text("System rules", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Agent rules", encoding="utf-8")

    res = synthesize_system_prompt(tmp_path, custom_instructions="Custom user instruction")
    assert "Soul content" in res
    assert "System rules" in res
    assert "Developer & Agent Rules" in res
    assert "Custom user instruction" in res


def test_list_prompts():
    prompts = list_prompts()
    assert len(prompts) >= 3
    names = [p["name"] for p in prompts]
    assert "knowledge-search" in names
    assert "wiki-synthesis" in names
    assert "deep-investigation" in names


def test_get_prompt_response(tmp_path: Path):
    (tmp_path / "SOUL.md").write_text("Direct tone", encoding="utf-8")
    (tmp_path / "SYSTEM_PROMPT.md").write_text("Search rules", encoding="utf-8")

    # 1. knowledge-search
    res = get_prompt_response("knowledge-search", {"query": "OCR rationale", "silo": "wiki"}, tmp_path)
    assert "OCR rationale" in res["messages"][0]["content"]["text"]
    assert "'wiki' silo" in res["messages"][0]["content"]["text"]

    # 2. wiki-synthesis
    res_wiki = get_prompt_response("wiki-synthesis", {"topic": "solar sizing"}, tmp_path)
    assert "solar sizing" in res_wiki["messages"][0]["content"]["text"]

    # 3. deep-investigation
    res_inv = get_prompt_response("deep-investigation", {"objective": "latency debugging"}, tmp_path)
    assert "latency debugging" in res_inv["messages"][0]["content"]["text"]

    # 4. unknown prompt
    with pytest.raises(ValueError, match="Unknown prompt template"):
        get_prompt_response("nonexistent-template", {}, tmp_path)
