"""Git MCP tool bridges.

Targets `mcp-server-git` (uvx mcp-server-git). The server takes a
`repo_path` argument on each tool call; we factory-bind it to the
active project's `root_path` so the LLM never has to provide it.

We bridge 6 commonly-used operations:
  git_status, git_log, git_diff_unstaged, git_diff_staged,
  git_add, git_commit

Skipped (lower-priority, can be added later):
  git_reset, git_create_branch, git_checkout, git_show, git_init
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


_SERVER = "git"


# ── Shared helpers ─────────────────────────────────────────────────

class _GitTool(GuardedMCPTool):
    """Base that holds the bound repo_path for all git tools."""
    permission_kind: ClassVar[str | None] = "git"
    _bound_repo_path: ClassVar[str] = ""

    def _repo(self) -> str:
        return self._bound_repo_path or ""


# ── Read-only inspection ───────────────────────────────────────────

class _NoArgs(BaseModel):
    pass


class GitStatus(_GitTool):
    name: str = "git_status"
    description: str = "Show `git status` for the project repository (modified, staged, untracked files)."
    args_schema: type[BaseModel] = _NoArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "git_status"

    def _run(self) -> str:
        return self._guarded_call({"repo_path": self._repo()})


class GitLogArgs(BaseModel):
    max_count: int = Field(10, description="How many commits to show (default 10).")


class GitLog(_GitTool):
    name: str = "git_log"
    description: str = "Show the recent commit history (hash, author, date, message)."
    args_schema: type[BaseModel] = GitLogArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "git_log"

    def _run(self, max_count: int = 10) -> str:
        return self._guarded_call({"repo_path": self._repo(), "max_count": max_count})


class GitDiffUnstaged(_GitTool):
    name: str = "git_diff_unstaged"
    description: str = "Show working-tree changes that have NOT been staged yet."
    args_schema: type[BaseModel] = _NoArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "git_diff_unstaged"

    def _run(self) -> str:
        return self._guarded_call({"repo_path": self._repo()})


class GitDiffStaged(_GitTool):
    name: str = "git_diff_staged"
    description: str = "Show changes that are staged (in the index) but not yet committed."
    args_schema: type[BaseModel] = _NoArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "git_diff_staged"

    def _run(self) -> str:
        return self._guarded_call({"repo_path": self._repo()})


# ── Mutations (require user confirmation) ──────────────────────────

class GitAddArgs(BaseModel):
    files: list[str] = Field(..., description="Paths to add. Use ['.'] to stage everything.")


class GitAdd(_GitTool):
    name: str = "git_add"
    description: str = "Stage one or more files (`git add <files>`). Use ['.'] to stage all modified files."
    args_schema: type[BaseModel] = GitAddArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "git_add"

    def _run(self, files: list[str]) -> str:
        return self._guarded_call({"repo_path": self._repo(), "files": files})


class GitCommitArgs(BaseModel):
    message: str = Field(..., description="Commit message. Should be concise and descriptive.")


class GitCommit(_GitTool):
    name: str = "git_commit"
    description: str = "Create a commit from the currently-staged changes. Returns the new commit hash."
    args_schema: type[BaseModel] = GitCommitArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "git_commit"
    requires_confirmation: ClassVar[bool] = True

    def _run(self, message: str) -> str:
        return self._guarded_call({"repo_path": self._repo(), "message": message})


# ── Factory ────────────────────────────────────────────────────────

def make_git_tools(repo_path: str | None) -> dict[str, _GitTool]:
    """Bind a repo_path to a fresh set of git tools.

    Pass the project's root_path. If None / empty, the tools will still
    instantiate but every call returns an error — keeps the agent
    aware they need to set a project path.
    """
    repo = repo_path or ""

    def bind(cls):
        class _Bound(cls):
            _bound_repo_path: ClassVar[str] = repo
        return _Bound()

    return {
        "git_status": bind(GitStatus),
        "git_log": bind(GitLog),
        "git_diff_unstaged": bind(GitDiffUnstaged),
        "git_diff_staged": bind(GitDiffStaged),
        "git_add": bind(GitAdd),
        "git_commit": bind(GitCommit),
    }


__all__ = [
    "GitStatus", "GitLog", "GitDiffUnstaged", "GitDiffStaged",
    "GitAdd", "GitCommit", "make_git_tools",
]
