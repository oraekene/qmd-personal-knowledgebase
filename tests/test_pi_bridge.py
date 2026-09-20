"""Tests for Pi Agent Execution Bridge."""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from control_plane.pi_bridge import PiBridge, get_operational_mode


@pytest.fixture
def repo_root(tmp_path):
    # Setup mock repo structure
    corpus = tmp_path / "corpus" / "notes"
    corpus.mkdir(parents=True)
    (corpus / "sample.md").write_text("# Sample Note\nThis is test content.", encoding="utf-8")
    
    skills = tmp_path / "skills" / "search-expert"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: search-expert\ndescription: Searches notes\n---\nBody", encoding="utf-8")
    
    return tmp_path


def test_pi_bridge_lifecycle_and_state(repo_root):
    bridge = PiBridge(repo_root=repo_root, prefer_subprocess=False)
    assert not bridge.is_running
    
    assert bridge.start() is True
    assert bridge.is_running
    assert bridge.mode == "native"
    
    state_res = bridge.get_state()
    assert state_res["success"] is True
    assert state_res["data"]["sessionId"] == bridge.session_id
    assert state_res["data"]["thinkingLevel"] == "high"
    
    bridge.stop()
    assert not bridge.is_running


def test_pi_bridge_events_and_listeners(repo_root):
    bridge = PiBridge(repo_root=repo_root)
    received_events = []
    def on_event(evt):
        received_events.append(evt)
        
    bridge.add_event_listener(on_event)
    bridge.start()
    
    bridge.send_command({"type": "set_model", "modelId": "test-model"})
    assert bridge.state["model"] == "test-model"
    
    goal_res = bridge.execute_goal("status")
    assert goal_res["status"] == "completed"
    
    assert len(received_events) > 0
    event_types = [e["type"] for e in received_events]
    assert "message_start" in event_types
    assert "thinking_delta" in event_types
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert "turn_end" in event_types
    
    # Verify get_events pagination
    events = bridge.get_events(since_id=0)
    assert len(events) == len(received_events)
    
    bridge.remove_event_listener(on_event)
    bridge.stop()


def test_pi_bridge_commands_catalog(repo_root):
    bridge = PiBridge(repo_root=repo_root)
    bridge.start()
    
    cmds = bridge.get_commands()
    assert len(cmds) > 0
    cmd_names = [c["name"] for c in cmds]
    assert "search" in cmd_names
    assert "get" in cmd_names
    assert "ingest_url" in cmd_names
    assert "search-expert" in cmd_names  # from mocked skills directory
    
    bridge.stop()


def test_pi_bridge_operational_mode_models(repo_root, monkeypatch):
    bridge = PiBridge(repo_root=repo_root)
    bridge.start()
    
    # 1. Offline only
    monkeypatch.setenv("OPERATIONAL_MODE", "offline-only")
    res = bridge.send_command({"type": "get_available_models"})
    models = res["data"]["models"]
    model_ids = [m["modelId"] for m in models]
    assert "local-gguf" in model_ids
    assert "claude-3-5-sonnet" not in model_ids
    
    # 2. Offline + Cloudflare Wiki
    monkeypatch.setenv("OPERATIONAL_MODE", "offline+cloudflare-wiki")
    res = bridge.send_command({"type": "get_available_models"})
    models = res["data"]["models"]
    model_ids = [m["modelId"] for m in models]
    assert "local-gguf" in model_ids
    assert "@cf/meta/llama-3.1-8b-instruct-fp8-fast" in model_ids
    assert "claude-3-5-sonnet" not in model_ids
    
    # 3. Full mode
    monkeypatch.setenv("OPERATIONAL_MODE", "full")
    res = bridge.send_command({"type": "get_available_models"})
    models = res["data"]["models"]
    model_ids = [m["modelId"] for m in models]
    assert "local-gguf" in model_ids
    assert "@cf/meta/llama-3.1-8b-instruct-fp8-fast" in model_ids
    assert "claude-3-5-sonnet" in model_ids
    
    bridge.stop()


def test_pi_bridge_execute_get_tool(repo_root):
    bridge = PiBridge(repo_root=repo_root)
    bridge.start()
    
    with patch("auth_proxy.progressive_tools.call_tool", return_value="# Sample Note\nThis is test content.") as mock_tool:
        res = bridge.execute_goal("read corpus/notes/sample.md")
        assert res["status"] == "completed"
        assert "Sample Note" in res["response"]
        assert len(res["tool_calls"]) == 1
        assert res["tool_calls"][0]["tool"] == "get"
        
    bridge.stop()
