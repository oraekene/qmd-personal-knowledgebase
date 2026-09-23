"""Tests for Standalone Desktop Application Packaging & Launcher (Issue 6)."""

from __future__ import annotations

import json
import os
import pathlib
import platform
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.package_desktop import generate_spec_file
from scripts.run_desktop import (
    find_system_app_browser,
    is_server_healthy,
    launch_native_window,
    run_desktop_app,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_install_and_launch_scripts_exist():
    """Verify all 1-click installer and launcher files exist."""
    install_cmd = REPO_ROOT / "install.cmd"
    install_sh = REPO_ROOT / "install.sh"
    launch_cmd = REPO_ROOT / "launch-desktop.cmd"
    requirements = REPO_ROOT / "requirements.txt"
    desktop_py = REPO_ROOT / "scripts" / "run_desktop.py"
    package_py = REPO_ROOT / "scripts" / "package_desktop.py"

    assert install_cmd.is_file(), "install.cmd missing"
    assert install_sh.is_file(), "install.sh missing"
    assert launch_cmd.is_file(), "launch-desktop.cmd missing"
    assert requirements.is_file(), "requirements.txt missing"
    assert desktop_py.is_file(), "run_desktop.py missing"
    assert package_py.is_file(), "package_desktop.py missing"

    assert "run_desktop.py" in launch_cmd.read_text(encoding="utf-8")
    assert "pyyaml" in requirements.read_text(encoding="utf-8")


def test_find_system_app_browser():
    """Verify system browser detection logic."""
    browser_info = find_system_app_browser()
    if platform.system() == "Windows":
        # On Windows host, Edge or Chrome is installed
        assert browser_info is not None
        exe_path, args = browser_info
        assert os.path.isfile(exe_path)
        assert any("edge" in exe_path.lower() or "chrome" in exe_path.lower() for _ in [1])
        assert "--app={url}" in args


def test_generate_spec_file(tmp_path: pathlib.Path):
    """Verify PyInstaller spec generation."""
    spec_path = tmp_path / "test.spec"
    content = generate_spec_file(spec_path)
    assert spec_path.is_file()
    assert "run_desktop.py" in content
    assert "control_plane/static" in content
    assert "hidden_imports" in content


def test_desktop_launcher_check_only_cli():
    """Verify desktop launcher runs cleanly in --check-only mode."""
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "run_desktop.py"), "--check-only"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0
    assert "Detected standalone browser:" in proc.stdout


def test_is_server_healthy_mocked():
    """Verify server health check with mocked responses."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_cm):
        assert is_server_healthy(3333) is True

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert is_server_healthy(3333) is False


def test_launch_native_window_browser_fallback():
    """Verify fallback to webbrowser when browser_only is requested."""
    with patch("webbrowser.open") as mock_open:
        launch_native_window("http://127.0.0.1:3333", browser_only=True)
        mock_open.assert_called_once_with("http://127.0.0.1:3333")
