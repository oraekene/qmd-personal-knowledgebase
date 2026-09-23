"""Packaging and standalone binary build script for QMD Personal Knowledgebase.

Prepares standalone executable bundles using PyInstaller:
1. Generates PyInstaller .spec file including static assets, templates, connectors, and engine.
2. Packages binaries for Windows (portable .exe or distribution folder) and macOS (.app).
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [packaging] %(message)s")
logger = logging.getLogger("packaging")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def generate_spec_file(output_path: pathlib.Path) -> str:
    """Generate PyInstaller .spec file configured for QMD Knowledgebase."""
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

added_files = [
    ('{str(REPO_ROOT / "control_plane" / "static").replace(os.sep, "/")}', 'control_plane/static'),
    ('{str(REPO_ROOT / "skills").replace(os.sep, "/")}', 'skills'),
    ('{str(REPO_ROOT / "SOUL.md").replace(os.sep, "/")}', '.'),
    ('{str(REPO_ROOT / "SYSTEM_PROMPT.md").replace(os.sep, "/")}', '.'),
    ('{str(REPO_ROOT / "automations.json").replace(os.sep, "/")}', '.'),
]

hidden_imports = [
    'http.server',
    'urllib.request',
    'urllib.parse',
    'sqlite3',
    'json',
    'yaml',
    'connectors',
    'control_plane',
    'engine',
    'gateways',
    'sandbox',
    'sync',
]

a = Analysis(
    ['{str(REPO_ROOT / "scripts" / "run_desktop.py").replace(os.sep, "/")}'],
    pathex=['{str(REPO_ROOT).replace(os.sep, "/")}'],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='QMD-Knowledgebase',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""
    output_path.write_text(spec_content, encoding="utf-8")
    logger.info("Generated PyInstaller spec file at: %s", output_path)
    return spec_content


def build_bundle(spec_path: pathlib.Path) -> int:
    """Invoke PyInstaller on the generated spec file."""
    try:
        import PyInstaller  # type: ignore
    except ImportError:
        logger.warning("PyInstaller is not installed in the current environment.")
        logger.info("To build a standalone executable bundle, install PyInstaller via: pip install pyinstaller")
        logger.info("Then run: pyinstaller %s", spec_path)
        return 0

    logger.info("Running PyInstaller build...")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(spec_path)]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return res.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="QMD Desktop Packaging Utility")
    parser.add_argument("--spec-only", action="store_true", help="Only generate spec file without compiling")
    parser.add_argument("--output-spec", default=str(REPO_ROOT / "qmd_desktop.spec"), help="Path to save spec file")
    args = parser.parse_args()

    spec_file = pathlib.Path(args.output_spec)
    generate_spec_file(spec_file)

    if not args.spec_only:
        build_bundle(spec_file)


if __name__ == "__main__":
    main()
