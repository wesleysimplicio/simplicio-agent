# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Hermes Agent standalone binary."""

import os
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['run_agent.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('hermes_cli/web_dist', 'hermes_cli/web_dist'),
        ('hermes_cli/tui_dist', 'hermes_cli/tui_dist'),
        ('scripts/install.sh', 'scripts'),
        ('scripts/install.ps1', 'scripts'),
    ],
    hiddenimports=[
        'pkg_resources',
        'pkgutil',
        'jinja2.ext',
        'yaml',
        'ruamel.yaml',
        'croniter',
        'requests',
        'httpx',
        'openai',
        'prompt_toolkit',
        'rich',
        'fire',
        'tenacity',
        'packaging',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'PIL',
        'cv2',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='simplicio-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
