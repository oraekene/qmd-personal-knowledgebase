"""E2E Test Suite 7: Multi-Channel Gateways (Telegram, Discord, OpenAPI REST).

Tests end-to-end bot gateways and API schema:
- TelegramBotHandler webhook updates, command parsing (/help, /search, /get, /run)
- DiscordBotHandler interaction webhooks (PING, slash commands: search, get, run)
- Message length limit enforcement (Telegram 4096 chars, Discord 2000 chars)
- OpenAPI 3.1.0 specification schema compliance for Custom GPT Actions
- Graceful error reporting when commands fail or inputs are missing
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from gateways.bot_gateway import (
    DiscordBotHandler,
    TelegramBotHandler,
    generate_openapi_schema,
)


@pytest.fixture
def mock_pi_bridge():
    """Provides a mocked PiBridge for bot interaction testing."""
    bridge = MagicMock()
    bridge.execute_goal.return_value = {
        "status": "completed",
        "response": "Autonomous analysis complete. Found 3 key findings in knowledgebase.",
        "tool_calls": [{"tool": "search", "args": {"query": "test"}}],
    }
    return bridge


def test_e2e_telegram_commands_and_routing(tmp_path: pathlib.Path, mock_pi_bridge: MagicMock):
    """Verifies Telegram command dispatch, help menus, and length truncation."""
    notes_dir = tmp_path / "corpus" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    test_note = notes_dir / "briefing.md"
    test_note.write_text("# Project Briefing\nAll deliverables on track.\n", encoding="utf-8")

    handler = TelegramBotHandler(pi_bridge=mock_pi_bridge, repo_root=tmp_path)

    # 1. /start command
    start_update = {
        "update_id": 1001,
        "message": {"chat": {"id": 12345}, "text": "/start"},
    }
    res_start = handler.handle_update(start_update)
    assert res_start["status"] == "handled"
    assert "QMD Knowledgebase & Pi Agent Bot" in res_start["reply"]
    assert "/search" in res_start["reply"]

    # 2. /get command
    get_update = {
        "update_id": 1002,
        "message": {"chat": {"id": 12345}, "text": "  /get corpus/notes/briefing.md  "},
    }
    res_get = handler.handle_update(get_update)
    assert res_get["status"] == "handled"
    assert "Project Briefing" in res_get["reply"]

    # 3. /run autonomous goal command
    run_update = {
        "update_id": 1003,
        "message": {"chat": {"id": 12345}, "text": "/run Research distributed state machines"},
    }
    res_run = handler.handle_update(run_update)
    assert res_run["status"] == "handled"
    assert "Pi Agent Result" in res_run["reply"]
    assert "Autonomous analysis complete" in res_run["reply"]
    mock_pi_bridge.execute_goal.assert_called_with("Research distributed state machines")

    # 4. Message length limit truncation (Telegram <= 4096 chars)
    mock_pi_bridge.execute_goal.return_value = {"response": "A" * 5000}
    long_update = {
        "update_id": 1004,
        "message": {"chat": {"id": 12345}, "text": "/run Long query"},
    }
    res_long = handler.handle_update(long_update)
    assert len(res_long["reply"]) <= 4096
    assert "Truncated by Telegram limit" in res_long["reply"]

    # 5. Non-text or empty updates
    assert handler.handle_update({})["status"] == "ignored"
    assert handler.handle_update({"message": {"chat": {"id": 1}, "text": ""}})["status"] == "ignored"


def test_e2e_discord_interactions_and_slash_commands(tmp_path: pathlib.Path, mock_pi_bridge: MagicMock):
    """Verifies Discord interaction webhook handling (PING and Application Commands)."""
    notes_dir = tmp_path / "corpus" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "discord_test.md").write_text("# Discord Test\nActive integration.\n", encoding="utf-8")

    handler = DiscordBotHandler(pi_bridge=mock_pi_bridge, repo_root=tmp_path)

    # 1. Discord PING verification (Type 1 -> Type 1 response)
    ping_payload = {"type": 1}
    ping_res = handler.handle_interaction(ping_payload)
    assert ping_res == {"type": 1}

    # 2. Discord Slash Command: /get (Type 2 -> Type 4 CHANNEL_MESSAGE_WITH_SOURCE)
    get_payload = {
        "type": 2,
        "data": {
            "name": "get",
            "options": [{"name": "file", "value": "corpus/notes/discord_test.md"}],
        },
    }
    get_res = handler.handle_interaction(get_payload)
    assert get_res["type"] == 4
    content = get_res["data"]["content"]
    assert "Discord Test" in content
    assert "Active integration" in content

    # 3. Discord Slash Command: /run
    run_payload = {
        "type": 2,
        "data": {
            "name": "run",
            "options": [{"name": "goal", "value": "Synthesize security whitepaper"}],
        },
    }
    run_res = handler.handle_interaction(run_payload)
    assert run_res["type"] == 4
    assert "Pi Agent Result" in run_res["data"]["content"]

    # 4. Discord 2000 character limit truncation
    mock_pi_bridge.execute_goal.return_value = {"response": "D" * 3000}
    long_res = handler.handle_interaction(run_payload)
    assert len(long_res["data"]["content"]) <= 2000
    assert "Truncated" in long_res["data"]["content"]


def test_e2e_openapi_schema_spec_compliance():
    """Verifies that the generated OpenAPI schema is compliant with 3.1.0 specifications."""
    schema = generate_openapi_schema("https://custom-domain.space")

    assert schema["openapi"] == "3.1.0"
    assert schema["servers"][0]["url"] == "https://custom-domain.space"
    
    paths = schema["paths"]
    assert "/api/search" in paths
    assert "/api/pi/goal" in paths
    assert "/api/connectors/reach" in paths
    assert "/api/sync/status" in paths

    # Verify BearerAuth security definition
    assert "BearerAuth" in schema["components"]["securitySchemes"]
    assert schema["security"][0]["BearerAuth"] == []
