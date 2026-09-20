"""Tests for Cloudflare Artifacts (Git Versioning) and Cloudflare R2 Sync."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sync.cloudflare_sync import (
    CloudflareArtifactsClient,
    CloudflareR2Client,
    CloudflareSyncManager,
    compute_sha256,
)


@pytest.fixture
def temp_corpus(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "note1.md").write_text("# Note 1\nContent 1", encoding="utf-8")
    (corpus / "note2.md").write_text("# Note 2\nContent 2", encoding="utf-8")
    return corpus


def test_compute_sha256(temp_corpus):
    f = temp_corpus / "note1.md"
    sha = compute_sha256(f)
    assert len(sha) == 64
    assert sha == compute_sha256(f)


def test_artifacts_client_local_git_workflow(temp_corpus):
    client = CloudflareArtifactsClient()
    
    # 1. Push directory locally
    push_res = client.push_directory(temp_corpus, commit_message="Initial commit")
    assert push_res["status"] == "success"
    assert "commit" in push_res
    commit_1 = push_res["commit"]
    
    # 2. History
    history = client.get_history(temp_corpus)
    assert len(history) >= 1
    assert history[0]["commit"] == commit_1
    assert "Initial commit" in history[0]["message"]
    
    # 3. Add change and commit again
    (temp_corpus / "note1.md").write_text("# Note 1 Modified\nChanged", encoding="utf-8")
    push_res_2 = client.push_directory(temp_corpus, commit_message="Second commit")
    commit_2 = push_res_2["commit"]
    assert commit_2 != commit_1
    
    # 4. Revert back to commit 1
    revert_res = client.revert_commit(temp_corpus, commit_1)
    assert revert_res["status"] == "reverted"
    assert (temp_corpus / "note1.md").read_text(encoding="utf-8") == "# Note 1\nContent 1"


def test_r2_client_unconfigured_and_upload(tmp_path):
    client = CloudflareR2Client()
    assert not client.is_configured
    
    db_file = tmp_path / "index.qmd.db"
    db_file.write_text("sqlite dummy data", encoding="utf-8")
    
    # Upload fallback mock
    res = client.upload_file(db_file, "snapshots/index.qmd.db")
    assert res["status"] == "mock_uploaded"
    assert res["key"] == "snapshots/index.qmd.db"
    assert res["size_bytes"] > 0
    assert len(res["sha256"]) == 64


def test_sync_manager_operational_mode_gating(temp_corpus, monkeypatch):
    manager = CloudflareSyncManager()
    
    # 1. Offline only: sync is blocked
    monkeypatch.setenv("OPERATIONAL_MODE", "offline-only")
    assert not manager.is_cloud_sync_allowed()
    res = manager.sync_all(corpus_dir=temp_corpus)
    assert res["status"] == "blocked"
    assert res["mode"] == "offline-only"
    
    # 2. Offline + Cloudflare Wiki: sync is blocked (only local + Workers AI wiki allowed)
    monkeypatch.setenv("OPERATIONAL_MODE", "offline+cloudflare-wiki")
    assert not manager.is_cloud_sync_allowed()
    res = manager.sync_all(corpus_dir=temp_corpus)
    assert res["status"] == "blocked"
    assert res["mode"] == "offline+cloudflare-wiki"
    
    # 3. Full mode: sync is permitted
    monkeypatch.setenv("OPERATIONAL_MODE", "full")
    assert manager.is_cloud_sync_allowed()
    res = manager.sync_all(corpus_dir=temp_corpus)
    assert res["mode"] == "full"
    assert "artifacts" in res
    assert res["artifacts"]["status"] == "success"


def test_sync_manager_status(temp_corpus, monkeypatch):
    monkeypatch.setenv("OPERATIONAL_MODE", "full")
    manager = CloudflareSyncManager()
    status = manager.get_status(corpus_dir=temp_corpus)
    assert status["operational_mode"] == "full"
    assert status["cloud_sync_enabled"] is True
    assert "recent_commits" in status
