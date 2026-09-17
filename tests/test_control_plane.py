"""Unit tests for the Web Control Plane and Dashboard endpoints."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from control_plane.server import (
    check_port_listening,
    get_corpus_stats,
    get_inbox_stats,
    read_env_dict,
    write_env_dict,
    TaskRunner,
    make_control_plane_handler,
)


def test_check_port_listening():
    # Test checking an unopened high port
    assert check_port_listening("127.0.0.1", 59999) is False


def test_corpus_stats(tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "notes").mkdir(parents=True)
    (corpus / "wiki").mkdir(parents=True)
    (corpus / "notes" / "n1.md").write_text("note 1")
    (corpus / "wiki" / "w1.md").write_text("wiki 1")
    (corpus / "wiki" / "w2.md").write_text("wiki 2")

    stats = get_corpus_stats(corpus)
    assert stats["notes"] == 1
    assert stats["wiki"] == 2
    assert stats["github"] == 0
    assert stats["total"] == 3


def test_inbox_stats(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "chats").mkdir(parents=True)
    (inbox / "pdfs").mkdir(parents=True)
    (inbox / "chats" / "claude.zip").write_text("zip")
    (inbox / "test.zip").write_text("zip")
    (inbox / "pdfs" / "doc.pdf").write_text("pdf")

    stats = get_inbox_stats(inbox)
    assert stats["chats"] == 2
    assert stats["pdfs"] == 1
    assert stats["total"] == 3


def test_env_read_write(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_KEY=initial_value\nANOTHER_KEY=123\n")

    cfg = read_env_dict(env_file)
    assert cfg["TEST_KEY"] == "initial_value"
    assert cfg["ANOTHER_KEY"] == "123"

    write_env_dict(env_file, {"TEST_KEY": "updated_value", "NEW_KEY": "new_val"})
    updated = read_env_dict(env_file)
    assert updated["TEST_KEY"] == "updated_value"
    assert updated["ANOTHER_KEY"] == "123"
    assert updated["NEW_KEY"] == "new_val"


def test_task_runner_status(tmp_path: Path):
    runner = TaskRunner(tmp_path)
    status = runner.get_status()
    assert status["running"] is False
    assert status["action"] == ""
    assert status["exit_code"] is None
    assert runner.is_active() is False


def test_control_plane_http_server(tmp_path: Path):
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request
    import urllib.error

    # Create dummy static and corpus dirs
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>Control Plane</h1>", encoding="utf-8")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_PROP=alpha\n")

    handler_class = make_control_plane_handler(tmp_path, static_dir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    port = server.server_port

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        # 1. GET /index.html
        with urllib.request.urlopen(f"{base_url}/") as resp:
            assert resp.status == 200
            assert "Control Plane" in resp.read().decode()

        # 2. GET /api/status
        with urllib.request.urlopen(f"{base_url}/api/status") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert "services" in data
            assert "corpus" in data
            assert "inbox" in data

        # 3. GET /api/config
        with urllib.request.urlopen(f"{base_url}/api/config") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["config"]["TEST_PROP"] == "alpha"

        # 4. POST /api/config
        req = urllib.request.Request(
            f"{base_url}/api/config",
            data=json.dumps({"updates": {"TEST_PROP": "beta", "NEW_PARAM": "100"}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "saved"

        updated_env = read_env_dict(env_file)
        assert updated_env["TEST_PROP"] == "beta"
        assert updated_env["NEW_PARAM"] == "100"

        # 5. POST /api/upload (ZIP upload)
        zip_req = urllib.request.Request(
            f"{base_url}/api/upload",
            data=b"dummy_zip_content",
            headers={"Content-Type": "application/octet-stream", "X-Filename": "claude_export.zip"},
            method="POST",
        )
        with urllib.request.urlopen(zip_req) as resp:
            assert resp.status == 201
            data = json.loads(resp.read().decode())
            assert data["filename"] == "claude_export.zip"
            assert "chats" in data["target_dir"]

        uploaded_zip = tmp_path / "inbox" / "chats" / "claude_export.zip"
        assert uploaded_zip.exists()
        assert uploaded_zip.read_bytes() == b"dummy_zip_content"

        # 5b. POST /api/upload (Simplenote ZIP upload -> inbox/notes)
        sn_req = urllib.request.Request(
            f"{base_url}/api/upload",
            data=b"dummy_simplenote_zip",
            headers={"Content-Type": "application/octet-stream", "X-Filename": "simplenote_export.zip"},
            method="POST",
        )
        with urllib.request.urlopen(sn_req) as resp:
            assert resp.status == 201
            data = json.loads(resp.read().decode())
            assert data["filename"] == "simplenote_export.zip"
            assert "notes" in data["target_dir"]

        uploaded_sn = tmp_path / "inbox" / "notes" / "simplenote_export.zip"
        assert uploaded_sn.exists()
        assert uploaded_sn.read_bytes() == b"dummy_simplenote_zip"

        # 6. GET /api/logs
        with urllib.request.urlopen(f"{base_url}/api/logs") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert "logs" in data
            assert "status" in data
            assert "entries" in data
            assert "last_id" in data

        # 7. GET /api/logs/export
        with urllib.request.urlopen(f"{base_url}/api/logs/export") as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type").startswith("text/plain")
            assert "attachment" in resp.headers.get("Content-Disposition")

    finally:
        server.shutdown()
        server.server_close()

