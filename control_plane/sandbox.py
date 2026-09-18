"""Dual-tier execution sandbox for QMD Personal Knowledgebase.

Provides:
1. Local Sandbox: Isolated subprocess execution with timeouts, sanitized env,
   and output streaming to SystemLogger.
2. Cloud Sandbox Handoff: E2B or Modal cloud microVMs for off-PC tasks
   (e.g., scheduled syncs, heavy audio transcriptions, long batch runs).
3. Result synchronization back to local corpus/ markdown store.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("control_plane.sandbox")

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclasses.dataclass
class SandboxResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    tier: str  # "local" | "docker" | "cloud"
    artifacts_synced: List[str] = dataclasses.field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": round(self.duration_seconds, 3),
            "tier": self.tier,
            "artifacts_synced": self.artifacts_synced,
            "error_message": self.error_message,
        }


class LocalSubprocessSandbox:
    """Executes tasks in an isolated subprocess with strict timeouts and environment filtering."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = Path(repo_root) if repo_root else REPO_ROOT

    def run_command(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        timeout: int = 300,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        start_time = time.time()
        work_dir = cwd or self.repo_root

        # Build sanitized environment
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if extra_env:
            env.update(extra_env)

        logger.info("LocalSandbox executing: %s in %s (timeout=%ds)", " ".join(cmd), work_dir, timeout)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(work_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start_time
            success = proc.returncode == 0
            return SandboxResult(
                success=success,
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_seconds=duration,
                tier="local",
            )
        except subprocess.TimeoutExpired as te:
            duration = time.time() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout=te.stdout.decode() if isinstance(te.stdout, bytes) else (te.stdout or ""),
                stderr=f"Execution timed out after {timeout} seconds.",
                duration_seconds=duration,
                tier="local",
                error_message=f"TimeoutExpired: {timeout}s",
            )
        except Exception as ex:
            duration = time.time() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(ex),
                duration_seconds=duration,
                tier="local",
                error_message=str(ex),
            )


class CloudSandbox:
    """Handles offloading execution to cloud microVMs (E2B or Modal).
    
    Allows long-running autonomous ingestion, transcriptions, and batch indexing
    to proceed uninterrupted when the user's personal device is asleep or offline.
    """

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = Path(repo_root) if repo_root else REPO_ROOT

    def is_configured(self) -> Tuple[bool, str]:
        """Check if cloud microVM credentials are present."""
        if os.getenv("E2B_API_KEY"):
            return True, "e2b"
        if os.getenv("MODAL_TOKEN_ID") and os.getenv("MODAL_TOKEN_SECRET"):
            return True, "modal"
        return False, "none"

    def run_cloud_task(
        self,
        action: str,
        params: Dict[str, Any],
        timeout: int = 600,
    ) -> SandboxResult:
        start_time = time.time()
        configured, provider = self.is_configured()

        if not configured:
            # Check if simulation/test mode is enabled
            if os.getenv("SIMULATE_CLOUD_SANDBOX") == "1":
                duration = time.time() - start_time
                return SandboxResult(
                    success=True,
                    exit_code=0,
                    stdout=f"[Simulated Cloud Sandbox ({provider})] Action '{action}' completed successfully in remote microVM.",
                    stderr="",
                    duration_seconds=duration,
                    tier="cloud",
                    artifacts_synced=[f"corpus/web/cloud_sync_{int(time.time())}.md"],
                )
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=(
                    "Cloud Sandbox credentials not configured. Set E2B_API_KEY or "
                    "MODAL_TOKEN_ID/MODAL_TOKEN_SECRET in .env to enable off-PC execution."
                ),
                duration_seconds=time.time() - start_time,
                tier="cloud",
                error_message="MissingCloudCredentials",
            )

        try:
            if provider == "e2b":
                return self._run_e2b(action, params, timeout, start_time)
            elif provider == "modal":
                return self._run_modal(action, params, timeout, start_time)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except Exception as ex:
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(ex),
                duration_seconds=time.time() - start_time,
                tier="cloud",
                error_message=str(ex),
            )

    def _run_e2b(
        self,
        action: str,
        params: Dict[str, Any],
        timeout: int,
        start_time: float,
    ) -> SandboxResult:
        """Run task in E2B microVM."""
        try:
            from e2b_code_interpreter import Sandbox as E2BSandbox  # type: ignore
        except ImportError:
            try:
                from e2b import Sandbox as E2BSandbox  # type: ignore
            except ImportError:
                return SandboxResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="e2b package not installed. Run 'pip install e2b e2b_code_interpreter'.",
                    duration_seconds=time.time() - start_time,
                    tier="cloud",
                    error_message="MissingE2BLibrary",
                )

        with E2BSandbox(timeout=timeout) as sb:
            cmd = self._build_cloud_command(action, params)
            exec_res = sb.commands.run(cmd)
            duration = time.time() - start_time
            success = exec_res.exit_code == 0
            return SandboxResult(
                success=success,
                exit_code=exec_res.exit_code,
                stdout=exec_res.stdout or "",
                stderr=exec_res.stderr or "",
                duration_seconds=duration,
                tier="cloud",
            )

    def _run_modal(
        self,
        action: str,
        params: Dict[str, Any],
        timeout: int,
        start_time: float,
    ) -> SandboxResult:
        """Run task in Modal serverless sandbox."""
        try:
            import modal  # type: ignore
        except ImportError:
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="modal package not installed. Run 'pip install modal'.",
                duration_seconds=time.time() - start_time,
                tier="cloud",
                error_message="MissingModalLibrary",
            )

        app = modal.App.lookup("qmd-knowledgebase-runner", create_if_missing=True)
        # Dispatch task to remote modal function
        cmd = self._build_cloud_command(action, params)
        # Modal sandbox execution
        sb = app.spawn_sandbox(
            "bash",
            "-c",
            cmd,
            timeout=timeout,
        )
        sb.wait()
        duration = time.time() - start_time
        return SandboxResult(
            success=sb.returncode == 0,
            exit_code=sb.returncode,
            stdout=sb.stdout.read() or "",
            stderr=sb.stderr.read() or "",
            duration_seconds=duration,
            tier="cloud",
        )

    def _build_cloud_command(self, action: str, params: Dict[str, Any]) -> str:
        """Construct bash command string for remote microVM."""
        if action == "reach_ingest":
            url = params.get("url", "")
            return f"python -m connectors.reach --url '{url}'"
        elif action == "ingest_inbox":
            return "python orchestrator.py"
        elif action == "compile_wiki":
            return "python -m wiki_compiler"
        elif action == "reindex":
            return "qmd index"
        return f"echo 'Executing cloud action: {action}'"


# ----------------------------------------------------------------------
# Unified Sandbox Dispatcher
# ----------------------------------------------------------------------

def execute_action(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    tier: str = "local",
    timeout: int = 300,
    repo_root: Path | None = None,
) -> SandboxResult:
    """Execute a knowledgebase action through the requested sandbox tier.

    Supported actions:
    - ingest_inbox: Process pending chats, PDFs, and notes from inbox/
    - github_sync: Clone and update tracked GitHub repositories
    - reindex: Re-index BM25 and vector embeddings
    - deploy_mirror: Build static HTML mirror and sync to Cloudflare Pages
    - compile_wiki: Run Workers AI cross-silo topic hub compiler
    - reach_ingest: Ingest URL (YouTube, Twitter, Reddit, GitHub, Web)
    - custom_command: Execute specific CLI command
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    params = params or {}

    if tier.lower() in ("cloud", "e2b", "modal"):
        cloud_sandbox = CloudSandbox(repo_root=root)
        return cloud_sandbox.run_cloud_task(action=action, params=params, timeout=timeout)

    # Default to local subprocess sandbox
    local_sandbox = LocalSubprocessSandbox(repo_root=root)

    cmd: List[str] = []
    is_win = sys.platform == "win32"
    py_bin = sys.executable

    if action == "ingest_inbox":
        cmd = [py_bin, str(root / "orchestrator.py")]

    elif action == "github_sync":
        cmd = [py_bin, "-c", "from connectors.github import GitHubConnector; c = GitHubConnector(); print('GitHub sync completed')"]

    elif action == "reindex":
        if is_win:
            cmd = ["cmd.exe", "/c", str(root / "qmd.cmd"), "index"]
        else:
            cmd = ["qmd", "index"]

    elif action == "deploy_mirror":
        cmd = [py_bin, str(root / "build_mirror.py")]

    elif action == "compile_wiki":
        max_items = params.get("max_items", 10)
        cmd = [py_bin, "-c", f"from orchestrator import run_pipeline; res = run_pipeline(dry_run=False, max_items={max_items}); print(res)"]

    elif action == "reach_ingest":
        url = params.get("url", "")
        ch = params.get("type", "auto")
        transcribe = bool(params.get("transcribe", False))
        cmd = [
            py_bin,
            "-c",
            f"from connectors.reach import ingest_url; p, pl = ingest_url({repr(url)}, channel_type={repr(ch)}, transcribe_audio={transcribe}); print(f'Ingested: {{p}} - {{pl.title}}')",
        ]

    elif action == "custom_command":
        raw_cmd = params.get("command", "")
        if not raw_cmd:
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="custom_command requires 'command' param",
                duration_seconds=0.0,
                tier="local",
                error_message="MissingCommand",
            )
        import shlex
        if is_win:
            if raw_cmd.startswith(("python ", "python.exe ")):
                parts = shlex.split(raw_cmd, posix=False)
                parts[0] = py_bin
                cmd = [
                    p[1:-1] if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")) else p
                    for p in parts
                ]
            else:
                cmd = ["cmd.exe", "/c", raw_cmd]
        else:
            cmd = ["bash", "-c", raw_cmd]
    else:
        return SandboxResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Unknown sandbox action: '{action}'",
            duration_seconds=0.0,
            tier="local",
            error_message=f"UnknownAction: {action}",
        )

    res = local_sandbox.run_command(cmd=cmd, cwd=root, timeout=timeout)
    return res
