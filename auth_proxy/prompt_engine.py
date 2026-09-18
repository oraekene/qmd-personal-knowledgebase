"""System Prompt and User Customization Engine for QMD Knowledgebase.

Provides dynamic synthesis of SOUL.md (persona), SYSTEM_PROMPT.md (guidelines),
and corpus silo contexts, as well as MCP prompt templates (`prompts/list` and `prompts/get`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_file_content(path: Path) -> str:
    """Safely load text content from a file if it exists."""
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def load_soul(repo_root: Path) -> str:
    """Load SOUL.md persona and tone principles."""
    return load_file_content(repo_root / "SOUL.md")


def load_system_prompt(repo_root: Path) -> str:
    """Load SYSTEM_PROMPT.md operational guidelines."""
    return load_file_content(repo_root / "SYSTEM_PROMPT.md")


def load_agents_context(repo_root: Path) -> str:
    """Load AGENTS.md rules if present."""
    return load_file_content(repo_root / "AGENTS.md")


def get_silo_summary(repo_root: Path) -> str:
    """Generate a high-level summary of active silos and their approximate scale."""
    corpus_dir = repo_root / "corpus"
    if not corpus_dir.is_dir():
        return ""

    silos = ["notes", "wiki", "github", "chats", "pdfs", "web", "twitter"]
    counts = {}
    for s in silos:
        s_dir = corpus_dir / s
        if s_dir.is_dir():
            cnt = len(list(s_dir.rglob("*.md")))
            if cnt > 0:
                counts[s] = cnt

    if not counts:
        return ""

    lines = ["## Active Corpus Silos Status:"]
    for s, cnt in counts.items():
        lines.append(f"- **{s}**: {cnt} indexed markdown documents")
    return "\n".join(lines)


def synthesize_system_prompt(
    repo_root: Path,
    custom_instructions: Optional[str] = None,
) -> str:
    """Synthesize complete system instructions for MCP initialize and thin clients."""
    parts: List[str] = []

    soul = load_soul(repo_root)
    if soul:
        parts.append(soul)

    sys_prompt = load_system_prompt(repo_root)
    if sys_prompt:
        parts.append(sys_prompt)

    agents = load_agents_context(repo_root)
    if agents:
        parts.append(f"## Developer & Agent Rules\n{agents}")

    silo_summary = get_silo_summary(repo_root)
    if silo_summary:
        parts.append(silo_summary)

    if custom_instructions and custom_instructions.strip():
        parts.append(f"## User Custom Instructions\n{custom_instructions.strip()}")

    return "\n\n---\n\n".join(parts)


# MCP Prompt Templates Specification
PROMPT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "knowledge-search",
        "description": "Formulates an optimal multi-silo search query with structured collection filtering.",
        "arguments": [
          {
            "name": "query",
            "description": "The concept, topic, or question to search across the knowledgebase",
            "required": True,
          },
          {
            "name": "silo",
            "description": "Optional specific silo to scope search to (notes, wiki, github, chats, pdfs, web, twitter)",
            "required": False,
          },
        ],
    },
    {
        "name": "wiki-synthesis",
        "description": "Synthesizes extracted knowledge from multiple notes and chats into a consolidated concept note.",
        "arguments": [
          {
            "name": "topic",
            "description": "The topic or subject area to synthesize",
            "required": True,
          }
        ],
    },
    {
        "name": "deep-investigation",
        "description": "Runs an iterative multi-step research investigation across notes, code repositories, and chats.",
        "arguments": [
          {
            "name": "objective",
            "description": "The ultimate research or debugging objective",
            "required": True,
          }
        ],
    },
]


def list_prompts() -> List[Dict[str, Any]]:
    """Return list of supported MCP prompt templates."""
    return PROMPT_DEFINITIONS


def get_prompt_response(name: str, arguments: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    """Generate prompt messages for MCP prompts/get call."""
    base_instructions = synthesize_system_prompt(repo_root)

    if name == "knowledge-search":
        query = arguments.get("query", "")
        silo = arguments.get("silo", "")
        scope_clause = f" strictly within the '{silo}' silo" if silo and silo != "all" else " across all silos"
        user_msg = (
            f"Search my personal knowledgebase for '{query}'{scope_clause}.\n"
            f"Please search using the MCP search/query tool, retrieve the most relevant source documents using get, "
            f"and present a grounded summary citing all sources with qmd:// URIs."
        )
        return {
            "description": f"Knowledgebase search for {query}",
            "messages": [
                {"role": "user", "content": {"type": "text", "text": user_msg}}
            ],
        }

    if name == "wiki-synthesis":
        topic = arguments.get("topic", "")
        user_msg = (
            f"Please synthesize a comprehensive wiki concept document for '{topic}'.\n"
            f"1. Search notes, chats, and github repositories for references to '{topic}'.\n"
            f"2. Extract core principles, architectural decisions, and rationale.\n"
            f"3. Produce a structured markdown concept entry citing original source paths."
        )
        return {
            "description": f"Wiki concept synthesis for {topic}",
            "messages": [
                {"role": "user", "content": {"type": "text", "text": user_msg}}
            ],
        }

    if name == "deep-investigation":
        objective = arguments.get("objective", "")
        user_msg = (
            f"Conduct a deep multi-step investigation for: '{objective}'.\n"
            f"Examine relevant code repositories, architecture decisions (docs/adr/), and chat discussions.\n"
            f"Provide a root-cause breakdown, verified evidence, and recommended next actions."
        )
        return {
            "description": f"Deep investigation: {objective}",
            "messages": [
                {"role": "user", "content": {"type": "text", "text": user_msg}}
            ],
        }

    raise ValueError(f"Unknown prompt template: '{name}'")
