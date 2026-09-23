"""QMD Personal Knowledgebase — Standalone Desktop Application Launcher.

Provides a 1-click native desktop experience:
1. Verifies local environment and configuration.
2. Spawns or connects to the local Web Control Plane server on port 3333.
3. Launches a dedicated, borderless native desktop application window:
   - Priority 1: pywebview (native embedded WebView2 / WebKit / WebEngine)
   - Priority 2: Native Chromium/Edge Application Mode (--app=http://127.0.0.1:3333)
   - Priority 3: System default web browser
4. Gracefully terminates background supervisor and daemons on window close.
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from typing import List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [desktop] %(message)s")
logger = logging.getLogger("desktop_app")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PORT = 3333
DEFAULT_WIDTH = 1366
DEFAULT_HEIGHT = 850
APP_TITLE = "QMD Personal Knowledgebase & Search Engine"


def find_system_app_browser() -> Optional[Tuple[str, List[str]]]:
    """Find Microsoft Edge or Google Chrome for borderless standalone app window mode."""
    system = platform.system()
    candidates: List[pathlib.Path] = []

    if system == "Windows":
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        prog_64 = os.environ.get("ProgramFiles", r"C:\Program Files")
        local_app = os.environ.get("LOCALAPPDATA", "")

        candidates.extend([
            pathlib.Path(prog_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            pathlib.Path(prog_64) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            pathlib.Path(prog_64) / "Google" / "Chrome" / "Application" / "chrome.exe",
            pathlib.Path(prog_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
            pathlib.Path(local_app) / "Google" / "Chrome" / "Application" / "chrome.exe" if local_app else pathlib.Path(""),
            pathlib.Path(local_app) / "Microsoft" / "Edge" / "Application" / "msedge.exe" if local_app else pathlib.Path(""),
        ])
    elif system == "Darwin":  # macOS
        candidates.extend([
            pathlib.Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            pathlib.Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            pathlib.Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ])
    else:  # Linux
        for name in ["microsoft-edge", "google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "brave-browser"]:
            try:
                res = subprocess.run(["which", name], capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    return (res.stdout.strip(), ["--app={url}", "--window-size={w},{h}"])
            except Exception:
                pass

    for candidate in candidates:
        if candidate.is_file():
            return (str(candidate), ["--app={url}", "--window-size={w},{h}"])

    return None


def is_server_healthy(port: int) -> bool:
    """Check if Control Plane server responds to health check."""
    url = f"http://127.0.0.1:{port}/api/status"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "QMD-Desktop-Probe"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            code = getattr(resp, "status", getattr(resp, "code", 0))
            return code == 200
    except Exception:
        return False


def wait_for_server(port: int, timeout: float = 12.0) -> bool:
    """Poll until the server responds or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_server_healthy(port):
            return True
        time.sleep(0.4)
    return False


def start_server_process(port: int, repo_root: pathlib.Path) -> subprocess.Popen:
    """Start Control Plane server in background subprocess."""
    logger.info("Starting background Control Plane on port %d...", port)
    cmd = [sys.executable, "-m", "control_plane.server", "--port", str(port)]
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc


def launch_native_window(
    url: str,
    title: str = APP_TITLE,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    browser_only: bool = False,
) -> None:
    """Open application window with priority: pywebview -> Chromium App Mode -> Web Browser."""
    if not browser_only:
        # 1. Try pywebview if installed
        try:
            import webview  # type: ignore
            logger.info("Launching native WebView window via pywebview...")
            webview.create_window(title, url, width=width, height=height, min_size=(1024, 700))
            webview.start()
            return
        except ImportError:
            logger.info("pywebview not installed. Checking for system Chromium/Edge app mode...")
        except Exception as e:
            logger.warning("pywebview launch encountered an error: %s", e)

        # 2. Try Edge or Chrome in borderless app window mode
        app_browser = find_system_app_browser()
        if app_browser:
            exe_path, arg_templates = app_browser
            args = [
                exe_path,
                f"--app={url}",
                f"--window-size={width},{height}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            logger.info("Launching standalone desktop app mode: %s", exe_path)
            try:
                proc = subprocess.Popen(args)
                proc.wait()  # Block until the desktop window is closed
                return
            except Exception as e:
                logger.warning("Failed to launch app browser process: %s", e)

    # 3. Fallback to default browser
    logger.info("Opening Control Plane in default web browser: %s", url)
    webbrowser.open(url)


def run_desktop_app(
    port: int = DEFAULT_PORT,
    browser_only: bool = False,
    no_open: bool = False,
    repo_root: pathlib.Path | None = None,
) -> int:
    """Orchestrate desktop app startup, window lifecycle, and shutdown."""
    root = repo_root or REPO_ROOT
    server_proc: Optional[subprocess.Popen] = None
    app_url = f"http://127.0.0.1:{port}"

    try:
        # Check if already running
        if not is_server_healthy(port):
            server_proc = start_server_process(port, root)
            ready = wait_for_server(port, timeout=12.0)
            if not ready:
                logger.error("Control plane server failed to start within timeout.")
                if server_proc and server_proc.poll() is not None:
                    _, err = server_proc.communicate()
                    logger.error("Server stderr: %s", err)
                return 1
            logger.info("Control plane server healthy at %s", app_url)
        else:
            logger.info("Connected to existing Control Plane server running at %s", app_url)

        if not no_open:
            launch_native_window(
                url=app_url,
                title=APP_TITLE,
                width=DEFAULT_WIDTH,
                height=DEFAULT_HEIGHT,
                browser_only=browser_only,
            )

        # If we opened in default browser, give user prompt to keep running or stop
        if browser_only and server_proc:
            print("\n" + "=" * 60)
            print(f"  QMD Personal Knowledgebase is running at: {app_url}")
            print("  Press Ctrl+C to stop the desktop server...")
            print("=" * 60 + "\n")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        return 0

    finally:
        if server_proc and server_proc.poll() is None:
            logger.info("Terminating desktop server process...")
            server_proc.terminate()
            try:
                server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server_proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="QMD Personal Knowledgebase Desktop Launcher")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Control Plane port (default: 3333)")
    parser.add_argument("--browser-only", action="store_true", help="Open in standard browser instead of standalone app window")
    parser.add_argument("--no-open", action="store_true", help="Start server only without launching window")
    parser.add_argument("--check-only", action="store_true", help="Verify browser detection and exit")
    args = parser.parse_args()

    if args.check_only:
        browser = find_system_app_browser()
        print(f"Detected standalone browser: {browser[0] if browser else 'None (webbrowser fallback)'}")
        sys.exit(0)

    code = run_desktop_app(
        port=args.port,
        browser_only=args.browser_only,
        no_open=args.no_open,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
