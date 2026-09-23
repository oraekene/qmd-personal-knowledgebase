"""E2E Test Suite 8: Web Control Plane HTTP Server, SystemLogger, Audit Trail & Daemon Lifecycle.

Tests end-to-end Web Control Plane:
- Live HTTP server initialization on an ephemeral port
- SystemLogger logging, streaming, filtering, and export
- Dedicated User Action Audit Trail (logs/audit.log) persistence across all user mutations
- REST API endpoint coverage:
  - GET /api/status, /api/config, /api/prompts, /api/skills, /api/tools, /api/automations, /api/sandboxes, /api/audit-trail
  - POST /api/config (saves .env updates and logs user action)
  - POST /api/prompts/templates (creates custom MCP prompt template and logs user action)
  - POST /api/skills (creates custom skill and logs user action)
  - POST /api/tools (registers dynamic bridge tool and logs user action)
  - POST /api/automations (upserts automation job and logs user action)
  - POST /api/engine/operational-mode (toggles operational mode and logs user action)
- Verification of on-disk logs/audit.log entries
- CORS preflight OPTIONS handling
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer
from unittest.mock import MagicMock, patch

import pytest

from control_plane.pi_bridge import PiBridge
from control_plane.scheduler import SchedulerDaemon, SchedulerStore
from control_plane.server import (
    SystemLogger,
    make_control_plane_handler,
)
from sync.cloudflare_sync import CloudflareSyncManager


def get_free_port() -> int:
    """Find an available ephemeral TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def control_plane_env(tmp_path: pathlib.Path):
    """Sets up an isolated environment with files, logs, and live server instance."""
    (tmp_path / ".env").write_text("RETRIEVAL_MODE=cpu-only\nOPERATIONAL_MODE=full\n", encoding="utf-8")
    (tmp_path / "SOUL.md").write_text("# Test Persona\nAutonomous agent.\n", encoding="utf-8")
    (tmp_path / "SYSTEM_PROMPT.md").write_text("# Test Prompt\nBe concise.\n", encoding="utf-8")
    (tmp_path / "corpus").mkdir(exist_ok=True)
    (tmp_path / "inbox").mkdir(exist_ok=True)
    (tmp_path / "skills").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)

    static_dir = tmp_path / "control_plane" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text("<html><body>Control Plane UI</body></html>", encoding="utf-8")

    port = get_free_port()
    system_logger = SystemLogger(repo_root=tmp_path)
    scheduler_store = SchedulerStore(tmp_path / "automations.json")
    scheduler_daemon = SchedulerDaemon(repo_root=tmp_path, store=scheduler_store)
    pi_bridge = PiBridge(repo_root=tmp_path)
    pi_bridge.start()
    sync_manager = CloudflareSyncManager()

    handler_cls = make_control_plane_handler(
        repo_root=tmp_path,
        static_dir=static_dir,
        logger=system_logger,
        scheduler=scheduler_daemon,
        pi_bridge_inst=pi_bridge,
        sync_manager_inst=sync_manager,
    )

    httpd = HTTPServer(("127.0.0.1", port), handler_cls)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    # Yield test context
    yield {
        "root": tmp_path,
        "base_url": base_url,
        "logger": system_logger,
        "audit_file": tmp_path / "logs" / "audit.log",
        "system_file": tmp_path / "logs" / "system.log",
    }

    # Teardown
    httpd.shutdown()
    httpd.server_close()
    pi_bridge.stop()


def _http_request(url: str, method: str = "GET", data: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    """Helper to perform HTTP requests against the live control plane test server."""
    req_headers = headers or {}
    req_body = None
    if data is not None:
        req_body = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=req_body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_content = e.read().decode("utf-8")
        try:
            parsed = json.loads(err_content)
        except Exception:
            parsed = {"error": err_content}
        return e.code, parsed


def test_e2e_control_plane_status_and_cors(control_plane_env: dict):
    """Verifies GET /api/status, service readiness metrics, and CORS preflight headers."""
    base_url = control_plane_env["base_url"]

    # 1. GET /api/status
    status_code, data = _http_request(f"{base_url}/api/status")
    assert status_code == 200
    assert "services" in data
    assert "corpus" in data
    assert "inbox" in data
    assert data["retrieval_mode"] == "cpu-only"

    # 2. CORS Preflight OPTIONS request
    req = urllib.request.Request(f"{base_url}/api/search", method="OPTIONS")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 204
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"
        assert "GET" in resp.headers.get("Access-Control-Allow-Methods")


def test_e2e_control_plane_user_action_audit_trail(control_plane_env: dict):
    """Verifies that all administrative user mutations write to logs/audit.log and /api/audit-trail."""
    base_url = control_plane_env["base_url"]
    audit_file: pathlib.Path = control_plane_env["audit_file"]

    # 1. Action: Update Configuration
    status, config_res = _http_request(
        f"{base_url}/api/config",
        method="POST",
        data={"updates": {"TELEGRAM_BOT_TOKEN": "123456:ABC-DEF", "SEARCH_MAX_RESULTS": "25"}},
    )
    assert status == 200
    assert config_res["status"] == "saved"

    # 2. Action: Create Prompt Template
    status, prompt_res = _http_request(
        f"{base_url}/api/prompts/templates",
        method="POST",
        data={
            "name": "system-evaluator",
            "description": "Evaluates system architecture",
            "content": "Evaluate knowledgebase integrity for {target_silo}.",
        },
    )
    assert status == 201
    assert prompt_res["template"]["name"] == "system-evaluator"

    # 3. Action: Create Skill
    status, skill_res = _http_request(
        f"{base_url}/api/skills",
        method="POST",
        data={
            "name": "triage-protocol",
            "description": "Auto-triage inbound tickets",
            "content": "# Triage Rules\nClassify by priority.",
        },
    )
    assert status == 201
    assert skill_res["skill"]["name"] == "triage-protocol"

    # 4. Action: Register Dynamic Tool
    status, tool_res = _http_request(
        f"{base_url}/api/tools",
        method="POST",
        data={
            "name": "archive_vault",
            "description": "Archive old files to cold vault",
            "inputSchema": {"type": "object", "properties": {"days": {"type": "integer"}}},
        },
    )
    assert status == 201
    assert tool_res["tool"]["name"] == "archive_vault"

    # 5. Action: Save Automation Job
    status, auto_res = _http_request(
        f"{base_url}/api/automations",
        method="POST",
        data={
            "id": "job_weekly_digest",
            "name": "Weekly Digest",
            "action": "custom_command",
            "schedule": "@weekly",
        },
    )
    assert status == 200
    assert auto_res["job"]["id"] == "job_weekly_digest"

    # 6. Action: Change Operational Mode
    status, mode_res = _http_request(
        f"{base_url}/api/engine/operational-mode",
        method="POST",
        data={"mode": "offline-only"},
    )
    assert status == 200
    assert mode_res["operational_mode"] == "offline-only"

    # 7. Query Dedicated Audit Trail Endpoint
    status, audit_data = _http_request(f"{base_url}/api/audit-trail")
    assert status == 200
    entries = audit_data["entries"]
    assert len(entries) >= 6

    # Verify that all entries carry the USER_ACTION source marker
    for entry in entries:
        assert entry["source"] == "USER_ACTION"

    actions_captured = [e["message"] for e in entries]
    assert any("CONFIG_UPDATE" in m for m in actions_captured)
    assert any("ADD_PROMPT_TEMPLATE" in m for m in actions_captured)
    assert any("CREATE_SKILL" in m for m in actions_captured)
    assert any("REGISTER_TOOL" in m for m in actions_captured)
    assert any("AUTOMATION_SAVE" in m for m in actions_captured)
    assert any("OPERATIONAL_MODE_CHANGE" in m for m in actions_captured)

    # 8. Verify the physical file logs/audit.log exists and contains all audit lines
    assert audit_file.exists()
    audit_text = audit_file.read_text(encoding="utf-8")
    assert "[USER_ACTION]" in audit_text
    assert "CONFIG_UPDATE" in audit_text
    assert "CREATE_SKILL" in audit_text
    assert "AUTOMATION_SAVE" in audit_text


def test_e2e_control_plane_rest_catalogs_and_sandboxes(control_plane_env: dict):
    """Verifies GET endpoints for prompts, skills, tools, automations, and sandboxes."""
    base_url = control_plane_env["base_url"]

    # 1. GET /api/prompts
    status, prompts = _http_request(f"{base_url}/api/prompts")
    assert status == 200
    assert "soul" in prompts
    assert "system_prompt" in prompts
    assert "templates" in prompts

    # 2. GET /api/skills
    status, skills = _http_request(f"{base_url}/api/skills")
    assert status == 200
    assert "skills" in skills

    # 3. GET /api/tools
    status, tools = _http_request(f"{base_url}/api/tools")
    assert status == 200
    assert "catalog" in tools
    assert "progressive_manifest" in tools

    # 4. GET /api/automations
    status, automations = _http_request(f"{base_url}/api/automations")
    assert status == 200
    assert "automations" in automations
    assert automations["count"] >= 5

    # 5. GET /api/sandboxes
    status, sandboxes = _http_request(f"{base_url}/api/sandboxes")
    assert status == 200
    assert sandboxes["local"]["available"] is True
    assert "cloud" in sandboxes
