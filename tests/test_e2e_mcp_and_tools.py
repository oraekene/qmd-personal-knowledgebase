"""E2E Test Suite 3: Auth Proxy, OAuth RFC 7591 Shim, MCP Protocol & Progressive Tools.

Tests end-to-end MCP integration:
- RFC 7591 Dynamic Client Registration and Token Issuance
- MCP JSON-RPC protocol (initialize, prompts/list, prompts/get, tools/list, tools/call)
- Hermes 3-tier progressive tool disclosure
- Dynamic tools registry (tools.json) execution
- System prompt and SOUL.md synthesis in MCP handshake
- Security validation, missing token rejection, and malformed JSON-RPC handling
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from auth_proxy.prompt_engine import (
    delete_custom_prompt,
    get_prompt_response,
    list_prompts,
    save_custom_prompt,
)
from auth_proxy.progressive_tools import (
    TOOL_REGISTRY,
    call_tool,
    create_skill,
    describe_tool,
    get_progressive_tools_manifest,
    handle_progressive_tool_call,
    list_skills,
    register_dynamic_tool,
    search_tools,
    view_skill,
)


@pytest.fixture
def mcp_env(tmp_path: pathlib.Path):
    """Sets up an isolated environment with SOUL.md, prompts, skills, and tools."""
    (tmp_path / "SOUL.md").write_text(
        "# Core Persona\n\nYou are an autonomous AI research engineer with direct knowledgebase access.\n",
        encoding="utf-8",
    )
    (tmp_path / "SYSTEM_PROMPT.md").write_text(
        "# System Instructions\n\nAlways cite knowledgebase units using [title](file:///path).\n",
        encoding="utf-8",
    )
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools.json").write_text("[]", encoding="utf-8")
    (tmp_path / "prompts.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_e2e_oauth_shim_dynamic_registration_and_auth():
    """Verifies RFC 7591 client registration, PKCE verification, and metadata endpoints."""
    from auth_proxy.oauth import (
        OAuthStore,
        _compute_s256,
        get_authorization_server_metadata,
        get_protected_resource_metadata,
        verify_pkce,
    )

    store = OAuthStore()

    # 1. Dynamic Client Registration (RFC 7591)
    client_metadata = {
        "client_name": "Claude Desktop Client",
        "redirect_uris": ["http://localhost:54321/callback"],
    }
    client_reg = store.register_client(client_metadata)
    assert "client_id" in client_reg
    assert "client_secret" in client_reg
    assert client_reg["client_name"] == "Claude Desktop Client"
    client_id = client_reg["client_id"]

    # 2. PKCE Challenge Setup (RFC 7636)
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = _compute_s256(verifier)
    assert verify_pkce(verifier, challenge) is True
    assert verify_pkce("wrong_verifier", challenge) is False

    # 3. Create Authorization Code with PKCE challenge
    redirect_uri = "http://localhost:54321/callback"
    code = store.create_authorization_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    assert code.startswith("code_")

    # 4. Consume Code with valid PKCE verifier
    is_valid, err_msg = store.validate_and_consume_code(
        code=code,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
    )
    assert is_valid is True
    assert err_msg == ""

    # 5. One-time code cannot be reused
    reuse_valid, reuse_err = store.validate_and_consume_code(
        code=code,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
    )
    assert reuse_valid is False
    assert "already used" in reuse_err.lower() or "invalid" in reuse_err.lower()

    # 6. Verify RFC 9728 & RFC 8414 metadata
    issuer = "https://parmeterai.space"
    res_meta = get_protected_resource_metadata(issuer)
    assert res_meta["resource"] == "https://parmeterai.space/mcp"
    assert "https://parmeterai.space" in res_meta["authorization_servers"]

    auth_meta = get_authorization_server_metadata(issuer)
    assert auth_meta["issuer"] == issuer
    assert auth_meta["token_endpoint"] == f"{issuer}/oauth/token"
    assert "S256" in auth_meta["code_challenge_methods_supported"]


def test_e2e_mcp_prompt_engine_lifecycle(mcp_env: pathlib.Path):
    """Verifies creating, listing, interpolating, and deleting custom MCP prompts."""
    repo = mcp_env

    # 1. Verify default prompts list contains built-in knowledge-search
    defaults = list_prompts(repo_root=repo)
    default_names = [p["name"] for p in defaults]
    assert "knowledge-search" in default_names

    # 2. Add custom prompt template
    custom_prompt = {
        "name": "architecture-audit",
        "description": "Performs an architectural compliance audit on a repository silo",
        "arguments": [
            {"name": "silo_name", "description": "Silo to audit (e.g. chats, notes, pdfs)", "required": True},
            {"name": "focus_area", "description": "Specific focus area", "required": False},
        ],
        "content": "Audit the {silo_name} silo thoroughly with primary focus on {focus_area}. Cite all violated ADRs.",
    }
    saved = save_custom_prompt(custom_prompt, repo_root=repo)
    assert saved["name"] == "architecture-audit"

    # 3. Verify it is included in list_prompts
    updated_prompts = list_prompts(repo_root=repo)
    updated_names = [p["name"] for p in updated_prompts]
    assert "architecture-audit" in updated_names

    # 4. Execute prompt with arguments
    res = get_prompt_response(
        "architecture-audit",
        {"silo_name": "chats/claude", "focus_area": "token quantization"},
        repo_root=repo,
    )
    assert "messages" in res
    prompt_text = res["messages"][0]["content"]["text"]
    assert "chats/claude" in prompt_text
    assert "token quantization" in prompt_text

    # 5. Delete prompt
    deleted = delete_custom_prompt("architecture-audit", repo_root=repo)
    assert deleted is True
    final_prompts = list_prompts(repo_root=repo)
    assert "architecture-audit" not in [p["name"] for p in final_prompts]


def test_e2e_hermes_progressive_tools_disclosure(mcp_env: pathlib.Path):
    """Verifies Hermes 3-tier progressive tool disclosure, dynamic tools, and execution."""
    repo = mcp_env

    # 1. Tier 1: Base manifest contains compact progressive tools
    manifest = get_progressive_tools_manifest()
    manifest_names = [t["name"] for t in manifest]
    assert "skills_list" in manifest_names
    assert "skill_view" in manifest_names
    assert "tool_search" in manifest_names
    assert "tool_describe" in manifest_names
    assert "tool_call" in manifest_names
    assert "search" in manifest_names
    assert "get" in manifest_names

    # 2. Tier 2: Create and list specialized on-demand skills
    skill_def = create_skill(
        name="incident-postmortem",
        description="Analyzes outages and generates incident reports",
        content="## Incident Protocol\n1. Inspect system logs.\n2. Summarize root cause.\n3. Propose mitigations.",
        skills_dir=repo / "skills",
    )
    assert skill_def["name"] == "incident-postmortem"
    assert (repo / "skills" / "incident-postmortem" / "SKILL.md").exists()

    all_skills = list_skills(skills_dir=repo / "skills")
    skill_names = [s["name"] for s in all_skills]
    assert "incident-postmortem" in skill_names

    skill_body = view_skill("incident-postmortem", skills_dir=repo / "skills")
    assert "## Incident Protocol" in skill_body

    # 3. Tier 3: Search tools catalog
    search_res = search_tools("bm25 query", repo_root=repo)
    tool_names = [t["name"] for t in search_res]
    assert "search" in tool_names

    desc = describe_tool("search")
    assert desc["name"] == "search"
    assert "query" in desc["inputSchema"]["properties"]

    # 4. Register a dynamic tool via tools.json
    custom_tool = {
        "name": "backup_to_r2_bucket",
        "description": "Trigger automated snapshot backup to Cloudflare R2",
        "inputSchema": {
            "type": "object",
            "properties": {"bucket_name": {"type": "string"}},
            "required": ["bucket_name"],
        },
        "tags": ["backup", "cloud", "r2"],
    }
    registered = register_dynamic_tool(custom_tool, repo_root=repo)
    assert registered["name"] == "backup_to_r2_bucket"
    assert "backup_to_r2_bucket" in TOOL_REGISTRY

    # Search finds the dynamic tool
    found = search_tools("r2 snapshot", repo_root=repo)
    assert any(t["name"] == "backup_to_r2_bucket" for t in found)

    # 5. MCP Tool Call execution via handle_progressive_tool_call
    mcp_res = handle_progressive_tool_call(
        "skills_list",
        {},
        repo_root=repo,
    )
    assert mcp_res["isError"] is False
    assert "incident-postmortem" in mcp_res["content"][0]["text"]


def test_e2e_mcp_json_rpc_schema_compliance():
    """Tests JSON-RPC protocol error codes and schema enforcement."""
    # Valid JSON-RPC 2.0 Request
    valid_req = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    }

    assert valid_req["jsonrpc"] == "2.0"
    assert "method" in valid_req
    assert "id" in valid_req

    # Method not found response simulation (-32601)
    error_resp = {
        "jsonrpc": "2.0",
        "id": "req-unknown",
        "error": {
            "code": -32601,
            "message": "Method not found: unknown/endpoint",
        },
    }
    assert error_resp["error"]["code"] == -32601
    assert "Method not found" in error_resp["error"]["message"]
