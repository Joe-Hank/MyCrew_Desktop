"""Build script for MyCrew Desktop.

Steps:
1. PyInstaller: backend → single binary
2. Copy binary to src-tauri/binaries/ with target-triple suffix
3. cargo tauri build

Usage:
    python scripts/build.py          # full build
    python scripts/build.py --backend-only   # only PyInstaller step
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
TAURI_DIR = ROOT / "src-tauri"
BINARIES_DIR = TAURI_DIR / "binaries"


def get_target_triple() -> str:
    """Determine Rust target triple for current platform."""
    machine = platform.machine().lower()
    system = platform.system().lower()

    arch_map = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
    arch = arch_map.get(machine, machine)

    if system == "windows":
        return f"{arch}-pc-windows-msvc"
    elif system == "darwin":
        return f"{arch}-apple-darwin"
    elif system == "linux":
        return f"{arch}-unknown-linux-gnu"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def build_backend():
    """Run PyInstaller to produce the backend binary."""
    print("=== Building backend with PyInstaller ===")
    spec_file = BACKEND_DIR / "mycrew_backend.spec"
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(spec_file), "--distpath", str(BACKEND_DIR / "dist")],
        cwd=str(BACKEND_DIR),
        check=True,
    )

    # Determine output name
    ext = ".exe" if platform.system() == "Windows" else ""
    src = BACKEND_DIR / "dist" / f"mycrew-backend{ext}"
    if not src.exists():
        raise FileNotFoundError(f"Expected binary not found: {src}")

    # Copy to Tauri binaries dir with target-triple suffix
    triple = get_target_triple()
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    dst = BINARIES_DIR / f"mycrew-backend-{triple}{ext}"
    shutil.copy2(src, dst)
    print(f"  → Copied to {dst}")


def build_tauri():
    """Run cargo tauri build."""
    print("=== Building Tauri app ===")
    subprocess.run(
        ["cargo", "tauri", "build"],
        cwd=str(ROOT),
        check=True,
    )


def main():
    backend_only = "--backend-only" in sys.argv

    build_backend()

    if not backend_only:
        build_tauri()

    print("\n✅ Build complete!")


if __name__ == "__main__":
    main()
