"""QMD Knowledgebase Web Control Plane & Dashboard Server.

Provides a unified local web UI on port 3333 to:
- Monitor health and supervise daemons (QMD 8181, Auth Proxy 3210, Cloudflare Tunnel, Mirror)
- Trigger pipeline actions (Orchestrator, QMD Embed, Wiki Compile, Mirror Deploy, Smoke Tests)
- Stream real-time terminal execution logs to the browser
- Manage .env secrets and pipeline toggles without file hunting
- Drag-and-drop upload AI chat ZIPs and PDFs directly into inbox silos
- Test interactive BM25 / Vector search queries directly
"""

from __future__ import annotations

import collections
import html
import io
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("control_plane")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENV_PATH = REPO_ROOT / ".env"



def check_port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open and listening locally (supports IPv4 & IPv6)."""
    hosts_to_try = [host]
    if host in ("127.0.0.1", "localhost"):
        hosts_to_try = ["127.0.0.1", "::1", "localhost"]
    for h in hosts_to_try:
        try:
            with socket.create_connection((h, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            continue
    return False


def check_http_url(url: str, timeout: float = 1.5) -> bool:
    """Check if an HTTP/HTTPS URL returns an OK status."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Claude/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 204, 302, 401, 403, 405)
    except urllib.error.HTTPError as e:
        return e.code in (200, 204, 302, 401, 403, 405)
    except Exception:
        return False


def find_pids_by_port(port: int) -> List[int]:
    """Find all PIDs actively listening on a given port."""
    pids = set()
    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and "LISTENING" in parts:
                    local_addr = parts[1]
                    pid_str = parts[-1]
                    if local_addr.endswith(f":{port}") and pid_str.isdigit():
                        pids.add(int(pid_str))
        except Exception:
            pass
    return list(pids)


def kill_pid(pid: int) -> None:
    """Forcefully kill a process and its children."""
    if pid <= 0:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)
        except Exception:
            pass
    else:
        try:
            os.kill(pid, 9)
        except Exception:
            pass


class SystemLogger:
    """Centralized thread-safe logger capturing all daemons, pipelines, and server events."""

    def __init__(self, repo_root: Path, max_entries: int = 5000):
        self.repo_root = repo_root
        self.lock = threading.Lock()
        self.entries: collections.deque[Dict[str, Any]] = collections.deque(maxlen=max_entries)
        self.counter: int = 0
        self.log_file = repo_root / "logs" / "system.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, source: str, message: str, level: str = "INFO") -> None:
        message = message.rstrip()
        if not message:
            return
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            self.counter += 1
            record = {
                "id": self.counter,
                "time": now_str,
                "source": source.upper(),
                "level": level.upper(),
                "message": message,
                "raw": f"[{now_str}] [{source.upper()}] [{level.upper()}] {message}",
            }
            self.entries.append(record)
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(record["raw"] + "\n")
            except Exception:
                pass

    def get_logs(
        self, since_id: int = 0, source: Optional[str] = None, level: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self.lock:
            filtered = [e for e in self.entries if e["id"] > since_id]
            if source and source.upper() != "ALL":
                s = source.upper()
                if s == "DAEMONS":
                    filtered = [e for e in filtered if e["source"] in ("QMD", "AUTH_PROXY", "TUNNEL", "SUPERVISOR")]
                elif s == "PIPELINES":
                    filtered = [e for e in filtered if e["source"] in ("PIPELINE", "TASK")]
                else:
                    filtered = [e for e in filtered if e["source"] == s]
            if level and level.upper() != "ALL":
                l = level.upper()
                if l == "ERRORS":
                    filtered = [e for e in filtered if e["level"] in ("ERROR", "WARNING")]
                else:
                    filtered = [e for e in filtered if e["level"] == l]
            return filtered

    def get_raw_lines(self, since_id: int = 0) -> List[str]:
        return [e["raw"] for e in self.get_logs(since_id=since_id)]

    def count(self) -> int:
        with self.lock:
            return len(self.entries)


def get_corpus_stats(corpus_dir: Path) -> Dict[str, int]:
    """Count .md files across all registered silos."""
    silos = ["notes", "wiki", "github", "chats", "pdfs", "web", "twitter"]
    stats: Dict[str, int] = {}
    total = 0
    for silo in silos:
        silo_path = corpus_dir / silo
        if silo_path.exists():
            cnt = len(list(silo_path.rglob("*.md")))
        else:
            cnt = 0
        stats[silo] = cnt
        total += cnt
    stats["total"] = total
    return stats


def get_inbox_stats(inbox_dir: Path) -> Dict[str, int]:
    """Count pending files in inboxes."""
    stats = {"chats": 0, "pdfs": 0, "notes": 0, "total": 0}
    if not inbox_dir.exists():
        return stats
    chats_dir = inbox_dir / "chats"
    pdfs_dir = inbox_dir / "pdfs"
    notes_dir = inbox_dir / "notes"

    root_zips = len(list(inbox_dir.glob("*.zip")))
    chat_zips = len(list(chats_dir.glob("*.zip"))) if chats_dir.exists() else 0
    stats["chats"] = root_zips + chat_zips

    pdf_files = len(list(pdfs_dir.glob("*.pdf"))) if pdfs_dir.exists() else 0
    stats["pdfs"] = pdf_files

    notes_count = 0
    if notes_dir.exists():
        notes_count += len(list(notes_dir.glob("*.zip")))
        notes_count += len(list(notes_dir.glob("*.txt")))
        notes_count += len(list(notes_dir.glob("*.md")))
    stats["notes"] = notes_count

    stats["total"] = stats["chats"] + stats["pdfs"] + stats["notes"]
    return stats


def read_env_dict(path: Path) -> Dict[str, str]:
    """Read key-value pairs from .env."""
    if not path.exists():
        return {}
    res: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            res[k.strip()] = v.strip().strip('"').strip("'")
    return res


def write_env_dict(path: Path, updates: Dict[str, str]) -> None:
    """Update or append keys to .env safely."""
    existing_lines = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                updated_keys.add(k)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _stream_output(proc: subprocess.Popen, source: str, sys_logger: SystemLogger) -> None:
    def _reader():
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    clean = line.rstrip()
                    if clean:
                        level = "ERROR" if ("error" in clean.lower() or "exception" in clean.lower() or "fatal" in clean.lower()) else "INFO"
                        sys_logger.log(source, clean, level=level)
        except Exception as e:
            sys_logger.log(source, f"Stream reader exception: {e}", level="ERROR")

    t = threading.Thread(target=_reader, daemon=True)
    t.start()


class TaskRunner:
    """Manages background CLI pipelines and captures output logs."""

    def __init__(self, repo_root: Path, logger: Optional[SystemLogger] = None):
        self.repo_root = repo_root
        self.logger = logger or SystemLogger(repo_root)
        self.lock = threading.Lock()
        self.current_process: Optional[subprocess.Popen] = None
        self.current_action: str = ""
        self.is_running: bool = False
        self.exit_code: Optional[int] = None
        self.start_time: float = 0.0
        self.logs: collections.deque[str] = collections.deque(maxlen=3000)

    def is_active(self) -> bool:
        with self.lock:
            return self.is_running

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = time.time() - self.start_time if self.is_running else 0.0
            return {
                "running": self.is_running,
                "action": self.current_action,
                "exit_code": self.exit_code,
                "elapsed_seconds": round(elapsed, 1),
                "log_count": len(self.logs),
            }

    def get_logs(self, since_index: int = 0) -> List[str]:
        with self.lock:
            logs_list = list(self.logs)
            if since_index < len(logs_list):
                return logs_list[since_index:]
            return []

    def stop_current(self) -> bool:
        with self.lock:
            if self.is_running and self.current_process:
                try:
                    self.current_process.terminate()
                    time.sleep(0.5)
                    if self.current_process.poll() is None:
                        self.current_process.kill()
                    self.logs.append("[Control Plane] Process terminated by user.")
                    self.logger.log("PIPELINE", "Process terminated by user.", level="WARNING")
                    self.is_running = False
                    return True
                except Exception as e:
                    self.logs.append(f"[Control Plane] Error terminating: {e}")
                    self.logger.log("PIPELINE", f"Error terminating: {e}", level="ERROR")
            return False

    def trigger(self, action: str) -> bool:
        with self.lock:
            if self.is_running:
                return False

            cmd: List[str] = []
            use_shell = sys.platform == "win32"

            if action == "orchestrator":
                cmd = [sys.executable, "orchestrator.py"]
            elif action == "reindex":
                if sys.platform == "win32":
                    cmd = ["cmd.exe", "/c", str(self.repo_root / "qmd.cmd"), "update"]
                else:
                    cmd = ["qmd", "update"]
            elif action == "embed":
                if sys.platform == "win32":
                    cmd = ["cmd.exe", "/c", str(self.repo_root / "qmd.cmd"), "embed"]
                else:
                    cmd = ["qmd", "embed"]
            elif action == "wiki":
                cmd = [sys.executable, "-m", "scripts.wiki"]
            elif action == "mirror":
                cmd = [sys.executable, "scripts/build_mirror.py"]
            elif action == "smoke":
                cmd = [sys.executable, "scripts/acceptance.py", "--live"]
            elif action == "github":
                cmd = [sys.executable, "github_extractor_v2.py", "--sources", "owned,forks,starred"]
            else:
                return False

            self.current_action = action
            self.is_running = True
            self.exit_code = None
            self.start_time = time.time()
            self.logs.clear()
            msg = f"Starting action '{action}': {' '.join(cmd)}"
            self.logs.append(f"[Control Plane] {msg}")
            self.logger.log("PIPELINE", msg)

            def _worker():
                try:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(self.repo_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        shell=use_shell,
                    )
                    with self.lock:
                        self.current_process = proc

                    for line in iter(proc.stdout.readline, ""):
                        clean_line = line.rstrip()
                        if clean_line:
                            with self.lock:
                                self.logs.append(clean_line)
                            level = "ERROR" if "error" in clean_line.lower() else "INFO"
                            self.logger.log("PIPELINE", clean_line, level=level)

                    proc.wait()
                    with self.lock:
                        self.exit_code = proc.returncode
                        self.is_running = False
                        status_str = "SUCCESS" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
                        self.logs.append(f"[Control Plane] Action '{action}' finished: {status_str}")
                    level = "INFO" if proc.returncode == 0 else "ERROR"
                    self.logger.log("PIPELINE", f"Action '{action}' finished: {status_str}", level=level)
                except Exception as e:
                    with self.lock:
                        self.exit_code = -1
                        self.is_running = False
                        self.logs.append(f"[Control Plane] Exception running action '{action}': {e}")
                    self.logger.log("PIPELINE", f"Exception running action '{action}': {e}", level="ERROR")

            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            return True


class DaemonSupervisor:
    """Tracks, controls, and streams logs from background daemons."""

    def __init__(self, repo_root: Path, logger: Optional[SystemLogger] = None):
        self.repo_root = repo_root
        self.logger = logger or SystemLogger(repo_root)
        self.processes: Dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()

    def start_daemon(self, name: str) -> Dict[str, Any]:
        with self.lock:
            env = os.environ.copy()
            env_file_dict = read_env_dict(self.repo_root / ".env")
            env.update(env_file_dict)
            env["PYTHONUNBUFFERED"] = "1"
            retrieval_mode = env.get("RETRIEVAL_MODE", "cpu-only").lower()
            env["RETRIEVAL_MODE"] = retrieval_mode
            env["QMD_RETRIEVAL_MODE"] = retrieval_mode
            use_shell = sys.platform == "win32"

            if name == "qmd":
                # Clean up any stale PIDs on 8181 before launching
                for pid in find_pids_by_port(8181):
                    self.logger.log("QMD", f"Killing stale PID {pid} on port 8181 before starting", level="WARNING")
                    kill_pid(pid)
                    time.sleep(0.5)

                env["QMD_ALLOWED_ORIGINS"] = "*"
                if sys.platform == "win32":
                    cmd = ["cmd.exe", "/c", str(self.repo_root / "qmd.cmd"), "mcp", "--http", "--port", "8181", "--host", "0.0.0.0"]
                else:
                    cmd = ["node", "qmd-main/node_modules/tsx/dist/cli.mjs", "qmd-main/src/cli/qmd.ts", "mcp", "--http", "--port", "8181", "--host", "0.0.0.0"]

                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.repo_root),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                self.processes["qmd"] = proc
                _stream_output(proc, "QMD", self.logger)
                self.logger.log("QMD", f"QMD MCP Server launched (PID {proc.pid}) on port 8181")
                return {"status": "started", "name": "qmd", "pid": proc.pid}

            elif name == "auth_proxy":
                # Clean up any stale PIDs on 3210 before launching
                for pid in find_pids_by_port(3210):
                    self.logger.log("AUTH_PROXY", f"Killing stale PID {pid} on port 3210 before starting", level="WARNING")
                    kill_pid(pid)
                    time.sleep(0.5)

                cmd = [sys.executable, "-u", "-m", "auth_proxy"]
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.repo_root),
                    env=env,
                    shell=use_shell,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                self.processes["auth_proxy"] = proc
                _stream_output(proc, "AUTH_PROXY", self.logger)
                self.logger.log("AUTH_PROXY", f"Auth Proxy launched (PID {proc.pid}) on port 3210")
                return {"status": "started", "name": "auth_proxy", "pid": proc.pid}

            elif name == "tunnel":
                token = env.get("TUNNEL_TOKEN", "")
                if not token:
                    self.logger.log("TUNNEL", "TUNNEL_TOKEN not configured in .env", level="ERROR")
                    return {"status": "error", "message": "TUNNEL_TOKEN not configured in .env"}

                # Kill any existing cloudflared instances
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
                    time.sleep(0.5)

                cmd = ["cloudflared", "tunnel", "run", "--token", token]
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.repo_root),
                    env=env,
                    shell=use_shell,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                self.processes["tunnel"] = proc
                _stream_output(proc, "TUNNEL", self.logger)
                self.logger.log("TUNNEL", f"Cloudflare Tunnel launched (PID {proc.pid})")
                return {"status": "started", "name": "tunnel", "pid": proc.pid}

            return {"status": "unknown_daemon", "name": name}

    def stop_daemon(self, name: str) -> Dict[str, Any]:
        with self.lock:
            killed_pids = []
            proc = self.processes.pop(name, None)
            if proc:
                try:
                    proc.terminate()
                    time.sleep(0.5)
                    if proc.poll() is None:
                        proc.kill()
                    killed_pids.append(proc.pid)
                except Exception:
                    pass

            if name == "qmd":
                for pid in find_pids_by_port(8181):
                    kill_pid(pid)
                    killed_pids.append(pid)
            elif name == "auth_proxy":
                for pid in find_pids_by_port(3210):
                    kill_pid(pid)
                    killed_pids.append(pid)
            elif name == "tunnel":
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)

            self.logger.log("SUPERVISOR", f"Stopped daemon '{name}' (cleaned PIDs: {killed_pids})")
            return {"status": "stopped", "name": name, "killed_pids": killed_pids}

    def restart_daemon(self, name: str) -> Dict[str, Any]:
        self.stop_daemon(name)
        time.sleep(1.0)
        return self.start_daemon(name)



def make_control_plane_handler(
    repo_root: Path,
    static_dir: Path,
    logger: Optional[SystemLogger] = None,
    scheduler: Optional[Any] = None,
    pi_bridge_inst: Optional[Any] = None,
    sync_manager_inst: Optional[Any] = None,
):
    system_logger = logger or SystemLogger(repo_root)
    runner = TaskRunner(repo_root, logger=system_logger)
    supervisor = DaemonSupervisor(repo_root, logger=system_logger)

    from control_plane.scheduler import SchedulerDaemon, SchedulerStore
    scheduler_store = SchedulerStore(repo_root / "automations.json")
    scheduler_daemon = scheduler or SchedulerDaemon(
        repo_root=repo_root,
        store=scheduler_store,
        logger_func=lambda level, msg: system_logger.log("SCHEDULER", msg, level=level),
    )

    from control_plane.pi_bridge import PiBridge
    from sync.cloudflare_sync import CloudflareSyncManager

    pi_bridge = pi_bridge_inst or PiBridge(repo_root=repo_root)
    pi_bridge.start()
    sync_manager = sync_manager_inst or CloudflareSyncManager()

    pi_bridge.add_event_listener(
        lambda evt: system_logger.log("PI_AGENT", f"[{evt.get('type')}] {evt.get('tool') or evt.get('content') or evt.get('sessionId') or ''}")
    )

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(static_dir), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send_json(self, status: int, data: Dict[str, Any]) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")
            params = urllib.parse.parse_qs(parsed.query)

            if path == "/api/status":
                env_dict = read_env_dict(repo_root / ".env")
                tunnel_url = env_dict.get("TUNNEL_URL", "https://kb.parmeterai.space/mcp")
                mirror_host = env_dict.get("MIRROR_HOST", "https://qmd-mirror.pages.dev")
                retrieval_mode = env_dict.get("RETRIEVAL_MODE", "cpu-only").lower()

                qmd_ok = check_port_listening("127.0.0.1", 8181)
                proxy_ok = check_port_listening("127.0.0.1", 3210)
                tunnel_ok = check_http_url("https://kb.parmeterai.space/.well-known/oauth-authorization-server")

                mirror_token = env_dict.get("MIRROR_TOKEN", "")
                mirror_probe_url = f"{mirror_host}/llms.txt"
                mirror_ok = check_http_url(mirror_probe_url)
                mirror_user_url = f"{mirror_host}/{mirror_token}/" if mirror_token else mirror_host

                corpus_stats = get_corpus_stats(repo_root / "corpus")
                inbox_stats = get_inbox_stats(repo_root / "inbox")
                task_status = runner.get_status()

                data = {
                    "retrieval_mode": retrieval_mode,
                    "services": {
                        "qmd": {"ok": qmd_ok, "port": 8181, "name": "QMD MCP Server"},
                        "auth_proxy": {"ok": proxy_ok, "port": 3210, "name": "Auth Proxy (OAuth)"},
                        "tunnel": {"ok": tunnel_ok, "url": tunnel_url, "name": "Cloudflare Tunnel"},
                        "mirror": {"ok": mirror_ok, "url": mirror_user_url, "name": "Static Web Mirror"},
                    },
                    "corpus": corpus_stats,
                    "inbox": inbox_stats,
                    "task": task_status,
                }
                self.send_json(200, data)
                return

            if path in ("/openapi.json", "/api/openapi.json"):
                openapi_file = repo_root / "control_plane" / "openapi.json"
                if openapi_file.exists():
                    try:
                        spec = json.loads(openapi_file.read_text(encoding="utf-8"))
                        self.send_json(200, spec)
                        return
                    except Exception:
                        pass
                from gateways.bot_gateway import generate_openapi_schema
                self.send_json(200, generate_openapi_schema())
                return

            if path == "/api/config":
                env_dict = read_env_dict(repo_root / ".env")
                self.send_json(200, {"config": env_dict})
                return

            if path == "/api/prompts":
                from auth_proxy.prompt_engine import (
                    list_prompts,
                    load_soul,
                    load_system_prompt,
                    synthesize_system_prompt,
                )
                soul_text = load_soul(repo_root)
                sys_prompt_text = load_system_prompt(repo_root)
                synthesized = synthesize_system_prompt(repo_root)
                self.send_json(200, {
                    "soul": soul_text,
                    "system_prompt": sys_prompt_text,
                    "synthesized": synthesized,
                    "templates": list_prompts(),
                })
                return

            if path == "/api/logs":
                since = int(params.get("since", [0])[0])
                source = params.get("source", ["ALL"])[0]
                level = params.get("level", ["ALL"])[0]
                entries = system_logger.get_logs(since_id=since, source=source, level=level)
                last_id = entries[-1]["id"] if entries else since
                self.send_json(200, {
                    "status": runner.get_status(),
                    "logs": [e["raw"] for e in entries],
                    "entries": entries,
                    "last_id": last_id,
                    "total": system_logger.count(),
                })
                return

            if path == "/api/logs/export":
                try:
                    if system_logger.log_file.exists():
                        content = system_logger.log_file.read_bytes()
                    else:
                        content = "\n".join([e["raw"] for e in list(system_logger.entries)]).encode("utf-8")
                except Exception as e:
                    content = f"Error reading log file: {e}".encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="qmd-system.log"')
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return

            if path == "/api/search":
                query = params.get("q", [""])[0].strip()
                silo = params.get("silo", [""])[0].strip() or params.get("collection", [""])[0].strip()
                filter_json = params.get("filter", [""])[0].strip()
                if not query:
                    self.send_json(400, {"error": "Missing query 'q'"})
                    return

                qmd_args = ["search", query]
                if silo and silo.lower() != "all":
                    qmd_args.extend(["-c", silo])
                if filter_json:
                    qmd_args.extend(["--filter", filter_json])

                if sys.platform == "win32":
                    cmd = ["cmd.exe", "/c", str(repo_root / "qmd.cmd")] + qmd_args
                else:
                    cmd = ["qmd"] + qmd_args

                try:
                    res = subprocess.run(
                        cmd,
                        cwd=str(repo_root),
                        capture_output=True,
                        text=True,
                        timeout=45,
                    )
                    raw_out = res.stdout if res.stdout else res.stderr
                    self.send_json(200, {"query": query, "silo": silo or "all", "filter": filter_json, "output": raw_out, "exit_code": res.returncode})
                except subprocess.TimeoutExpired:
                    self.send_json(504, {"error": "Search timed out"})
                except Exception as e:
                    self.send_json(500, {"error": f"Search failed: {e}"})
                return

            if path == "/api/connectors":
                try:
                    from connectors.reach import AgentReachConnector
                    rc = AgentReachConnector(repo_root / "corpus")
                    ok, msg = rc.health_check()
                except Exception as e:
                    ok, msg = False, str(e)

                self.send_json(200, {
                    "reach": {"ok": ok, "details": msg},
                    "channels": ["youtube", "twitter", "reddit", "web", "github"],
                })
                return

            if path == "/api/skills":
                from auth_proxy.progressive_tools import list_skills
                skills = list_skills(repo_root / "skills")
                self.send_json(200, {"skills": skills, "count": len(skills)})
                return

            if path.startswith("/api/skills/"):
                skill_name = path[len("/api/skills/"):].strip()
                from auth_proxy.progressive_tools import view_skill
                try:
                    content = view_skill(skill_name, repo_root / "skills")
                    self.send_json(200, {"name": skill_name, "content": content})
                except Exception as e:
                    self.send_json(404, {"error": str(e)})
                return

            if path == "/api/tools":
                from auth_proxy.progressive_tools import TOOL_REGISTRY, get_progressive_tools_manifest
                self.send_json(200, {
                    "catalog": list(TOOL_REGISTRY.values()),
                    "progressive_manifest": get_progressive_tools_manifest(),
                })
                return

            if path == "/api/automations":
                jobs = scheduler_store.load_jobs()
                self.send_json(200, {"automations": [j.to_dict() for j in jobs], "count": len(jobs)})
                return

            if path.startswith("/api/automations/"):
                job_id = path[len("/api/automations/"):].strip()
                job = scheduler_store.get_job(job_id)
                if job:
                    self.send_json(200, job.to_dict())
                else:
                    self.send_json(404, {"error": f"Automation '{job_id}' not found"})
                return

            if path == "/api/sandboxes":
                from control_plane.sandbox import CloudSandbox
                cs = CloudSandbox(repo_root=repo_root)
                configured, provider = cs.is_configured()
                self.send_json(200, {
                    "local": {"available": True, "type": "subprocess"},
                    "cloud": {"configured": configured, "provider": provider},
                })
                return

            if path == "/api/engine/operational-mode":
                env_dict = read_env_dict(repo_root / ".env")
                current_mode = env_dict.get("OPERATIONAL_MODE", "full").lower()
                self.send_json(200, {
                    "operational_mode": current_mode,
                    "modes": [
                        {
                            "id": "offline-only",
                            "name": "Offline Only",
                            "description": "100% on-device. Local GGUF models via llama.cpp + local Pi ReAct + SQLite index. Zero network calls.",
                        },
                        {
                            "id": "offline+cloudflare-wiki",
                            "name": "Offline Search + Cloudflare Wiki",
                            "description": "Local search and Pi agent execution, plus Cloudflare Workers AI for cross-silo wiki synthesis & topic hub compilation.",
                        },
                        {
                            "id": "full",
                            "name": "Full Cloud Connected",
                            "description": "Everything enabled: Cloudflare Artifacts (Git versioning), Cloudflare R2 binary snapshots, and cloud models.",
                        },
                    ],
                })
                return

            if path == "/api/sync/status":
                status = sync_manager.get_status(corpus_dir=repo_root / "corpus")
                self.send_json(200, status)
                return

            if path == "/api/sync/history":
                limit = int(params.get("limit", [15])[0])
                history = sync_manager.artifacts.get_history(repo_root / "corpus", limit=limit)
                self.send_json(200, {"history": history, "count": len(history)})
                return

            if path == "/api/pi/status":
                state_res = pi_bridge.get_state()
                self.send_json(200, {
                    "is_running": pi_bridge.is_running,
                    "mode": pi_bridge.mode,
                    "state": state_res.get("data", {}),
                })
                return

            if path == "/api/pi/events":
                since = int(params.get("since", [0])[0])
                events = pi_bridge.get_events(since_id=since)
                self.send_json(200, {
                    "events": events,
                    "last_id": events[-1]["id"] if events else since,
                    "count": len(events),
                })
                return

            if path == "" or path == "/":
                self.path = "/index.html"
            super().do_GET()

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")

            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""

            if path == "/api/config":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return

                updates = payload.get("updates", {})
                if not isinstance(updates, dict):
                    self.send_json(400, {"error": "'updates' must be an object"})
                    return

                write_env_dict(repo_root / ".env", updates)
                self.send_json(200, {"status": "saved", "count": len(updates)})
                return

            if path == "/api/prompts":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return

                soul_text = payload.get("soul")
                sys_prompt_text = payload.get("system_prompt")

                if soul_text is not None:
                    (repo_root / "SOUL.md").write_text(soul_text.strip() + "\n", encoding="utf-8")
                if sys_prompt_text is not None:
                    (repo_root / "SYSTEM_PROMPT.md").write_text(sys_prompt_text.strip() + "\n", encoding="utf-8")

                self.send_json(200, {"status": "saved", "message": "Prompts updated successfully"})
                return

            if path == "/api/run":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return

                action = payload.get("action", "")
                if not action:
                    self.send_json(400, {"error": "Missing action"})
                    return

                success = runner.trigger(action)
                if not success:
                    self.send_json(409, {"error": "A task is already running or action is invalid"})
                    return

                self.send_json(200, {"status": "started", "action": action})
                return

            if path == "/api/stop":
                stopped = runner.stop_current()
                self.send_json(200, {"status": "stopped" if stopped else "not_running"})
                return

            if path == "/api/engine/mode":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return

                mode = payload.get("mode", "").strip().lower()
                if mode not in ("cpu-only", "full"):
                    self.send_json(400, {"error": "Invalid mode. Must be 'cpu-only' or 'full'"})
                    return

                write_env_dict(repo_root / ".env", {"RETRIEVAL_MODE": mode})

                res_qmd = supervisor.restart_daemon("qmd")
                res_proxy = supervisor.restart_daemon("auth_proxy")

                self.send_json(200, {
                    "retrieval_mode": mode,
                    "restarted": {
                        "qmd": res_qmd,
                        "auth_proxy": res_proxy,
                    },
                })
                return

            if path == "/api/daemons":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return

                daemon = payload.get("daemon", "")
                action = payload.get("action", "")

                if action == "start":
                    if daemon == "all":
                        res1 = supervisor.start_daemon("qmd")
                        res2 = supervisor.start_daemon("auth_proxy")
                        res3 = supervisor.start_daemon("tunnel")
                        self.send_json(200, {"results": [res1, res2, res3]})
                    else:
                        res = supervisor.start_daemon(daemon)
                        self.send_json(200, res)
                    return
                elif action == "stop":
                    if daemon == "all":
                        res1 = supervisor.stop_daemon("qmd")
                        res2 = supervisor.stop_daemon("auth_proxy")
                        res3 = supervisor.stop_daemon("tunnel")
                        self.send_json(200, {"results": [res1, res2, res3]})
                    else:
                        res = supervisor.stop_daemon(daemon)
                        self.send_json(200, res)
                    return
                elif action == "restart":
                    if daemon == "all":
                        supervisor.stop_daemon("qmd")
                        supervisor.stop_daemon("auth_proxy")
                        supervisor.stop_daemon("tunnel")
                        time.sleep(1.0)
                        res1 = supervisor.start_daemon("qmd")
                        res2 = supervisor.start_daemon("auth_proxy")
                        res3 = supervisor.start_daemon("tunnel")
                        self.send_json(200, {"results": [res1, res2, res3]})
                    else:
                        res = supervisor.restart_daemon(daemon)
                        self.send_json(200, res)
                    return

                self.send_json(400, {"error": "Invalid action or daemon"})
                return

            if path in (
                "/api/connectors/reach",
                "/api/connectors/youtube",
                "/api/connectors/twitter",
                "/api/connectors/reddit",
                "/api/connectors/web",
                "/api/connectors/github",
            ):
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return

                url = payload.get("url", "").strip() or payload.get("repo", "").strip()
                if not url:
                    self.send_json(400, {"error": "Missing 'url' or 'repo' in request body"})
                    return

                channel_type = payload.get("type", "").strip().lower()
                if not channel_type or channel_type == "auto":
                    if path == "/api/connectors/youtube":
                        channel_type = "youtube"
                    elif path == "/api/connectors/twitter":
                        channel_type = "twitter"
                    elif path == "/api/connectors/reddit":
                        channel_type = "reddit"
                    elif path == "/api/connectors/web":
                        channel_type = "web"
                    elif path == "/api/connectors/github":
                        channel_type = "github"
                    else:
                        channel_type = "auto"

                transcribe = bool(payload.get("transcribe", False))

                try:
                    from connectors.reach import ingest_url
                    target_path, unit = ingest_url(
                        url=url,
                        corpus_root=repo_root / "corpus",
                        channel_type=channel_type,
                        transcribe_audio=transcribe,
                    )
                    system_logger.log(
                        "CONNECTOR",
                        f"Ingested {unit.source} from {url} into {target_path.relative_to(repo_root)} ({unit.title})"
                    )
                    self.send_json(200, {
                        "status": "success",
                        "file": str(target_path.relative_to(repo_root)).replace("\\", "/"),
                        "title": unit.title,
                        "silo": unit.silo,
                        "source": unit.source,
                        "summary": unit.summary,
                        "author": unit.author,
                        "url": unit.url,
                    })
                except Exception as e:
                    system_logger.log("CONNECTOR", f"Failed to ingest {url}: {e}", level="ERROR")
                    self.send_json(500, {"error": f"Ingestion failed: {e}"})
                return

            if path == "/api/upload":
                filename = self.headers.get("X-Filename") or parsed.query.replace("filename=", "")
                if not filename:
                    cd = self.headers.get("Content-Disposition", "")
                    m = re.search(r'filename="?([^";]+)"?', cd)
                    if m:
                        filename = m.group(1)

                if not filename:
                    filename = f"upload_{int(time.time())}.bin"

                filename = os.path.basename(filename).strip()
                lower = filename.lower()

                if lower.endswith(".zip"):
                    is_notes_zip = any(k in lower for k in ("simplenote", "keep", "note"))
                    if not is_notes_zip:
                        try:
                            with zipfile.ZipFile(io.BytesIO(body), "r") as zf:
                                for name in zf.namelist():
                                    nl = name.lower()
                                    if "notes.json" in nl or nl.startswith("notes/") or nl.startswith("takeout/keep/"):
                                        is_notes_zip = True
                                        break
                        except Exception:
                            pass

                    if is_notes_zip:
                        dest_dir = repo_root / "inbox" / "notes"
                    else:
                        dest_dir = repo_root / "inbox" / "chats"
                elif lower.endswith(".pdf"):
                    dest_dir = repo_root / "inbox" / "pdfs"
                elif lower.endswith(".md") or lower.endswith(".txt"):
                    dest_dir = repo_root / "corpus" / "notes"
                else:
                    dest_dir = repo_root / "inbox"

                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / filename
                dest_path.write_bytes(body)

                self.send_json(201, {
                    "status": "uploaded",
                    "filename": filename,
                    "target_dir": str(dest_dir.relative_to(repo_root)),
                    "size_bytes": len(body),
                })
                return

            if path == "/api/automations":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return
                from control_plane.scheduler import AutomationJob, compute_next_run
                job = AutomationJob.from_dict(payload)
                if not job.next_run_at and job.enabled:
                    job.next_run_at = compute_next_run(job.schedule).isoformat()
                scheduler_store.upsert_job(job)
                system_logger.log("SCHEDULER", f"Saved automation '{job.name}' ({job.id})")
                self.send_json(200, {"status": "saved", "job": job.to_dict()})
                return

            if path.startswith("/api/automations/") and path.endswith("/trigger"):
                job_id = path[len("/api/automations/"): -len("/trigger")].strip()
                try:
                    res = scheduler_daemon.trigger_job(job_id)
                    self.send_json(200, {"status": "triggered", "result": res.to_dict()})
                except Exception as e:
                    self.send_json(500, {"error": f"Trigger failed: {e}"})
                return

            if path.startswith("/api/automations/") and path.endswith("/toggle"):
                job_id = path[len("/api/automations/"): -len("/toggle")].strip()
                job = scheduler_store.get_job(job_id)
                if not job:
                    self.send_json(404, {"error": f"Automation '{job_id}' not found"})
                    return
                job.enabled = not job.enabled
                from control_plane.scheduler import compute_next_run
                if job.enabled and not job.next_run_at:
                    job.next_run_at = compute_next_run(job.schedule).isoformat()
                scheduler_store.upsert_job(job)
                system_logger.log("SCHEDULER", f"Toggled automation '{job.name}' ({job.id}) enabled={job.enabled}")
                self.send_json(200, {"status": "updated", "job": job.to_dict()})
                return

            if path.startswith("/api/automations/") and path.endswith("/delete"):
                job_id = path[len("/api/automations/"): -len("/delete")].strip()
                deleted = scheduler_store.delete_job(job_id)
                if deleted:
                    system_logger.log("SCHEDULER", f"Deleted automation '{job_id}'")
                    self.send_json(200, {"status": "deleted", "id": job_id})
                else:
                    self.send_json(404, {"error": f"Automation '{job_id}' not found"})
                return

            if path == "/api/sandboxes/execute":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return
                action = payload.get("action", "")
                params_dict = payload.get("params", {})
                tier = payload.get("tier", "local")
                timeout = int(payload.get("timeout", 300))
                from control_plane.sandbox import execute_action
                res = execute_action(action=action, params=params_dict, tier=tier, timeout=timeout, repo_root=repo_root)
                self.send_json(200, res.to_dict())
                return

            if path == "/api/engine/operational-mode":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return
                mode = payload.get("mode", "").strip().lower()
                if mode not in ("offline-only", "offline+cloudflare-wiki", "full"):
                    self.send_json(400, {"error": "Invalid mode. Must be 'offline-only', 'offline+cloudflare-wiki', or 'full'"})
                    return
                write_env_dict(repo_root / ".env", {"OPERATIONAL_MODE": mode})
                os.environ["OPERATIONAL_MODE"] = mode
                system_logger.log("OPERATIONAL_MODE", f"Switched operational mode to '{mode}'")
                self.send_json(200, {"status": "updated", "operational_mode": mode})
                return

            if path == "/api/sync/trigger":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    payload = {}
                commit_msg = payload.get("message", "Manual sync triggered from Control Plane")
                system_logger.log("SYNC", f"Triggered Cloudflare sync: '{commit_msg}'")
                res = sync_manager.sync_all(corpus_dir=repo_root / "corpus", commit_message=commit_msg)
                self.send_json(200, res)
                return

            if path == "/api/sync/revert":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return
                commit_hash = payload.get("commit", "").strip()
                if not commit_hash:
                    self.send_json(400, {"error": "Missing 'commit' hash in request body"})
                    return
                system_logger.log("SYNC", f"Reverting corpus to commit: {commit_hash}")
                res = sync_manager.artifacts.revert_commit(repo_root / "corpus", commit_hash)
                self.send_json(200, res)
                return

            if path == "/api/pi/goal":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return
                prompt = payload.get("prompt", "").strip()
                if not prompt:
                    self.send_json(400, {"error": "Missing 'prompt' in request body"})
                    return
                session_id = payload.get("session_id")
                model = payload.get("model")
                system_logger.log("PI_AGENT", f"Autonomous goal received: '{prompt[:100]}'")
                result = pi_bridge.execute_goal(prompt, session_id=session_id, model=model)
                self.send_json(200, result)
                return

            self.send_json(404, {"error": "Endpoint not found"})

        def do_PUT(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""

            if path.startswith("/api/automations/"):
                job_id = path[len("/api/automations/"):].strip()
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    self.send_json(400, {"error": "Invalid JSON"})
                    return
                existing = scheduler_store.get_job(job_id)
                if not existing:
                    self.send_json(404, {"error": f"Automation '{job_id}' not found"})
                    return
                for k, v in payload.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
                scheduler_store.upsert_job(existing)
                system_logger.log("SCHEDULER", f"Updated automation '{existing.name}' ({existing.id})")
                self.send_json(200, {"status": "saved", "job": existing.to_dict()})
                return

            self.send_json(404, {"error": "Endpoint not found"})

        def do_DELETE(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")
            if path.startswith("/api/automations/"):
                job_id = path[len("/api/automations/"):].strip()
                deleted = scheduler_store.delete_job(job_id)
                if deleted:
                    system_logger.log("SCHEDULER", f"Deleted automation '{job_id}'")
                    self.send_json(200, {"status": "deleted", "id": job_id})
                else:
                    self.send_json(404, {"error": f"Automation '{job_id}' not found"})
                return
            self.send_json(404, {"error": "Endpoint not found"})

    return Handler


def run_server(port: int = 3333, host: str = "127.0.0.1") -> None:
    from control_plane.scheduler import SchedulerDaemon, SchedulerStore
    store = SchedulerStore(REPO_ROOT / "automations.json")
    scheduler = SchedulerDaemon(repo_root=REPO_ROOT, store=store)
    scheduler.start()

    handler_class = make_control_plane_handler(REPO_ROOT, STATIC_DIR, scheduler=scheduler)
    server = ThreadingHTTPServer((host, port), handler_class)
    print("================================================================")
    print(f"  QMD Knowledgebase Control Plane running at http://{host}:{port}")
    print("  Open in your browser to manage configs, daemons, and pipelines.")
    print("================================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Control Plane...")
        scheduler.stop()
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QMD Knowledgebase Control Plane")
    parser.add_argument("--port", type=int, default=3333, help="Port to listen on (default 3333)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default 127.0.0.1)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)
