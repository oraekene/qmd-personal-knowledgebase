"""Tests for User Action Audit Trail, Prompt Templates, Skills & Tools creation, and Upload routing."""

import io
import json
import tempfile
import zipfile
from pathlib import Path

from auth_proxy.prompt_engine import (
    delete_custom_prompt,
    get_prompt_response,
    list_prompts,
    load_custom_prompts,
    save_custom_prompt,
)
from auth_proxy.progressive_tools import (
    TOOL_REGISTRY,
    create_skill,
    list_skills,
    register_dynamic_tool,
)
from control_plane.server import SystemLogger, find_pids_by_port, get_qmd_cli_args


def test_system_logger_audit_trail(tmp_path: Path):
    logger = SystemLogger(repo_root=tmp_path)
    logger.log("SYSTEM", "Normal daemon startup message")
    logger.log_user_action("SEARCH_EXECUTE", {"query": "vector indexing", "silo": "all"})
    logger.log_user_action("UPLOAD_FILE", {"filename": "export.zip", "target_dir": "inbox/chats"})

    audit_file = tmp_path / "logs" / "audit.log"
    system_file = tmp_path / "logs" / "system.log"

    assert audit_file.exists(), "audit.log should be created on user action"
    assert system_file.exists(), "system.log should be created"

    audit_content = audit_file.read_text(encoding="utf-8")
    assert "SEARCH_EXECUTE" in audit_content
    assert "UPLOAD_FILE" in audit_content
    assert "Normal daemon startup message" not in audit_content, "Audit log must not contain daemon logs"

    # Filter logs by USER_ACTION
    user_actions = logger.get_logs(source="USER_ACTION")
    assert len(user_actions) == 2
    assert user_actions[0]["source"] == "USER_ACTION"
    assert "SEARCH_EXECUTE" in user_actions[0]["message"]


def test_custom_prompt_templates(tmp_path: Path):
    prompt_def = {
        "name": "custom-code-review",
        "description": "Reviews code against ADR principles",
        "arguments": [{"name": "repo", "description": "Repo name", "required": True}],
        "content": "Perform a rigorous architectural code review of {repo} following docs/adr.",
    }
    saved = save_custom_prompt(prompt_def, repo_root=tmp_path)
    assert saved["name"] == "custom-code-review"

    # Verify listing includes it
    all_prompts = list_prompts(repo_root=tmp_path)
    prompt_names = [p["name"] for p in all_prompts]
    assert "custom-code-review" in prompt_names
    assert "knowledge-search" in prompt_names  # built-in remains available

    # Verify execution / substitution
    res = get_prompt_response("custom-code-review", {"repo": "nebula-core"}, repo_root=tmp_path)
    assert "nebula-core" in res["messages"][0]["content"]["text"]

    # Clean up
    deleted = delete_custom_prompt("custom-code-review", repo_root=tmp_path)
    assert deleted is True
    prompts_after = list_prompts(repo_root=tmp_path)
    assert "custom-code-review" not in [p["name"] for p in prompts_after]


def test_create_skill_and_register_tool(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    res = create_skill(
        name="test-automation",
        description="Automated system diagnostic skill",
        content="## Protocol\n1. Run diagnostics.\n2. Report findings.",
        skills_dir=skills_dir,
    )
    assert res["name"] == "test-automation"
    skill_file = skills_dir / "test-automation" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text(encoding="utf-8")
    assert "name: test-automation" in content
    assert "Run diagnostics." in content

    # Test tool registration
    tool_def = {
        "name": "test_echo_tool",
        "description": "Echoes back the message",
        "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}},
        "tags": ["test", "echo"],
    }
    reg = register_dynamic_tool(tool_def, repo_root=tmp_path)
    assert reg["name"] == "test_echo_tool"
    assert "test_echo_tool" in TOOL_REGISTRY
    tools_file = tmp_path / "tools.json"
    assert tools_file.exists()


def test_get_qmd_cli_args(tmp_path: Path):
    # When tsx and qmd.ts exist
    qmd_main = tmp_path / "qmd-main"
    tsx = qmd_main / "node_modules" / "tsx" / "dist" / "cli.mjs"
    qmd_ts = qmd_main / "src" / "cli" / "qmd.ts"
    tsx.parent.mkdir(parents=True, exist_ok=True)
    qmd_ts.parent.mkdir(parents=True, exist_ok=True)
    tsx.write_text("// tsx", encoding="utf-8")
    qmd_ts.write_text("// qmd", encoding="utf-8")

    args = get_qmd_cli_args(tmp_path)
    assert args[0] == "node"
    assert str(tsx) in args[1]
    assert str(qmd_ts) in args[2]


def test_find_pids_by_port_fast_closed_port():
    # An unused high port should return immediately without spawning netstat
    pids = find_pids_by_port(59999)
    assert pids == []
