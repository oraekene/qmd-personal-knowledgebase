# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

added_files = [
    ('C:/Users/rotim/Documents/QMD powered Personal Knowledgebase and Search Engine/control_plane/static', 'control_plane/static'),
    ('C:/Users/rotim/Documents/QMD powered Personal Knowledgebase and Search Engine/skills', 'skills'),
    ('C:/Users/rotim/Documents/QMD powered Personal Knowledgebase and Search Engine/SOUL.md', '.'),
    ('C:/Users/rotim/Documents/QMD powered Personal Knowledgebase and Search Engine/SYSTEM_PROMPT.md', '.'),
    ('C:/Users/rotim/Documents/QMD powered Personal Knowledgebase and Search Engine/automations.json', '.'),
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
    ['C:/Users/rotim/Documents/QMD powered Personal Knowledgebase and Search Engine/scripts/run_desktop.py'],
    pathex=['C:/Users/rotim/Documents/QMD powered Personal Knowledgebase and Search Engine'],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
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
