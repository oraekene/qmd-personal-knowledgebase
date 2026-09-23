"""Cloudflare Artifacts (Git Versioning) & Cloudflare R2 (Object Sync) Engine.

Provides:
1. CloudflareArtifactsClient: Git-compatible edge repository management (commits, diffs, history, rollback).
2. CloudflareR2Client: S3-compatible binary object store for pre-computed .qmd.db and media assets.
3. CloudflareSyncManager: Unified 1-click sync engine with versioning and operational mode awareness.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class CloudflareArtifactsClient:
    """Manages Git-compatible Cloudflare Artifacts edge repositories."""

    def __init__(
        self,
        account_id: str | None = None,
        api_token: str | None = None,
        namespace: str = "qmd",
        repo_name: str = "corpus",
    ):
        self.account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.api_token = api_token or os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        self.namespace = namespace or os.environ.get("ARTIFACTS_NAMESPACE", "qmd").strip()
        self.repo_name = repo_name or os.environ.get("ARTIFACTS_REPO", "corpus").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.account_id and self.api_token)

    @property
    def remote_url(self) -> str:
        if not self.is_configured:
            return ""
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/artifacts/{self.namespace}/{self.repo_name}.git"

    def create_repo(self) -> Dict[str, Any]:
        """Create or verify the Artifacts repository on Cloudflare."""
        if not self.is_configured:
            return {"status": "unconfigured", "message": "Missing Cloudflare credentials"}

        endpoint = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/artifacts/{self.namespace}/repos"
        payload = {"name": self.repo_name, "description": "QMD Personal Knowledgebase Corpus"}
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(endpoint, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_token}")
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return {"status": "created", "details": res}
        except urllib.error.HTTPError as e:
            if e.code == 409:  # Already exists
                return {"status": "exists", "repo": self.repo_name}
            err = e.read().decode("utf-8", errors="replace")
            return {"status": "error", "code": e.code, "message": err}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def push_directory(self, corpus_dir: Path, commit_message: str = "Auto-sync from QMD") -> Dict[str, Any]:
        """Commit and push markdown corpus to the Cloudflare Artifacts edge repository."""
        if not corpus_dir.exists():
            return {"status": "skipped", "message": "Corpus directory does not exist"}

        # Use git CLI to record version history in a local shadow or dedicated branch
        try:
            # Check if corpus has git initialized
            git_dir = corpus_dir / ".git"
            if not git_dir.exists():
                subprocess.run(["git", "init", str(corpus_dir)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(corpus_dir), "config", "user.name", "QMD Sync"], capture_output=True)
                subprocess.run(["git", "-C", str(corpus_dir), "config", "user.email", "qmd-sync@local"], capture_output=True)

            # Add all files in corpus
            subprocess.run(["git", "-C", str(corpus_dir), "add", "."], capture_output=True)
            commit_res = subprocess.run(
                ["git", "-C", str(corpus_dir), "commit", "-m", commit_message],
                capture_output=True,
                text=True,
            )

            # Get latest commit hash
            rev_res = subprocess.run(
                ["git", "-C", str(corpus_dir), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            commit_hash = rev_res.stdout.strip() if rev_res.returncode == 0 else "unknown"

            # If remote is configured and online, push
            if self.is_configured:
                auth_url = f"https://token:{self.api_token}@api.cloudflare.com/client/v4/accounts/{self.account_id}/artifacts/{self.namespace}/{self.repo_name}.git"
                subprocess.run(
                    ["git", "-C", str(corpus_dir), "push", auth_url, "HEAD:main", "--force"],
                    capture_output=True,
                    text=True,
                )

            return {
                "status": "success",
                "commit": commit_hash,
                "message": commit_message,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.warning("Local git commit/push in corpus failed: %s", e)
            return {"status": "error", "message": str(e)}

    def get_history(self, corpus_dir: Path, limit: int = 15) -> List[Dict[str, Any]]:
        """Retrieve recent version history with commit hashes, timestamps, and messages."""
        if not corpus_dir.exists():
            return []

        try:
            cmd = ["git", "-C", str(corpus_dir), "log", f"-n{limit}", "--pretty=format:%H|%an|%ad|%s", "--date=iso"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                return []

            history = []
            for line in res.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split("|", 3)
                if len(parts) == 4:
                    history.append({
                        "commit": parts[0],
                        "author": parts[1],
                        "date": parts[2],
                        "message": parts[3],
                    })
            return history
        except Exception:
            return []

    def revert_commit(self, corpus_dir: Path, commit_hash: str) -> Dict[str, Any]:
        """Revert corpus state to a specific commit."""
        if not corpus_dir.exists():
            return {"status": "error", "message": "Corpus directory not found"}

        try:
            cmd = ["git", "-C", str(corpus_dir), "checkout", commit_hash, "--", "."]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                return {"status": "reverted", "target_commit": commit_hash}
            return {"status": "error", "message": res.stderr}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def pull_directory(self, corpus_dir: Path) -> Dict[str, Any]:
        """Pull latest changes from Cloudflare Artifacts edge repository."""
        if not corpus_dir.exists():
            corpus_dir.mkdir(parents=True, exist_ok=True)

        if not self.is_configured:
            return {"status": "unconfigured", "files": []}

        try:
            auth_url = f"https://token:{self.api_token}@api.cloudflare.com/client/v4/accounts/{self.account_id}/artifacts/{self.namespace}/{self.repo_name}.git"
            git_dir = corpus_dir / ".git"
            if not git_dir.exists():
                res = subprocess.run(["git", "clone", "--depth", "1", auth_url, str(corpus_dir)], capture_output=True, text=True)
                if res.returncode == 0:
                    return {"status": "cloned", "files": [p.name for p in corpus_dir.iterdir()]}
            else:
                res = subprocess.run(["git", "-C", str(corpus_dir), "pull", auth_url, "main"], capture_output=True, text=True)
                if res.returncode == 0:
                    return {"status": "pulled", "files": [p.name for p in corpus_dir.iterdir()]}
            return {"status": "error", "message": res.stderr, "files": []}
        except Exception as e:
            logger.warning("Remote pull failed: %s", e)
            return {"status": "error", "message": str(e), "files": []}


class CloudflareR2Client:
    """S3-compatible client for Cloudflare R2 object storage."""

    def __init__(
        self,
        account_id: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket_name: str | None = None,
    ):
        self.account_id = account_id or os.environ.get("R2_ACCOUNT_ID", os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")).strip()
        self.access_key_id = access_key_id or os.environ.get("R2_ACCESS_KEY_ID", "").strip()
        self.secret_access_key = secret_access_key or os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
        self.bucket_name = bucket_name or os.environ.get("R2_BUCKET_NAME", "qmd-knowledgebase").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.account_id and self.access_key_id and self.secret_access_key and self.bucket_name)

    @property
    def endpoint_url(self) -> str:
        if not self.account_id:
            return ""
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    def upload_file(self, local_path: Path, r2_key: str) -> Dict[str, Any]:
        """Upload a binary file or snapshot to R2."""
        if not local_path.exists():
            return {"status": "error", "message": f"File {local_path} not found"}

        if not self.is_configured:
            # Simulated local mock when unconfigured
            return {
                "status": "mock_uploaded",
                "key": r2_key,
                "size_bytes": local_path.stat().st_size,
                "sha256": compute_sha256(local_path),
            }

        try:
            # Try boto3 if installed
            import boto3  # type: ignore
            s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
            )
            s3.upload_file(str(local_path), self.bucket_name, r2_key)
            return {"status": "uploaded", "key": r2_key, "size_bytes": local_path.stat().st_size}
        except ImportError:
            # Fallback mock/simulated upload
            return {
                "status": "simulated",
                "key": r2_key,
                "size_bytes": local_path.stat().st_size,
                "message": "boto3 not installed, simulated upload complete",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def download_file(self, r2_key: str, local_path: Path) -> Dict[str, Any]:
        """Download a file from R2 to local disk."""
        if not self.is_configured:
            return {"status": "mock_downloaded", "key": r2_key, "destination": str(local_path)}

        try:
            import boto3  # type: ignore
            local_path.parent.mkdir(parents=True, exist_ok=True)
            s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
            )
            s3.download_file(self.bucket_name, r2_key, str(local_path))
            return {"status": "downloaded", "key": r2_key, "path": str(local_path)}
        except Exception as e:
            return {"status": "error", "message": str(e)}


class CloudflareSyncManager:
    """Coordinates Cloudflare Artifacts (Git Versioning) & R2 (Binary DB Sync)."""

    def __init__(
        self,
        artifacts_client: CloudflareArtifactsClient | None = None,
        r2_client: CloudflareR2Client | None = None,
        repo_root: Path | None = None,
    ):
        self.artifacts = artifacts_client or CloudflareArtifactsClient()
        self.r2 = r2_client or CloudflareR2Client()
        self.repo_root = repo_root

    @property
    def is_configured(self) -> bool:
        return self.artifacts.is_configured or self.r2.is_configured

    def get_operational_mode(self) -> str:
        """Read 3-tier operational mode from env: offline-only, offline+cloudflare-wiki, full."""
        return os.environ.get("OPERATIONAL_MODE", "full").strip().lower()

    def is_cloud_sync_allowed(self) -> bool:
        mode = self.get_operational_mode()
        return mode == "full"

    def sync_up(
        self,
        corpus_dir: Path = Path("corpus"),
        db_path: Path | None = None,
        commit_message: str = "Automated sync from QMD",
    ) -> Dict[str, Any]:
        """Alias for sync_all pushing upstream."""
        return self.sync_all(corpus_dir=corpus_dir, db_path=db_path, commit_message=commit_message)

    def sync_down(self, corpus_dir: Path = Path("corpus")) -> Dict[str, Any]:
        """Pull downstream changes from Cloudflare Artifacts edge repository."""
        if not self.is_cloud_sync_allowed():
            return {
                "status": "blocked",
                "mode": self.get_operational_mode(),
                "message": f"Cloud sync blocked by operational mode: {self.get_operational_mode()}",
                "files": [],
            }
        return self.artifacts.pull_directory(corpus_dir=corpus_dir)

    def sync_all(
        self,
        corpus_dir: Path = Path("corpus"),
        db_path: Path | None = None,
        commit_message: str = "Automated sync from QMD",
    ) -> Dict[str, Any]:
        """Perform unified sync: Git commit to Artifacts + snapshot upload to R2."""
        if not self.is_cloud_sync_allowed():
            return {
                "status": "blocked",
                "mode": self.get_operational_mode(),
                "message": f"Cloud sync blocked by operational mode: {self.get_operational_mode()}",
            }

        results: Dict[str, Any] = {"timestamp": time.time(), "mode": self.get_operational_mode()}

        # 1. Versioned text sync to Artifacts
        artifacts_res = self.artifacts.push_directory(corpus_dir, commit_message=commit_message)
        results["artifacts"] = artifacts_res

        # 2. Pre-computed .qmd.db SQLite & Vector DB upload to R2
        if db_path is None:
            # Check standard locations
            candidates = [Path(".qmd/index.db"), Path("corpus/.qmd/index.db")] + list(Path(".").glob("*.qmd.db"))
            for cand in candidates:
                if cand.exists():
                    db_path = cand
                    break

        if db_path and db_path.exists():
            r2_key = f"snapshots/{db_path.name}"
            r2_res = self.r2.upload_file(db_path, r2_key)
            results["r2_database"] = r2_res
        else:
            results["r2_database"] = {"status": "skipped", "message": "No SQLite database found to upload"}

        return results

    def get_status(self, corpus_dir: Path = Path("corpus")) -> Dict[str, Any]:
        """Get comprehensive sync, versioning, and cloud status."""
        mode = self.get_operational_mode()
        history = self.artifacts.get_history(corpus_dir, limit=5)
        return {
            "operational_mode": mode,
            "cloud_sync_enabled": self.is_cloud_sync_allowed(),
            "artifacts_configured": self.artifacts.is_configured,
            "artifacts_repo": self.artifacts.repo_name,
            "r2_configured": self.r2.is_configured,
            "r2_bucket": self.r2.bucket_name,
            "recent_commits": history,
            "latest_commit": history[0] if history else None,
        }
