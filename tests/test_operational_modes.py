"""Tests for 3-Tier Operational Modes and Control Plane Endpoints."""

import json
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import pytest

from control_plane.server import make_control_plane_handler
from control_plane.pi_bridge import PiBridge
from sync.cloudflare_sync import CloudflareSyncManager


@pytest.fixture
def test_server(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "test.md").write_text("# Test\nContent", encoding="utf-8")
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<h1>QMD</h1>", encoding="utf-8")
    (tmp_path / ".env").write_text("OPERATIONAL_MODE=full\n", encoding="utf-8")
    
    bridge = PiBridge(repo_root=tmp_path)
    sync = CloudflareSyncManager()
    
    handler = make_control_plane_handler(
        repo_root=tmp_path,
        static_dir=static_dir,
        pi_bridge_inst=bridge,
        sync_manager_inst=sync,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    
    server.shutdown()
    bridge.stop()


def test_operational_mode_get_and_post(test_server):
    # 1. GET operational mode
    with urllib.request.urlopen(f"{test_server}/api/engine/operational-mode") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["operational_mode"] == "full"
        assert len(data["modes"]) == 3

    # 2. POST invalid mode -> 400
    req = urllib.request.Request(
        f"{test_server}/api/engine/operational-mode",
        data=json.dumps({"mode": "invalid-mode"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        assert False, "Should have returned 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400

    # 3. POST valid mode -> 200
    req = urllib.request.Request(
        f"{test_server}/api/engine/operational-mode",
        data=json.dumps({"mode": "offline-only"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res["operational_mode"] == "offline-only"


def test_sync_endpoints(test_server):
    # 1. GET sync status
    with urllib.request.urlopen(f"{test_server}/api/sync/status") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "operational_mode" in data

    # 2. POST sync trigger
    req = urllib.request.Request(
        f"{test_server}/api/sync/trigger",
        data=json.dumps({"message": "Test trigger"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert "mode" in res

    # 3. GET sync history
    with urllib.request.urlopen(f"{test_server}/api/sync/history") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "history" in data


def test_pi_endpoints(test_server):
    # 1. GET pi status
    with urllib.request.urlopen(f"{test_server}/api/pi/status") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["is_running"] is True
        assert "sessionId" in data["state"]

    # 2. POST pi goal
    req = urllib.request.Request(
        f"{test_server}/api/pi/goal",
        data=json.dumps({"prompt": "status"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res["status"] == "completed"

    # 3. GET pi events
    with urllib.request.urlopen(f"{test_server}/api/pi/events?since=0") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert len(data["events"]) > 0
