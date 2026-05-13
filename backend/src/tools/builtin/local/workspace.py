"""Workspace-scoped local file tools — write_file / mkdir / read_file_local
/ list_directory_local.

Why these exist alongside the filesystem MCP
--------------------------------------------
The filesystem MCP requires an external stdio server running; these
tools talk to Python's `pathlib` directly so they always work and can
enforce **workdir scoping** against the bound project's `root_path` —
preventing the agent from writing outside the project root by mistake
or by injection.

All four are bound via factory at agent-construction time: the
crewai_runner reads the current task's project_id → looks up
`projects.root_path` → injects it as `_bound_root`. If the project has
no root_path set, the tools refuse to run and tell the agent why.

Permissions: write_file/mkdir require file_write / dir_create; read
tools require file_read / folder_read. The base class enforces these
before the operation.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool

log = structlog.get_logger()


# ── Helpers ────────────────────────────────────────────────────────

def _resolve_in_root(root: str, rel_or_abs: str) -> Path | str:
    """Resolve `rel_or_abs` against the project root, refusing escapes.

    Returns the resolved Path on success, or an error string ready to
    return to the LLM. Symlinks inside the root are allowed; resolution
    of `..` is bounded by the root.
    """
    if not root:
        return (
            "[Error] This project has no root_path configured. Set the "
            "project path on the home page first."
        )
    root_p = Path(root).resolve()
    if not root_p.exists() or not root_p.is_dir():
        return f"[Error] Project root '{root}' does not exist or is not a directory."

    # `rel_or_abs` may be either relative (preferred) or an absolute path
    # that already lies inside the root. Reject anything else.
    p = Path(rel_or_abs)
    candidate = (root_p / p) if not p.is_absolute() else p
    try:
        resolved = candidate.resolve()
    except Exception as exc:
        return f"[Error] Cannot resolve path '{rel_or_abs}': {exc}"

    try:
        resolved.relative_to(root_p)
    except ValueError:
        return (
            f"[Error] Path '{rel_or_abs}' escapes the project root "
            f"'{root_p}'. All file ops must stay inside the project."
        )
    return resolved


# ── write_file ─────────────────────────────────────────────────────

class WriteFileArgs(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Path inside the project (relative preferred, absolute also "
            "accepted as long as it lies inside the project root). "
            "Parent dirs are created automatically."
        ),
    )
    content: str = Field(..., description="Full text content to write.")
    mode: str = Field(
        "overwrite",
        description="'overwrite' (default) or 'append'.",
    )


class WriteFile(GuardedLocalTool):
    name: str = "write_file"
    description: str = (
        "Write a text file inside the project workspace. Parent directories "
        "are auto-created. Use mode='append' to append; otherwise existing "
        "files are overwritten. Returns the bytes written."
    )
    args_schema: type[BaseModel] = WriteFileArgs
    permission_kind: ClassVar[str | None] = "file_write"
    requires_confirmation: ClassVar[bool] = False

    _bound_root: ClassVar[str] = ""

    def _run(self, path: str, content: str, mode: str = "overwrite") -> str:
        resolved = _resolve_in_root(self._bound_root, path)
        if isinstance(resolved, str):
            return resolved

        async def _do() -> str:
            try:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                if mode == "append":
                    with resolved.open("a", encoding="utf-8") as f:
                        n = f.write(content)
                else:
                    with resolved.open("w", encoding="utf-8") as f:
                        n = f.write(content)
                log.info("write_file.ok",
                         path=str(resolved), bytes=n, mode=mode)
                return f"Wrote {n} chars to {resolved.relative_to(Path(self._bound_root))} ({mode})."
            except Exception as exc:
                return f"[Error] write_file failed: {exc}"

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            return f"[Error] write_file failed: {exc}"


# ── mkdir ──────────────────────────────────────────────────────────

class MkdirArgs(BaseModel):
    path: str = Field(..., description="Directory path inside the project (relative preferred).")


class Mkdir(GuardedLocalTool):
    name: str = "mkdir"
    description: str = (
        "Create a directory inside the project workspace. Intermediate "
        "directories are created as needed. Idempotent: existing dirs OK."
    )
    args_schema: type[BaseModel] = MkdirArgs
    permission_kind: ClassVar[str | None] = "dir_create"

    _bound_root: ClassVar[str] = ""

    def _run(self, path: str) -> str:
        resolved = _resolve_in_root(self._bound_root, path)
        if isinstance(resolved, str):
            return resolved

        async def _do() -> str:
            try:
                resolved.mkdir(parents=True, exist_ok=True)
                return f"Directory ready: {resolved.relative_to(Path(self._bound_root))}"
            except Exception as exc:
                return f"[Error] mkdir failed: {exc}"

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            return f"[Error] mkdir failed: {exc}"


# ── read_file_local ────────────────────────────────────────────────

class ReadFileLocalArgs(BaseModel):
    path: str = Field(..., description="Path inside the project (relative preferred).")
    max_chars: int = Field(
        20000,
        description="Truncate after this many characters (default 20000).",
    )


class ReadFileLocal(GuardedLocalTool):
    name: str = "read_file_local"
    description: str = (
        "Read a text file from inside the project workspace. Does not "
        "require the filesystem MCP. Long files are truncated to "
        "max_chars; the tail is replaced with '...[truncated]'."
    )
    args_schema: type[BaseModel] = ReadFileLocalArgs
    permission_kind: ClassVar[str | None] = "file_read"

    _bound_root: ClassVar[str] = ""

    def _run(self, path: str, max_chars: int = 20000) -> str:
        resolved = _resolve_in_root(self._bound_root, path)
        if isinstance(resolved, str):
            return resolved

        async def _do() -> str:
            try:
                if not resolved.exists():
                    return f"[Error] File does not exist: {resolved.relative_to(Path(self._bound_root))}"
                if not resolved.is_file():
                    return f"[Error] Not a file: {resolved.relative_to(Path(self._bound_root))}"
                text = resolved.read_text(encoding="utf-8", errors="replace")
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n...[truncated]"
                return text
            except Exception as exc:
                return f"[Error] read_file_local failed: {exc}"

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            return f"[Error] read_file_local failed: {exc}"


# ── list_directory_local ───────────────────────────────────────────

class ListDirectoryLocalArgs(BaseModel):
    path: str = Field(
        ".",
        description="Directory path inside the project (relative preferred; '.' = project root).",
    )


class ListDirectoryLocal(GuardedLocalTool):
    name: str = "list_directory_local"
    description: str = (
        "List entries in a project directory (one per line; directories "
        "marked with trailing '/'). Hidden entries (starting with '.') "
        "are skipped."
    )
    args_schema: type[BaseModel] = ListDirectoryLocalArgs
    permission_kind: ClassVar[str | None] = "folder_read"

    _bound_root: ClassVar[str] = ""

    def _run(self, path: str = ".") -> str:
        resolved = _resolve_in_root(self._bound_root, path)
        if isinstance(resolved, str):
            return resolved

        async def _do() -> str:
            try:
                if not resolved.exists() or not resolved.is_dir():
                    return f"[Error] Not a directory: {path}"
                entries = []
                for child in sorted(resolved.iterdir()):
                    if child.name.startswith("."):
                        continue
                    if child.is_dir():
                        entries.append(child.name + "/")
                    else:
                        size = child.stat().st_size
                        entries.append(f"{child.name}  ({size} bytes)")
                if not entries:
                    return "(empty directory)"
                return "\n".join(entries)
            except Exception as exc:
                return f"[Error] list_directory_local failed: {exc}"

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            return f"[Error] list_directory_local failed: {exc}"


# ── Factories ──────────────────────────────────────────────────────

def make_workspace_tools(root_path: str | None) -> dict[str, GuardedLocalTool]:
    """Return all four workspace tools bound to the given project root.

    Returns a `{name: instance}` dict so the registry layer can pick
    whichever subset the agent has in its tool_ids.
    """
    root = root_path or ""

    class _BoundWrite(WriteFile):
        _bound_root: ClassVar[str] = root

    class _BoundMkdir(Mkdir):
        _bound_root: ClassVar[str] = root

    class _BoundRead(ReadFileLocal):
        _bound_root: ClassVar[str] = root

    class _BoundList(ListDirectoryLocal):
        _bound_root: ClassVar[str] = root

    return {
        "write_file": _BoundWrite(),
        "mkdir": _BoundMkdir(),
        "read_file_local": _BoundRead(),
        "list_directory_local": _BoundList(),
    }


__all__ = [
    "WriteFile",
    "Mkdir",
    "ReadFileLocal",
    "ListDirectoryLocal",
    "make_workspace_tools",
]
