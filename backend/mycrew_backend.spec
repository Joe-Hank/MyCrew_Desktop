# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for MyCrew backend.

Usage:
    cd backend
    pyinstaller mycrew_backend.spec

Output: dist/mycrew-backend.exe (Windows) or dist/mycrew-backend (Linux/macOS)
Copy the binary to src-tauri/binaries/<target-triple>/
"""

import sys
from pathlib import Path

block_cipher = None
backend_dir = Path(SPECPATH)

a = Analysis(
    [str(backend_dir / "bootstrap" / "app.py")],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=[
        (str(backend_dir / "migrations"), "migrations"),
    ],
    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "aiosqlite",
        "structlog",
        "httpx",
        "websockets",
        "alembic",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas"],
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
    name="mycrew-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep console for logging; Tauri hides it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
