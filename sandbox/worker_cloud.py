"""Cloud Sandbox (Modal/E2B) Ephemeral Worker Script & Hydration Pipeline.

Provides an autonomous ephemeral container worker for off-PC tasks:
1. Hydration Pipeline: Downloads latest corpus snapshot & DBs from Cloudflare R2 / Artifacts.
2. Isolated Task Execution: Runs reach ingestion, audio transcription, wiki synthesis, or reindexing.
3. Upstream Synchronization: Commits modified/new units back to Cloudflare Artifacts & R2.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [cloud-worker] %(message)s")
logger = logging.getLogger("worker_cloud")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def get_file_snapshot(root_dir: pathlib.Path) -> Dict[str, float]:
    """Capture mtimes of all files under root_dir."""
    snapshot: Dict[str, float] = {}
    if not root_dir.exists():
        return snapshot
    for path in root_dir.rglob("*"):
        if path.is_file() and not any(part.startswith(".") for part in path.parts):
            try:
                rel = str(path.relative_to(root_dir))
                snapshot[rel] = path.stat().st_mtime
            except Exception:
                pass
    return snapshot


def find_modified_or_new(root_dir: pathlib.Path, before_snapshot: Dict[str, float]) -> List[str]:
    """Identify new or modified files compared to before_snapshot."""
    after = get_file_snapshot(root_dir)
    changed: List[str] = []
    for rel, mtime in after.items():
        if rel not in before_snapshot or mtime > before_snapshot[rel] + 0.001:
            changed.append(rel)
    return sorted(changed)


class CloudWorker:
    """Manages the lifecycle of an ephemeral cloud microVM task."""

    def __init__(self, workspace_dir: pathlib.Path | None = None, dry_run: bool = False):
        self.workspace = (workspace_dir or REPO_ROOT).resolve()
        self.dry_run = dry_run
        self.corpus_dir = self.workspace / "corpus"
        self.inbox_dir = self.workspace / "inbox"

    def hydrate(self) -> Dict[str, Any]:
        """Phase 1: Hydrate workspace from Cloudflare R2 / Artifacts edge mirror."""
        logger.info("Hydrating cloud workspace at: %s", self.workspace)
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        hydrated_files: List[str] = []
        try:
            from sync.cloudflare_sync import CloudflareSyncManager
            sync_mgr = CloudflareSyncManager(repo_root=self.workspace)
            if sync_mgr.is_configured:
                logger.info("Cloudflare credentials detected. Pulling remote corpus & assets...")
                pull_res = sync_mgr.sync_down(corpus_dir=self.corpus_dir)
                hydrated_files = pull_res.get("files", [])
            else:
                logger.info("Running in offline/local mock mode. Using local workspace state.")
        except Exception as e:
            logger.warning("Hydration from remote failed or skipped: %s", e)

        return {
            "status": "hydrated",
            "workspace": str(self.workspace),
            "files_hydrated": hydrated_files,
        }

    def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 2: Execute task inside the microVM environment."""
        logger.info("Executing cloud action '%s' with params: %s", action, params)
        start_time = time.time()
        before_snapshot = get_file_snapshot(self.corpus_dir)

        stdout = ""
        stderr = ""
        exit_code = 0
        success = True

        try:
            if action == "reach_ingest":
                url = params.get("url", "")
                if not url:
                    raise ValueError("reach_ingest requires 'url' parameter")
                from connectors.reach import ingest_url
                target_path, payload = ingest_url(
                    url=url,
                    corpus_root=self.corpus_dir,
                    transcribe_audio=params.get("transcribe", False),
                )
                stdout = json.dumps({
                    "status": "ingested",
                    "url": url,
                    "file": str(target_path),
                    "title": getattr(payload, "title", "Untitled"),
                }, indent=2)

            elif action == "ingest_inbox":
                from orchestrator import run_orchestrator
                res = run_orchestrator(repo_root=self.workspace)
                stdout = json.dumps(res, indent=2)

            elif action == "compile_wiki":
                from scripts.wiki import run_compilation
                res = run_compilation(repo_root=self.workspace)
                stdout = json.dumps(res, indent=2)

            elif action == "reindex":
                from control_plane.sandbox import get_qmd_cli_args
                cmd = get_qmd_cli_args(self.workspace) + ["update"]
                proc = subprocess.run(cmd, cwd=str(self.workspace), capture_output=True, text=True, timeout=180)
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
                success = (exit_code == 0)

            elif action == "custom_command":
                cmd_str = params.get("command", "")
                if not cmd_str:
                    raise ValueError("custom_command requires 'command' parameter")
                proc = subprocess.run(cmd_str, shell=True, cwd=str(self.workspace), capture_output=True, text=True, timeout=params.get("timeout", 300))
                stdout = proc.stdout
                stderr = proc.stderr
                exit_code = proc.returncode
                success = (exit_code == 0)

            else:
                raise ValueError(f"Unknown action: {action}")

        except Exception as ex:
            logger.error("Execution failed: %s", ex, exc_info=True)
            stderr = str(ex)
            exit_code = 1
            success = False

        duration = time.time() - start_time
        changed_artifacts = find_modified_or_new(self.corpus_dir, before_snapshot)
        logger.info("Action '%s' completed in %.2fs. Changed artifacts: %d", action, duration, len(changed_artifacts))

        return {
            "success": success,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_seconds": duration,
            "artifacts_created": changed_artifacts,
        }

    def sync_upstream(self, artifacts: List[str]) -> Dict[str, Any]:
        """Phase 3: Push changed units back to Cloudflare Artifacts & R2."""
        if self.dry_run:
            logger.info("Dry run enabled. Skipping upstream push.")
            return {"status": "dry_run", "artifacts_synced": artifacts}

        if not artifacts:
            logger.info("No artifacts created or modified. Upstream sync skipped.")
            return {"status": "no_changes", "artifacts_synced": []}

        logger.info("Pushing %d updated artifacts upstream to Cloudflare...", len(artifacts))
        try:
            from sync.cloudflare_sync import CloudflareSyncManager
            sync_mgr = CloudflareSyncManager(repo_root=self.workspace)
            if sync_mgr.is_configured:
                res = sync_mgr.sync_up(corpus_dir=self.corpus_dir, commit_message=f"Cloud Sandbox Auto-Sync ({len(artifacts)} units)")
                return {
                    "status": "synced",
                    "commit": res.get("commit"),
                    "artifacts_synced": artifacts,
                }
            else:
                logger.info("Cloudflare credentials unconfigured. Upstream commit skipped.")
                return {"status": "local_only", "artifacts_synced": artifacts}
        except Exception as e:
            logger.warning("Upstream sync encountered an error: %s", e)
            return {"status": "error", "error": str(e), "artifacts_synced": artifacts}


def run_worker(action: str, params: Dict[str, Any], workspace: pathlib.Path | None = None, dry_run: bool = False) -> Dict[str, Any]:
    """Run full 3-phase cloud worker execution."""
    worker = CloudWorker(workspace_dir=workspace, dry_run=dry_run)
    hydration_res = worker.hydrate()
    exec_res = worker.execute(action, params)
    sync_res = worker.sync_upstream(exec_res.get("artifacts_created", []))

    result = {
        "action": action,
        "success": exec_res["success"],
        "exit_code": exec_res["exit_code"],
        "stdout": exec_res["stdout"],
        "stderr": exec_res["stderr"],
        "duration_seconds": exec_res["duration_seconds"],
        "artifacts_synced": sync_res.get("artifacts_synced", []),
        "hydration": hydration_res,
        "sync": sync_res,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="QMD Ephemeral Cloud Worker")
    parser.add_argument("--action", required=True, help="Task action (reach_ingest, ingest_inbox, compile_wiki, reindex, custom_command)")
    parser.add_argument("--params", default="{}", help="JSON string of task parameters")
    parser.add_argument("--workspace", default="", help="Optional root workspace directory")
    parser.add_argument("--dry-run", action="store_true", help="Skip upstream cloud push")
    args = parser.parse_args()

    try:
        params_dict = json.loads(args.params)
    except Exception as e:
        logger.error("Failed to parse --params JSON: %s", e)
        sys.exit(1)

    ws_path = pathlib.Path(args.workspace) if args.workspace else None
    result = run_worker(action=args.action, params=params_dict, workspace=ws_path, dry_run=args.dry_run)

    # Output machine-readable JSON on stdout
    print(json.dumps(result, indent=2))
    sys.exit(result["exit_code"])


if __name__ == "__main__":
    main()
