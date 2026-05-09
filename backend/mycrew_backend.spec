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
    [str(backend_dir / "bootstrap" / "main.py")],
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
        "aiosqlite",
        "structlog",
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "websockets",
        "alembic",
        "tenacity",
        "jsonschema",
        "jsonschema.validators",
        # App modules
        "api",
        "api.routes_health",
        "api.routes_llm",
        "api.routes_mcp",
        "api.routes_config",
        "api.routes_workflow",
        "api.routes_project",
        "api.routes_inception",
        "api.routes_files",
        "api.routes_agent",
        "api.routes_crew",
        "api.routes_tool",
        "api.routes_lifecycle",
        "api.ws",
        "services",
        "services.inception_svc",
        "services.workflow_svc",
        "services.llm_svc",
        "services.mcp_svc",
        "services.project_svc",
        "services.tool_svc",
        "services.permission_guard",
        "infra.llm",
        "infra.llm.base",
        "infra.llm.openai_adapter",
        "infra.llm.anthropic_adapter",
        "infra.llm.registry",
        "infra.llm.gateway",
        "infra.repo",
        "infra.repo.crud",
        "infra.repo.sqlite_repo",
        "infra.mcp",
        "infra.mcp.pool",
        "infra.config_loader",
        "infra.event_bus",
        "infra.event_bus.in_memory_bus",
        "infra.interaction",
        "infra.interaction.ws_interaction",
        "domain",
        "domain.harness",
        "domain.harness.states",
        "domain.harness.state_machine",
        "domain.harness.task_runner",
        "domain.qa",
        "domain.qa.dag_validator",
        "domain.qa.output_validator",
        "domain.events",
        "bootstrap",
        "bootstrap.app",
        "bootstrap.paths",
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
