"""VerifyImageDimensions — read an image file's actual W×H and compare
to the contract.

QA-side tool for Art / UI Crews. The PM-level output_schema declares
width/height per image-producing task; the ComfyUI Generator passes
those values to comfy_create_workflow_from_template. QA calls this
tool to confirm the produced file's IHDR/SOF actually matches.

Pure stdlib (no Pillow). Supports PNG + JPEG; both are what ComfyUI
emits today. Returns a JSON-style summary so the LLM can read it back.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool
from src.tools.builtin.local.workspace import _resolve_in_root

log = structlog.get_logger()


def _read_png_dims(data: bytes) -> tuple[int, int] | None:
    # PNG: 8-byte signature + IHDR chunk; width/height at bytes 16-23.
    if len(data) < 24:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def _read_jpeg_dims(data: bytes) -> tuple[int, int] | None:
    # JPEG: scan SOFn markers (FF C0..FF CF except C4/C8/CC) and read
    # 2 bytes height + 2 bytes width starting 5 bytes after the marker.
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = struct.unpack(">H", data[i + 5:i + 7])[0]
            w = struct.unpack(">H", data[i + 7:i + 9])[0]
            return w, h
        # segment length is 2 bytes after marker
        if i + 4 > len(data):
            return None
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg_len
    return None


def _read_image_dims(path: Path) -> tuple[int, int] | None:
    # Only read enough bytes for headers; whole-file read is unnecessary.
    with path.open("rb") as f:
        head = f.read(64 * 1024)
    suffix = path.suffix.lower()
    if suffix == ".png":
        return _read_png_dims(head)
    if suffix in (".jpg", ".jpeg"):
        return _read_jpeg_dims(head)
    # Fallback: try both
    return _read_png_dims(head) or _read_jpeg_dims(head)


class VerifyImageDimensionsArgs(BaseModel):
    file_path: str = Field(..., description="Project-relative path to the image file (e.g. 'Assets/Sprites/coin.png').")
    expected_width: int = Field(..., gt=0, description="Width the PM contract requires.")
    expected_height: int = Field(..., gt=0, description="Height the PM contract requires.")


class VerifyImageDimensions(GuardedLocalTool):
    name: str = "verify_image_dimensions"
    description: str = (
        "Read an image file's actual pixel width and height from its "
        "header (PNG / JPEG) and compare to expected. Returns a JSON "
        "summary with ok=true/false, actual_width, actual_height, and "
        "a reason on mismatch. Use this in QA steps for image-producing "
        "tasks where the PM contract declares width/height."
    )
    args_schema: type[BaseModel] = VerifyImageDimensionsArgs
    permission_kind: ClassVar[str | None] = "file_read"

    _bound_root: ClassVar[str] = ""

    def _run(self, file_path: str, expected_width: int, expected_height: int) -> str:
        resolved = _resolve_in_root(self._bound_root, file_path)
        if isinstance(resolved, str):
            return resolved

        async def _do() -> str:
            if not resolved.is_file():
                return json.dumps({
                    "ok": False,
                    "reason": "file_not_found",
                    "file_path": file_path,
                }, ensure_ascii=False)
            try:
                dims = _read_image_dims(resolved)
            except Exception as exc:
                return json.dumps({
                    "ok": False,
                    "reason": f"header_parse_failed: {exc}",
                    "file_path": file_path,
                }, ensure_ascii=False)
            if dims is None:
                return json.dumps({
                    "ok": False,
                    "reason": "unsupported_format_or_corrupt_header",
                    "file_path": file_path,
                }, ensure_ascii=False)
            actual_w, actual_h = dims
            match = actual_w == expected_width and actual_h == expected_height
            payload = {
                "ok": match,
                "file_path": file_path,
                "expected_width": expected_width,
                "expected_height": expected_height,
                "actual_width": actual_w,
                "actual_height": actual_h,
            }
            if not match:
                payload["reason"] = (
                    f"size_mismatch: expected {expected_width}x{expected_height}, "
                    f"got {actual_w}x{actual_h}"
                )
            log.info("verify_image_dimensions",
                     path=file_path, expected=(expected_width, expected_height),
                     actual=dims, ok=match)
            return json.dumps(payload, ensure_ascii=False)

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            return f"[Error] verify_image_dimensions failed: {exc}"


def make_verify_image_dimensions_tool(root_path: str | None) -> VerifyImageDimensions:
    class _Bound(VerifyImageDimensions):
        _bound_root: ClassVar[str] = root_path or ""
    return _Bound()


__all__ = ["VerifyImageDimensions", "make_verify_image_dimensions_tool"]
