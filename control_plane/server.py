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
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("control_plane")

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENV_PATH = REPO_ROOT / ".env"


def check_port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
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
        req = urllib.request.Request(url, headers={"User-Agent": "QMD-ControlPlane/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 204, 302, 401)
    except urllib.error.HTTPError as e:
        return e.code in (200, 204, 302, 401)
    except Exception:
        return False


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
    stats = {"chats": 0, "pdfs": 0, "total": 0}
    if not inbox_dir.exists():
        return stats
    chats_dir = inbox_dir / "chats"
    pdfs_dir = inbox_dir / "pdfs"

    root_zips = len(list(inbox_dir.glob("*.zip")))
    chat_zips = len(list(chats_dir.glob("*.zip"))) if chats_dir.exists() else 0
    stats["chats"] = root_zips + chat_zips

    pdf_files = len(list(pdfs_dir.glob("*.pdf"))) if pdfs_dir.exists() else 0
    stats["pdfs"] = pdf_files

    stats["total"] = stats["chats"] + stats["pdfs"]
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


class TaskRunner:
    """Manages background CLI pipelines and captures output logs."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
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
                    self.is_running = False
                    return True
                except Exception as e:
                    self.logs.append(f"[Control Plane] Error terminating: {e}")
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
            self.logs.append(f"[Control Plane] Starting action '{action}': {' '.join(cmd)}")

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
                        with self.lock:
                            self.logs.append(clean_line)

                    proc.wait()
                    with self.lock:
                        self.exit_code = proc.returncode
                        self.is_running = False
                        status_str = "SUCCESS" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
                        self.logs.append(f"[Control Plane] Action '{action}' finished: {status_str}")
                except Exception as e:
                    with self.lock:
                        self.exit_code = -1
                        self.is_running = False
                        self.logs.append(f"[Control Plane] Exception running action '{action}': {e}")

            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            return True


class DaemonSupervisor:
    """Tracks and controls background daemons (QMD, Auth Proxy, Cloudflare Tunnel)."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.processes: Dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()

    def start_daemon(self, name: str) -> Dict[str, Any]:
        with self.lock:
            env = os.environ.copy()
            env_file_dict = read_env_dict(self.repo_root / ".env")
            env.update(env_file_dict)

            use_shell = sys.platform == "win32"

            if name == "qmd":
                if check_port_listening("127.0.0.1", 8181):
                    return {"status": "already_running", "message": "QMD port 8181 is already active"}
                env["QMD_ALLOWED_ORIGINS"] = "*"
                if sys.platform == "win32":
                    cmd = ["cmd.exe", "/c", str(self.repo_root / "qmd.cmd"), "mcp", "--http", "--port", "8181"]
                else:
                    cmd = ["node", "qmd-main/node_modules/tsx/dist/cli.mjs", "qmd-main/src/cli/qmd.ts", "mcp", "--http", "--port", "8181"]
                proc = subprocess.Popen(cmd, cwd=str(self.repo_root), env=env)
                self.processes["qmd"] = proc
                return {"status": "started", "name": "qmd"}

            elif name == "auth_proxy":
                if check_port_listening("127.0.0.1", 3210):
                    return {"status": "already_running", "message": "Auth Proxy port 3210 is already active"}
                cmd = [sys.executable, "-m", "auth_proxy"]
                proc = subprocess.Popen(cmd, cwd=str(self.repo_root), env=env, shell=use_shell)
                self.processes["auth_proxy"] = proc
                return {"status": "started", "name": "auth_proxy"}

            elif name == "tunnel":
                token = env.get("TUNNEL_TOKEN", "")
                if not token:
                    return {"status": "error", "message": "TUNNEL_TOKEN not configured in .env"}
                cmd = ["cloudflared", "tunnel", "run", "--token", token]
                proc = subprocess.Popen(cmd, cwd=str(self.repo_root), env=env, shell=use_shell)
                self.processes["tunnel"] = proc
                return {"status": "started", "name": "tunnel"}

            return {"status": "unknown_daemon", "name": name}

    def stop_daemon(self, name: str) -> Dict[str, Any]:
        with self.lock:
            proc = self.processes.get(name)
            if proc:
                try:
                    proc.terminate()
                    time.sleep(0.5)
                    if proc.poll() is None:
                        proc.kill()
                    del self.processes[name]
                    return {"status": "stopped", "name": name}
                except Exception as e:
                    return {"status": "error", "name": name, "message": str(e)}
            return {"status": "not_managed", "name": name, "message": "Process was not started by this supervisor"}


def make_control_plane_handler(repo_root: Path, static_dir: Path):
    runner = TaskRunner(repo_root)
    supervisor = DaemonSupervisor(repo_root)

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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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

            if path == "/api/config":
                env_dict = read_env_dict(repo_root / ".env")
                self.send_json(200, {"config": env_dict})
                return

            if path == "/api/logs":
                since = int(params.get("since", [0])[0])
                logs = runner.get_logs(since_index=since)
                self.send_json(200, {
                    "status": runner.get_status(),
                    "logs": logs,
                    "total": len(runner.logs)
                })
                return

            if path == "/api/search":
                query = params.get("q", [""])[0].strip()
                if not query:
                    self.send_json(400, {"error": "Missing query 'q'"})
                    return

                if sys.platform == "win32":
                    cmd = ["cmd.exe", "/c", str(repo_root / "qmd.cmd"), "search", query]
                else:
                    cmd = ["qmd", "search", query]

                try:
                    res = subprocess.run(
                        cmd,
                        cwd=str(repo_root),
                        capture_output=True,
                        text=True,
                        timeout=45,
                    )
                    raw_out = res.stdout if res.stdout else res.stderr
                    self.send_json(200, {"query": query, "output": raw_out, "exit_code": res.returncode})
                except subprocess.TimeoutExpired:
                    self.send_json(504, {"error": "Search timed out"})
                except Exception as e:
                    self.send_json(500, {"error": f"Search failed: {e}"})
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
                    res = supervisor.stop_daemon(daemon)
                    self.send_json(200, res)
                    return
                elif action == "restart":
                    supervisor.stop_daemon(daemon)
                    time.sleep(1.0)
                    res = supervisor.start_daemon(daemon)
                    self.send_json(200, res)
                    return

                self.send_json(400, {"error": "Invalid action or daemon"})
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

            self.send_json(404, {"error": "Endpoint not found"})

    return Handler


def run_server(port: int = 3333, host: str = "127.0.0.1") -> None:
    handler_class = make_control_plane_handler(REPO_ROOT, STATIC_DIR)
    server = ThreadingHTTPServer((host, port), handler_class)
    print("================================================================")
    print(f"  QMD Knowledgebase Control Plane running at http://{host}:{port}")
    print("  Open in your browser to manage configs, daemons, and pipelines.")
    print("================================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Control Plane...")
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QMD Knowledgebase Control Plane")
    parser.add_argument("--port", type=int, default=3333, help="Port to listen on (default 3333)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default 127.0.0.1)")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)
