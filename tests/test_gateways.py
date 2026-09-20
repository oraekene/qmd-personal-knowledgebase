"""Tests for Multi-Client Bot Gateways (Telegram, Discord, OpenAPI)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gateways.bot_gateway import (
    DiscordBotHandler,
    TelegramBotHandler,
    generate_openapi_schema,
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
