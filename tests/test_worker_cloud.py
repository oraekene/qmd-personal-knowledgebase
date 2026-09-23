"""Tests for Cloud Sandbox Ephemeral Worker and Hydration Pipeline."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from sandbox.worker_cloud import (
    CloudWorker,
    find_modified_or_new,
    get_file_snapshot,
    run_worker,
)


def test_file_snapshot_and_diff(tmp_path: pathlib.Path):
    test_dir = tmp_path / "corpus"
    test_dir.mkdir(parents=True)
    f1 = test_dir / "doc1.md"
    f1.write_text("initial content", encoding="utf-8")

    snap1 = get_file_snapshot(test_dir)
    assert "doc1.md" in snap1

    # Modify f1 and create f2
    f1.write_text("updated content", encoding="utf-8")
    f2 = test_dir / "doc2.md"
    f2.write_text("new file", encoding="utf-8")

    diff = find_modified_or_new(test_dir, snap1)
    assert "doc2.md" in diff


def test_cloud_worker_hydrate(tmp_path: pathlib.Path):
    worker = CloudWorker(workspace_dir=tmp_path)
    res = worker.hydrate()
    assert res["status"] == "hydrated"
    assert (tmp_path / "corpus").exists()
    assert (tmp_path / "inbox").exists()


def test_cloud_worker_execute_custom_command(tmp_path: pathlib.Path):
    worker = CloudWorker(workspace_dir=tmp_path)
    worker.hydrate()

    res = worker.execute("custom_command", {"command": f"{sys.executable} -c \"print('worker hello')\""})
    assert res["success"] is True
    assert res["exit_code"] == 0
    assert "worker hello" in res["stdout"]


def test_cloud_worker_execute_reach_ingest_mocked(tmp_path: pathlib.Path):
    worker = CloudWorker(workspace_dir=tmp_path)
    worker.hydrate()

    target_file = tmp_path / "corpus" / "web" / "test.md"
    mock_payload = MagicMock()
    mock_payload.title = "Test Title"

    def mock_ingest(url, corpus_root, transcribe_audio=False):
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("# Test Title", encoding="utf-8")
        return target_file, mock_payload

    with patch("connectors.reach.ingest_url", side_effect=mock_ingest):
        res = worker.execute("reach_ingest", {"url": "https://example.com/test"})
        assert res["success"] is True
        assert res["exit_code"] == 0
        assert any("test.md" in a for a in res["artifacts_created"])


def test_cloud_worker_execute_unknown_action(tmp_path: pathlib.Path):
    worker = CloudWorker(workspace_dir=tmp_path)
    res = worker.execute("unknown_teleportation", {})
    assert res["success"] is False
    assert res["exit_code"] == 1
    assert "Unknown action" in res["stderr"]


def test_cloud_worker_sync_upstream_dry_run(tmp_path: pathlib.Path):
    worker = CloudWorker(workspace_dir=tmp_path, dry_run=True)
    res = worker.sync_upstream(["corpus/notes/idea.md"])
    assert res["status"] == "dry_run"
    assert res["artifacts_synced"] == ["corpus/notes/idea.md"]


def test_cloud_worker_sync_upstream_with_changes(tmp_path: pathlib.Path):
    worker = CloudWorker(workspace_dir=tmp_path, dry_run=False)
    
    mock_sync_mgr = MagicMock()
    mock_sync_mgr.is_configured = True
    mock_sync_mgr.sync_up.return_value = {"status": "success", "commit": "abc1234"}

    with patch("sync.cloudflare_sync.CloudflareSyncManager", return_value=mock_sync_mgr):
        res = worker.sync_upstream(["corpus/web/test.md"])
        assert res["status"] == "synced"
        assert res["commit"] == "abc1234"
        assert "corpus/web/test.md" in res["artifacts_synced"]


def test_run_worker_full_pipeline(tmp_path: pathlib.Path):
    res = run_worker(
        action="custom_command",
        params={"command": f"{sys.executable} -c \"print('pipeline ok')\""},
        workspace=tmp_path,
        dry_run=True,
    )
    assert res["success"] is True
    assert res["action"] == "custom_command"
    assert "pipeline ok" in res["stdout"]


def test_worker_cloud_cli_invocation(tmp_path: pathlib.Path):
    cmd = [
        sys.executable,
        "-m",
        "sandbox.worker_cloud",
        "--action",
        "custom_command",
        "--params",
        json.dumps({"command": f"{sys.executable} -c \"print('cli ok')\""}),
        "--workspace",
        str(tmp_path),
        "--dry-run",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parent.parent))
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["success"] is True
    assert "cli ok" in data["stdout"]
