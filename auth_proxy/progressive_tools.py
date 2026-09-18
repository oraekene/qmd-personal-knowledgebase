"""Progressive Tool Calling & Skill Disclosure Engine (Hermes Pattern).

Per Feature 5 specs:
Eliminates token bloat and tool confusion in thin clients (Claude.ai, Telegram, mobile)
by implementing a 3-tier progressive disclosure model:
- Tier 1 (Catalog): `skills_list` returns only names and short descriptions (<200 tokens total).
- Tier 2 (Activation): `skill_view(skill_name)` returns full `SKILL.md` instructions when needed.
- Tier 3 (Bridge Execution):
  - `tool_search(query)`: Finds relevant tools by keyword.
  - `tool_describe(tool_name)`: Returns exact input schema on demand.
  - `tool_call(tool_name, arguments)`: Dynamically executes the target tool on the server.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("progressive_tools")

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"


# ----------------------------------------------------------------------
# Tier 1 & Tier 2: Skills Disclosure
# ----------------------------------------------------------------------

def _parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter key-values and remaining markdown body."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    fm_raw = parts[1]
    body = parts[2].lstrip()
    data: Dict[str, Any] = {}
    for line in fm_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            data[k] = v
    return data, body


def list_skills(skills_dir: Path | None = None) -> List[Dict[str, str]]:
    """Tier 1: List available skills with compact descriptions (<200 tokens total)."""
    target_dir = Path(skills_dir) if skills_dir else SKILLS_DIR
    if not target_dir.exists():
        return []

    skills = []
    for entry in sorted(target_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            skill_file = entry / "SKILL.md"
            if skill_file.exists():
                try:
                    text = skill_file.read_text(encoding="utf-8")
                    meta, _ = _parse_frontmatter(text)
                    name = meta.get("name", entry.name)
                    desc = meta.get("description", f"Skill for {entry.name}")
                    # Truncate description to ensure concise budget
                    if len(desc) > 140:
                        desc = desc[:137] + "..."
                    skills.append({"name": name, "description": desc})
                except Exception:
                    continue
    return skills


def view_skill(name: str, skills_dir: Path | None = None) -> str:
    """Tier 2: View full SKILL.md instructions for a specific skill."""
    safe_name = name.strip()
    if not safe_name or re.search(r"[\\/.]", safe_name):
        raise ValueError(f"Invalid skill name: {name}")

    target_dir = Path(skills_dir) if skills_dir else SKILLS_DIR
    skill_file = target_dir / safe_name / "SKILL.md"
    if not skill_file.exists():
        raise FileNotFoundError(f"Skill '{safe_name}' not found in {target_dir}")

    return skill_file.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Tier 3: Tool Catalog & Dynamic Bridge
# ----------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "search": {
        "name": "search",
        "description": "Fast sub-second BM25 full-text search across indexed personal knowledgebase documents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords to search for"},
                "silo": {
                    "type": "string",
                    "description": "Optional silo filter (notes, wiki, github, chats, pdfs, web, twitter)",
                },
            },
            "required": ["query"],
        },
        "tags": ["search", "bm25", "retrieval", "query", "fast", "silo"],
    },
    "get": {
        "name": "get",
        "description": "Retrieve full text content of a specific document from the corpus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Relative file path (e.g. corpus/notes/idea.md)"},
                "count": {"type": "integer", "description": "Max lines to retrieve (default full file)"},
                "offset": {"type": "integer", "description": "Starting line number (1-based)"},
            },
            "required": ["file"],
        },
        "tags": ["get", "read", "file", "document", "content"],
    },
    "multi_get": {
        "name": "multi_get",
        "description": "Retrieve content of multiple documents in a single batch call.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of relative file paths",
                }
            },
            "required": ["files"],
        },
        "tags": ["multi_get", "batch", "read", "documents"],
    },
    "ingest_url": {
        "name": "ingest_url",
        "description": "Ingest YouTube transcripts, Twitter/X threads, Reddit discussions, GitHub repos, or web articles via Agent-Reach.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to ingest"},
                "type": {
                    "type": "string",
                    "description": "Optional channel override: auto, youtube, twitter, reddit, web, github",
                },
                "transcribe": {
                    "type": "boolean",
                    "description": "Enable Whisper audio transcription for YouTube videos",
                },
            },
            "required": ["url"],
        },
        "tags": ["ingest", "youtube", "twitter", "reddit", "web", "github", "reach", "transcribe"],
    },
    "status": {
        "name": "status",
        "description": "Check knowledgebase index status, collection statistics, and daemon readiness.",
        "inputSchema": {"type": "object", "properties": {}},
        "tags": ["status", "health", "stats", "index", "collections"],
    },
    "compile_wiki": {
        "name": "compile_wiki",
        "description": "Trigger Workers AI synthesis to extract concepts and compile cross-silo topic hubs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_items": {"type": "integer", "description": "Max documents to compile per run"},
            },
        },
        "tags": ["wiki", "synthesis", "concepts", "compile", "workers_ai"],
    },
    "skills_list": {
        "name": "skills_list",
        "description": "List available specialized skills and protocols with short summaries (<200 tokens total).",
        "inputSchema": {"type": "object", "properties": {}},
        "tags": ["skills", "list", "catalog", "instructions"],
    },
    "skill_view": {
        "name": "skill_view",
        "description": "Inspect the complete instructions and operational protocol for a specific skill.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact name of the skill to view"},
            },
            "required": ["name"],
        },
        "tags": ["skills", "view", "instructions", "details"],
    },
    "tool_search": {
        "name": "tool_search",
        "description": "Search available knowledgebase tools and capabilities by keyword or phrase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords or capability to search for"},
            },
            "required": ["query"],
        },
        "tags": ["tools", "search", "discover", "capabilities"],
    },
    "tool_describe": {
        "name": "tool_describe",
        "description": "Get the complete input schema and parameter specification for a tool before invoking it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the tool to inspect"},
            },
            "required": ["name"],
        },
        "tags": ["tools", "describe", "schema", "parameters"],
    },
    "tool_call": {
        "name": "tool_call",
        "description": "Dynamically invoke a tool on the knowledgebase server by name with arguments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the tool to execute"},
                "arguments": {"type": "object", "description": "Arguments dictionary matching tool schema"},
            },
            "required": ["name", "arguments"],
        },
        "tags": ["tools", "call", "execute", "bridge"],
    },
}


def search_tools(query: str, repo_root: Path | None = None) -> List[Dict[str, str]]:
    """Tier 3: Find relevant tools by keyword matching name, description, or tags."""
    words = [w.lower().strip() for w in re.split(r"\W+", query) if w.strip()]
    if not words:
        return [
            {"name": t["name"], "description": t["description"]}
            for t in TOOL_REGISTRY.values()
        ]

    matched = []
    for tool in TOOL_REGISTRY.values():
        score = 0
        name_lower = tool["name"].lower()
        desc_lower = tool["description"].lower()
        tags = [t.lower() for t in tool.get("tags", [])]

        for w in words:
            if w in name_lower:
                score += 3
            if any(w in tag for tag in tags):
                score += 2
            if w in desc_lower:
                score += 1

        if score > 0:
            matched.append((score, {"name": tool["name"], "description": tool["description"]}))

    matched.sort(key=lambda x: x[0], reverse=True)
    return [m[1] for m in matched[:8]]


def describe_tool(name: str) -> Dict[str, Any]:
    """Tier 3: Return exact input schema and description for a named tool."""
    tool = TOOL_REGISTRY.get(name)
    if not tool:
        raise ValueError(f"Tool '{name}' not found in tool catalog")
    return {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": tool["inputSchema"],
    }


def call_tool(
    name: str,
    arguments: Dict[str, Any],
    repo_root: Path | None = None,
) -> Any:
    """Tier 3: Execute tool dynamically and return result."""
    root = Path(repo_root) if repo_root else REPO_ROOT

    if name == "skills_list":
        return list_skills(root / "skills")

    if name == "skill_view":
        sname = arguments.get("name", "")
        return view_skill(sname, root / "skills")

    if name == "tool_search":
        return search_tools(arguments.get("query", ""), root)

    if name == "tool_describe":
        return describe_tool(arguments.get("name", ""))

    if name == "tool_call":
        inner_name = arguments.get("name", "")
        inner_args = arguments.get("arguments", {})
        return call_tool(inner_name, inner_args, root)

    if name == "ingest_url":
        from connectors.reach import ingest_url
        url = arguments.get("url", "")
        ch = arguments.get("type", "auto")
        transcribe = bool(arguments.get("transcribe", False))
        path, payload = ingest_url(
            url=url,
            corpus_root=root / "corpus",
            channel_type=ch,
            transcribe_audio=transcribe,
        )
        return {
            "status": "success",
            "file": str(path.relative_to(root)).replace("\\", "/"),
            "title": payload.title,
            "silo": payload.silo,
            "summary": payload.summary,
        }

    if name in ("search", "query"):
        q = arguments.get("query", "")
        silo = arguments.get("silo")
        qmd_args = ["search", q]
        if silo and silo.lower() != "all":
            qmd_args.extend(["-c", silo])
        if sys.platform == "win32":
            cmd = ["cmd.exe", "/c", str(root / "qmd.cmd")] + qmd_args
        else:
            cmd = ["qmd"] + qmd_args
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=30)
        return proc.stdout or proc.stderr

    if name == "get":
        fpath = arguments.get("file", "")
        full_path = root / fpath if not Path(fpath).is_absolute() else Path(fpath)
        if not full_path.exists():
            return f"File not found: {fpath}"
        text = full_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        offset = max(1, int(arguments.get("offset", 1))) - 1
        count = int(arguments.get("count", len(lines)))
        selected = lines[offset : offset + count]
        return "\n".join(selected)

    if name == "status":
        if sys.platform == "win32":
            cmd = ["cmd.exe", "/c", str(root / "qmd.cmd"), "status"]
        else:
            cmd = ["qmd", "status"]
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=20)
        return proc.stdout or proc.stderr

    if name == "compile_wiki":
        # Run wiki compiler orchestrator step
        from orchestrator import run_pipeline
        summary = run_pipeline(dry_run=False, max_items=arguments.get("max_items", 10))
        return summary

    raise ValueError(f"Unknown tool name: '{name}'")


# ----------------------------------------------------------------------
# Progressive Tools MCP Manifest
# ----------------------------------------------------------------------

def get_progressive_tools_manifest() -> List[Dict[str, Any]]:
    """Return the curated set of tools advertised when progressive mode is active.

    Total token budget: <1,000 tokens instead of 20,000+ tokens.
    """
    progressive_names = [
        "skills_list",
        "skill_view",
        "tool_search",
        "tool_describe",
        "tool_call",
        "search",
        "get",
    ]
    return [
        {
            "name": TOOL_REGISTRY[n]["name"],
            "description": TOOL_REGISTRY[n]["description"],
            "inputSchema": TOOL_REGISTRY[n]["inputSchema"],
        }
        for n in progressive_names
    ]


def handle_progressive_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    repo_root: Path | None = None,
) -> Dict[str, Any]:
    """Execute a progressive tool and return compliant MCP tool result."""
    try:
        res = call_tool(tool_name, arguments, repo_root=repo_root)
        if isinstance(res, (dict, list)):
            text = json.dumps(res, indent=2)
        else:
            text = str(res)
        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error executing tool '{tool_name}': {e}"}],
            "isError": True,
        }
