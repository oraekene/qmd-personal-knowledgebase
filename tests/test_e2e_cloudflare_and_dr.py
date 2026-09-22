"""E2E Test Suite 5: Cloudflare Sync, Git Versioning, R2 Storage & Disaster Recovery.

Tests end-to-end cloud and disaster recovery subsystems:
- Cloudflare Artifacts edge git versioning, commits, and history log
- Disaster Recovery: Rollback / revert of corpus to historical commits
- Cloudflare R2 object storage uploads and SHA256 integrity verification
- CloudflareSyncManager operational mode gating (offline-only vs full)
- Static mirror build: token prefixing, llms.txt generation, and secret protection
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from scripts.build_mirror import MirrorToken, build_mirror
from sync.cloudflare_sync import (
    CloudflareArtifactsClient,
    CloudflareR2Client,
    CloudflareSyncManager,
    compute_sha256,
)


@pytest.fixture
def sync_corpus(tmp_path: pathlib.Path):
    """Sets up an isolated test corpus directory with documents."""
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    notes_dir = corpus / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    doc1 = notes_dir / "recovery_plan.md"
    doc1.write_text(
        "---\ntitle: Recovery Plan\nsilo: notes\n---\n# Version 1.0 Initial Stable Architecture\n",
        encoding="utf-8",
    )
    return corpus


def test_e2e_artifacts_git_commit_and_history(sync_corpus: pathlib.Path):
    """Verifies automated git repo initialization, atomic commit creation, and history parsing."""
    client = CloudflareArtifactsClient()

    # 1. First commit
    res1 = client.push_directory(sync_corpus, commit_message="Initial baseline commit")
    assert res1["status"] == "success"
    assert res1["commit"] != "unknown"
    commit1 = res1["commit"]

    # 2. Add second file and commit
    doc2 = sync_corpus / "notes" / "incident_report.md"
    doc2.write_text("# Incident report 2026-09-22\nAll systems operational.\n", encoding="utf-8")

    res2 = client.push_directory(sync_corpus, commit_message="Second incremental commit")
    assert res2["status"] == "success"
    commit2 = res2["commit"]
    assert commit1 != commit2

    # 3. Retrieve history
    history = client.get_history(sync_corpus, limit=10)
    assert len(history) >= 2
    assert history[0]["commit"] == commit2
    assert history[0]["message"] == "Second incremental commit"
    assert history[1]["commit"] == commit1
    assert history[1]["message"] == "Initial baseline commit"


def test_e2e_disaster_recovery_rollback(sync_corpus: pathlib.Path):
    """Verifies that reverting to a prior commit cleanly restores corrupted corpus documents."""
    client = CloudflareArtifactsClient()
    target_file = sync_corpus / "notes" / "recovery_plan.md"

    # 1. Record baseline state
    res1 = client.push_directory(sync_corpus, commit_message="Baseline commit v1")
    v1_commit = res1["commit"]
    assert "Version 1.0 Initial Stable Architecture" in target_file.read_text(encoding="utf-8")

    # 2. Introduce corrupt/unwanted change
    target_file.write_text("# Corrupted Content by accidental overwrite\nMALFORMED DATA\n", encoding="utf-8")
    res2 = client.push_directory(sync_corpus, commit_message="Corrupted state commit v2")
    assert res2["status"] == "success"
    assert "MALFORMED DATA" in target_file.read_text(encoding="utf-8")

    # 3. Execute Disaster Recovery Rollback to v1 commit
    revert_res = client.revert_commit(sync_corpus, v1_commit)
    assert revert_res["status"] == "reverted"
    assert revert_res["target_commit"] == v1_commit

    # 4. Verify file content is completely restored
    restored_text = target_file.read_text(encoding="utf-8")
    assert "Version 1.0 Initial Stable Architecture" in restored_text
    assert "MALFORMED DATA" not in restored_text


def test_e2e_r2_client_file_upload_and_sha256(tmp_path: pathlib.Path):
    """Verifies R2 object storage upload, mock fallback, and SHA256 integrity calculation."""
    r2_client = CloudflareR2Client(bucket_name="test-corpus-bucket")

    test_db = tmp_path / "test_index.db"
    test_db.write_bytes(b"SQLite format 3\x00\x10\x00\x01\x01\x00@  \x00\x00\x00\x01" + b"A" * 1024)

    expected_sha = compute_sha256(test_db)
    assert len(expected_sha) == 64

    # Upload file
    upload_res = r2_client.upload_file(test_db, "snapshots/test_index.db")
    assert upload_res["status"] in ("uploaded", "mock_uploaded", "simulated")
    assert upload_res["key"] == "snapshots/test_index.db"
    assert upload_res["size_bytes"] == test_db.stat().st_size


def test_e2e_sync_manager_operational_mode_gating(sync_corpus: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Verifies that CloudflareSyncManager strictly adheres to operational mode policies."""
    manager = CloudflareSyncManager()

    # Blocked in offline-only mode
    monkeypatch.setenv("OPERATIONAL_MODE", "offline-only")
    res_blocked = manager.sync_all(corpus_dir=sync_corpus)
    assert res_blocked["status"] == "blocked"
    assert "blocked by operational mode" in res_blocked["message"]

    # Allowed in full mode
    monkeypatch.setenv("OPERATIONAL_MODE", "full")
    res_allowed = manager.sync_all(corpus_dir=sync_corpus, commit_message="Full mode automated sync")
    assert "artifacts" in res_allowed
    assert res_allowed["artifacts"]["status"] == "success"

    # Status summary reflects live environment
    status = manager.get_status(corpus_dir=sync_corpus)
    assert status["operational_mode"] == "full"
    assert status["cloud_sync_enabled"] is True
    assert status["latest_commit"] is not None


def test_e2e_static_mirror_build_and_token_protection(sync_corpus: pathlib.Path, tmp_path: pathlib.Path):
    """Verifies static mirror distribution build, secret token hiding at root, and llms.txt creation."""
    dist_dir = tmp_path / "dist"
    test_token = "0123456789abcdef0123456789abcdef"

    # 1. Build static mirror
    out_path = build_mirror(
        corpus=sync_corpus,
        dist=dist_dir,
        token=test_token,
        host="https://qmd-mirror.pages.dev",
    )
    assert out_path.exists()

    # 2. Verify root llms.txt does NOT contain the secret token (prevents token leakage)
    root_llms = (dist_dir / "llms.txt").read_text(encoding="utf-8")
    assert test_token not in root_llms
    assert "Private Knowledgebase" in root_llms

    # 3. Verify tokenized directory contains full mirror and tokenized llms.txt
    token_dir = dist_dir / test_token
    assert token_dir.exists()
    assert (token_dir / "notes" / "recovery_plan.md").exists()

    token_llms = (token_dir / "llms.txt").read_text(encoding="utf-8")
    assert test_token in token_llms
    assert "https://qmd-mirror.pages.dev/" + test_token in token_llms

    # 4. Verify 404.html prevents SPA leakage
    assert (dist_dir / "404.html").exists()
