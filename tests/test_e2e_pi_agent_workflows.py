"""E2E Test Suite 4: Pi Agent Autonomous Reasoning Engine & ReACT Workflows.

Tests end-to-end Pi Bridge integration:
- Lifecycle management (start, stop, state query, event dispatch)
- Multi-turn ReACT goal execution (Goal -> Thought -> Tool Call -> Observation -> Answer)
- Tool execution dispatch (search, get, status, ingest_url)
- 3-Tier Operational Mode enforcement (offline-only vs offline+cloudflare-wiki vs full)
- Event streaming subscription and history tracking
- Error recovery and graceful degradation on tool failures
"""

from __future__ import annotations

import os
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from control_plane.pi_bridge import PiBridge, get_operational_mode


@pytest.fixture
def pi_workspace(tmp_path: pathlib.Path):
    """Sets up a realistic knowledgebase workspace with files for Pi agent."""
    corpus_notes = tmp_path / "corpus" / "notes"
    corpus_notes.mkdir(parents=True, exist_ok=True)
    sample_note = corpus_notes / "quantum_computing.md"
    sample_note.write_text(
        "---\nid: note-qc-01\ntitle: Quantum Error Correction\nsilo: notes\n---\n"
        "# Quantum Error Correction\nSurface codes demonstrate threshold fault tolerance.\n",
        encoding="utf-8",
    )
    (tmp_path / "skills").mkdir(exist_ok=True)
    return tmp_path


def test_e2e_pi_bridge_lifecycle_and_state(pi_workspace: pathlib.Path):
    """Tests session initialization, state reporting, and clean shutdown."""
    bridge = PiBridge(repo_root=pi_workspace, default_model="test-model-4b")
    events = []

    def on_event(evt):
        events.append(evt)

    bridge.add_event_listener(on_event)

    # 1. Start engine
    assert bridge.start() is True
    assert bridge.is_running is True
    assert any(e["type"] == "session_started" for e in events)

    # 2. Query state via JSON-RPC
    state_res = bridge.get_state()
    assert state_res["success"] is True
    assert state_res["data"]["model"] == "test-model-4b"
    assert state_res["data"]["sessionId"] == bridge.session_id

    # 3. Model switching
    set_model_res = bridge.send_command({"type": "set_model", "modelId": "claude-3-5-sonnet"})
    assert set_model_res["success"] is True
    assert bridge.state["model"] == "claude-3-5-sonnet"

    # 4. Stop engine cleanly
    bridge.stop()
    assert bridge.is_running is False
    assert any(e["type"] == "session_stopped" for e in events)


def test_e2e_pi_bridge_operational_mode_restrictions(pi_workspace: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Verifies that 3-tier operational mode rules strictly limit advertised models."""
    bridge = PiBridge(repo_root=pi_workspace)

    # Mode 1: offline-only
    monkeypatch.setenv("OPERATIONAL_MODE", "offline-only")
    res1 = bridge.send_command({"type": "get_available_models"})
    models1 = [m["modelId"] for m in res1["data"]["models"]]
    assert "local-gguf" in models1
    assert not any("claude" in m for m in models1)
    assert not any("llama" in m for m in models1)

    # Mode 2: offline+cloudflare-wiki
    monkeypatch.setenv("OPERATIONAL_MODE", "offline+cloudflare-wiki")
    res2 = bridge.send_command({"type": "get_available_models"})
    models2 = [m["modelId"] for m in res2["data"]["models"]]
    assert "local-gguf" in models2
    assert "@cf/meta/llama-3.1-8b-instruct-fp8-fast" in models2
    assert not any("claude" in m for m in models2)

    # Mode 3: full
    monkeypatch.setenv("OPERATIONAL_MODE", "full")
    res3 = bridge.send_command({"type": "get_available_models"})
    models3 = [m["modelId"] for m in res3["data"]["models"]]
    assert "local-gguf" in models3
    assert "@cf/meta/llama-3.1-8b-instruct-fp8-fast" in models3
    assert "claude-3-5-sonnet" in models3
    assert "gpt-4o" in models3


def test_e2e_pi_react_workflow_get_file_and_followup(pi_workspace: pathlib.Path):
    """Tests multi-turn ReACT reasoning loop executing 'get' tool on knowledgebase document."""
    bridge = PiBridge(repo_root=pi_workspace)
    captured_events = []
    bridge.add_event_listener(lambda e: captured_events.append(e))

    # Turn 1: Goal requiring file reading
    turn1_res = bridge.execute_goal("Please read file corpus/notes/quantum_computing.md")
    assert turn1_res["status"] == "completed"
    assert len(turn1_res["tool_calls"]) == 1
    assert turn1_res["tool_calls"][0]["tool"] == "get"
    assert "Surface codes demonstrate threshold fault tolerance" in turn1_res["response"]

    # Verify event stream captured the ReACT thought and tool execution sequence
    event_types = [e["type"] for e in captured_events]
    assert "message_start" in event_types
    assert "thinking_delta" in event_types
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert "turn_end" in event_types

    # Turn 2: Follow-up conversational synthesis
    turn2_res = bridge.execute_goal("Summarize our key findings on fault tolerance so far.")
    assert turn2_res["status"] == "completed"
    messages = bridge.get_messages()
    assert len(messages) >= 4  # 2 user messages + 2 assistant responses


def test_e2e_pi_react_tool_failure_recovery(pi_workspace: pathlib.Path):
    """Tests that missing files or tool errors are handled gracefully without crashing bridge."""
    bridge = PiBridge(repo_root=pi_workspace)
    
    # Query non-existent document
    res = bridge.execute_goal("read file corpus/notes/non_existent_document.md")
    assert res["status"] == "completed"
    # Agent acknowledges file not found rather than crashing
    assert "not found" in res["response"].lower() or "could not read" in res["response"].lower()

    # Engine remains healthy and responsive for next command
    state = bridge.get_state()
    assert state["success"] is True
    assert state["data"]["isStreaming"] is False
