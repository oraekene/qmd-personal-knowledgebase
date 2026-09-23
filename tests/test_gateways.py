"""Tests for Multi-Client Bot Gateways (Telegram, Discord, OpenAPI)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gateways.bot_gateway import (
    DiscordBotHandler,
    TelegramBotHandler,
    generate_openapi_schema,
    run_telegram_polling,
)


@pytest.fixture
def mock_pi():
    pi = MagicMock()
    pi.execute_goal.return_value = {
        "status": "completed",
        "response": "Pi executed goal successfully.",
        "tool_calls": [{"tool": "search"}],
    }
    return pi


def test_telegram_handler_commands(tmp_path, mock_pi):
    handler = TelegramBotHandler(pi_bridge=mock_pi, repo_root=tmp_path)
    
    # 1. Start / Help
    update = {"message": {"chat": {"id": 123}, "text": "/start"}}
    res = handler.handle_update(update)
    assert res["status"] == "handled"
    assert "Available commands" in res["reply"]
    
    # 2. Run goal
    update = {"message": {"chat": {"id": 123}, "text": "/run summarize recent ideas"}}
    res = handler.handle_update(update)
    assert res["status"] == "handled"
    mock_pi.execute_goal.assert_called_with("summarize recent ideas")
    assert "Pi executed goal successfully." in res["reply"]
    
    # 3. Freeform text
    update = {"message": {"chat": {"id": 123}, "text": "What are my notes about AI?"}}
    res = handler.handle_update(update)
    assert res["status"] == "handled"
    mock_pi.execute_goal.assert_called_with("What are my notes about AI?")


def test_telegram_search_and_get(tmp_path, mock_pi):
    handler = TelegramBotHandler(pi_bridge=mock_pi, repo_root=tmp_path)
    
    with patch("auth_proxy.progressive_tools.call_tool", return_value="Result snippet") as mock_tool:
        # Search
        res = handler.handle_update({"message": {"chat": {"id": 1}, "text": "/search neural networks"}})
        assert "Search Results" in res["reply"]
        assert "Result snippet" in res["reply"]
        
        # Get
        res = handler.handle_update({"message": {"chat": {"id": 1}, "text": "/get corpus/notes/nn.md"}})
        assert "Result snippet" in res["reply"]


def test_discord_interaction_handler(tmp_path, mock_pi):
    handler = DiscordBotHandler(pi_bridge=mock_pi, repo_root=tmp_path)
    
    # 1. Ping
    ping_payload = {"type": 1}
    res = handler.handle_interaction(ping_payload)
    assert res["type"] == 1
    
    # 2. Slash command /run
    run_payload = {
        "type": 2,
        "data": {
            "name": "run",
            "options": [{"name": "goal", "value": "check system health"}],
        },
    }
    res = handler.handle_interaction(run_payload)
    assert res["type"] == 4
    assert "Pi executed goal successfully." in res["data"]["content"]


def test_openapi_schema_generation():
    schema = generate_openapi_schema(base_url="https://kb.parmeterai.space")
    assert schema["openapi"] == "3.1.0"
    assert "/api/search" in schema["paths"]
    assert "/api/pi/goal" in schema["paths"]
    assert "/api/connectors/reach" in schema["paths"]
    assert "/api/sync/status" in schema["paths"]
    assert "BearerAuth" in schema["components"]["securitySchemes"]


def test_run_telegram_polling_no_token(tmp_path, caplog):
    # When no token is configured, it warns and returns early
    run_telegram_polling(token="", repo_root=tmp_path, max_loops=1)
    assert any("TELEGRAM_BOT_TOKEN not configured" in rec.message for rec in caplog.records)


def test_run_telegram_polling_success(tmp_path):
    # Mock urllib request / response for getUpdates and sendMessage
    import io
    import json
    
    updates_payload = {
        "ok": True,
        "result": [
            {
                "update_id": 999,
                "message": {
                    "chat": {"id": 42},
                    "text": "/start",
                },
            }
        ],
    }
    
    mock_resp = io.BytesIO(json.dumps(updates_payload).encode("utf-8"))
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        
        run_telegram_polling(
            token="test-token-123",
            repo_root=tmp_path,
            poll_interval=0.01,
            max_loops=1,
        )
        
        assert mock_urlopen.call_count >= 1


def test_supervisor_bot_gateway_lifecycle(tmp_path):
    from control_plane.server import DaemonSupervisor, SystemLogger
    logger = SystemLogger(repo_root=tmp_path)
    supervisor = DaemonSupervisor(repo_root=tmp_path, logger=logger)
    
    # Mock subprocess.Popen
    mock_proc = MagicMock()
    mock_proc.pid = 9876
    mock_proc.poll.return_value = None
    mock_proc.stdout.readline.return_value = ""
    
    with patch("subprocess.Popen", return_value=mock_proc):
        res = supervisor.start_daemon("bot_gateway")
        assert res["status"] == "started"
        assert res["pid"] == 9876
        assert "bot_gateway" in supervisor.processes
        
        stop_res = supervisor.stop_daemon("bot_gateway")
        assert stop_res["status"] == "stopped"

