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

        # 8. GET /api/status contains retrieval_mode
        with urllib.request.urlopen(f"{base_url}/api/status") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["retrieval_mode"] == "cpu-only"

        # 9. POST /api/engine/mode toggles retrieval_mode
        mode_req = urllib.request.Request(
            f"{base_url}/api/engine/mode",
            data=json.dumps({"mode": "full"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(mode_req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["retrieval_mode"] == "full"
            assert "restarted" in data

        env_after_mode = read_env_dict(env_file)
        assert env_after_mode["RETRIEVAL_MODE"] == "full"

        # 10. POST /api/engine/mode with invalid mode returns 400
        bad_mode_req = urllib.request.Request(
            f"{base_url}/api/engine/mode",
            data=json.dumps({"mode": "quantum-superposition"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_mode_req)
            assert False, "Should have failed with 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400

        # 11. GET /api/search with silo parameter
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Mock search result", stderr="", returncode=0)
            with urllib.request.urlopen(f"{base_url}/api/search?q=ocr+model&silo=wiki") as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode())
                assert data["query"] == "ocr model"
                assert data["silo"] == "wiki"
                # verify subprocess called with -c wiki
                cmd = mock_run.call_args[0][0]
                assert "-c" in cmd
                assert "wiki" in cmd

        # 12. GET /api/prompts
        with urllib.request.urlopen(f"{base_url}/api/prompts") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert "soul" in data
            assert "system_prompt" in data
            assert "synthesized" in data
            assert "templates" in data
            assert any(t["name"] == "knowledge-search" for t in data["templates"])

        # 13. POST /api/prompts
        p_req = urllib.request.Request(
            f"{base_url}/api/prompts",
            data=json.dumps({"soul": "Updated Persona", "system_prompt": "Updated System Guidelines"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(p_req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "saved"

        assert (tmp_path / "SOUL.md").read_text(encoding="utf-8").strip() == "Updated Persona"
        assert (tmp_path / "SYSTEM_PROMPT.md").read_text(encoding="utf-8").strip() == "Updated System Guidelines"

        # 14. GET /api/connectors
        with urllib.request.urlopen(f"{base_url}/api/connectors") as resp:
            assert resp.status == 200
            c_data = json.loads(resp.read().decode())
            assert "reach" in c_data
            assert "channels" in c_data
            assert "youtube" in c_data["channels"]

        # 15. POST /api/connectors/reach with missing url returns 400
        bad_conn_req = urllib.request.Request(
            f"{base_url}/api/connectors/reach",
            data=json.dumps({"type": "youtube"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_conn_req)
            assert False, "Should have failed with 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400

        # 16. POST /api/connectors/reach with valid input
        with patch("connectors.reach.extract_youtube") as mock_extract:
            from connectors.sdk.base import UnitPayload
            mock_extract.return_value = UnitPayload(
                source="youtube",
                silo="web",
                source_id="youtube_test123",
                url="https://youtu.be/test123",
                title="Mocked YouTube Ingestion",
                summary="A mocked summary of the video.",
                body_markdown="# Mocked YouTube Ingestion\n\nVideo content goes here.",
            )
            good_conn_req = urllib.request.Request(
                f"{base_url}/api/connectors/reach",
                data=json.dumps({"url": "https://youtu.be/test123", "type": "youtube"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(good_conn_req) as resp:
                assert resp.status == 200
                conn_res = json.loads(resp.read().decode())
                assert conn_res["status"] == "success"
                assert conn_res["silo"] == "web"
                assert conn_res["title"] == "Mocked YouTube Ingestion"
                assert (tmp_path / "corpus" / "web" / "youtube_test123.md").exists()

        # 17. GET /api/skills
        skill_dir = tmp_path / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: Demo skill description\n---\n# Demo Skill\nInstructions here.",
            encoding="utf-8",
        )
        with urllib.request.urlopen(f"{base_url}/api/skills") as resp:
            assert resp.status == 200
            s_data = json.loads(resp.read().decode())
            assert "skills" in s_data
            assert any(s["name"] == "demo-skill" for s in s_data["skills"])

        # 18. GET /api/skills/{name}
        with urllib.request.urlopen(f"{base_url}/api/skills/demo-skill") as resp:
            assert resp.status == 200
            sk_content = json.loads(resp.read().decode())
            assert sk_content["name"] == "demo-skill"
            assert "# Demo Skill" in sk_content["content"]

        try:
            urllib.request.urlopen(f"{base_url}/api/skills/unknown-skill-xyz")
            assert False, "Should have returned 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404

        # 19. GET /api/tools
        with urllib.request.urlopen(f"{base_url}/api/tools") as resp:
            assert resp.status == 200
            t_data = json.loads(resp.read().decode())
            assert "catalog" in t_data
            assert "progressive_manifest" in t_data
            assert any(t["name"] == "search" for t in t_data["catalog"])
            assert any(t["name"] == "skills_list" for t in t_data["progressive_manifest"])

    finally:
        server.shutdown()
        server.server_close()

