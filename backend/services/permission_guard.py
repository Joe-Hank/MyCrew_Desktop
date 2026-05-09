"""Permission guard — checks system permission switches before Tool/MCP execution.

Usage:
    from services.permission_guard import require_permission

    await require_permission("file_read")   # raises PermissionDenied if disabled
    await require_permission("cmd_exec")
"""

from __future__ import annotations

import structlog

from services.permission_svc import permission_svc

log = structlog.get_logger()

# Maps high-level operation categories to permission kinds in DB
OPERATION_MAP: dict[str, list[str]] = {
    "file_read": ["file_read", "folder_read"],
    "file_write": ["file_write"],
    "file_delete": ["file_delete"],
    "file_modify": ["file_modify"],
    "folder_read": ["folder_read"],
    "dir_create": ["dir_create"],
    "cmd_exec": ["cmd_exec"],
    "bg_cmd": ["bg_cmd"],
    "git": ["git"],
}


class PermissionDenied(Exception):
    """Raised when a system permission is disabled."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(f"Permission denied: {kind} is disabled")


async def require_permission(kind: str) -> None:
    """Check if a permission kind is allowed. Raises PermissionDenied if not."""
    allowed = await permission_svc.check(kind)
    if not allowed:
        log.warning("permission.denied", kind=kind)
        raise PermissionDenied(kind)


async def check_tool_permissions(tool_name: str, arguments: dict) -> None:
    """Infer required permissions from tool name/arguments and check them.

    This is a best-effort heuristic. Tools that perform file operations,
    command execution, or git operations will be checked against the
    permission matrix.
    """
    tool_lower = tool_name.lower()

    # File read operations
    if any(kw in tool_lower for kw in ("read", "get_file", "find_in_file", "file_index")):
        await require_permission("file_read")

    # File write operations
    if any(kw in tool_lower for kw in ("write", "create_file", "create_script")):
        await require_permission("file_write")

    # File delete operations
    if any(kw in tool_lower for kw in ("delete", "remove")):
        await require_permission("file_delete")

    # File modify operations
    if any(kw in tool_lower for kw in ("modify", "edit", "apply_edit", "replace")):
        await require_permission("file_modify")

    # Directory operations
    if any(kw in tool_lower for kw in ("mkdir", "create_dir", "create_folder")):
        await require_permission("dir_create")

    # Command execution
    if any(kw in tool_lower for kw in ("exec", "execute", "run_command", "shell")):
        await require_permission("cmd_exec")

    # Git operations
    if "git" in tool_lower:
        await require_permission("git")
