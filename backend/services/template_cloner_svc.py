"""Clone Unity templates from GitHub into a user's chosen root dir.

Why this exists
---------------
Pre-2026-05-17 the project's `root_path` was set by the user to a
ready-made Unity project directory, and PM/Crews wrote into it
directly. New flow: the user picks a *parent* directory (e.g.
`F:\\UnityProjects\\`) plus a template; on the first click of "开始
项目", the backend clones the matching subfolder from the central
Templates repo (https://github.com/Joe-Hank/Templates) into the
parent, renaming the clone to the project's English name. The new
child dir becomes the project's effective root.

This module owns that clone step and nothing else:
  - resolves template_id → template git subfolder
  - performs sparse-checkout so we don't download all 4 templates'
    worth of assets when the user only wants one
  - moves/renames the result to <parent>/<project_name_en>
  - streams progress to WS so the task page's progress bar can update
  - updates `projects.root_path` + `projects.scaffold_status` rows
    transactionally with completion

Idempotency: if `scaffold_status='done'` we no-op. If it's 'failed' we
re-run (cleaning the partial child if present). If it's 'in_progress'
we refuse — another start attempt while a clone is mid-flight is a
bug, not a recovery path.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

import structlog

from infra.repo import crud

log = structlog.get_logger()


# ── Configuration ─────────────────────────────────────────────────


# Default template repo URL. 2026-05-17: switched from GitHub to Gitee
# because GitHub clone routinely fails for CN users behind flaky
# Clash/V2Ray proxies (RPC failed / Connection reset midway through
# blob fetch). Gitee mirrors the same content but lives inside the GFW
# so it's reachable directly without proxy.
#
# Override via env var if the user has a private mirror:
#   $env:MYCREW_TEMPLATE_REPO_URL = "https://gitee.com/<acct>/Templates.git"
#
# Mirror setup (do this once on Gitee):
#   1. Create empty public repo Joe-Hank/Templates on gitee.com
#   2. Either:
#        a) Gitee's "导入仓库" UI → paste GitHub URL → "立即克隆"
#        b) Or push local staged dir: see backend/scripts/mirror_to_gitee.sh
TEMPLATE_REPO_URL = os.getenv(
    "MYCREW_TEMPLATE_REPO_URL",
    "https://gitee.com/SoloSlow/Templates.git",
)
# Branch name is preserved on Gitee "导入仓库" from GitHub — we used
# 'main' on the GitHub source, so the Gitee mirror also gets 'main'.
TEMPLATE_REPO_BRANCH = os.getenv("MYCREW_TEMPLATE_REPO_BRANCH", "main")

# Maps the seed template id (used by inception drawer + Plan Maker) to
# the corresponding subdir in the Templates repo. Slugs are derived
# from `backend/scripts/stage_templates.py` NAME_MAP — keep in sync.
TEMPLATE_ID_TO_DIR = {
    "unity_universal_2d": "Universal2D",
    "unity_universal_3d": "Universal3D",
    "unity_ar_mobile": "ARMobile",
    "unity_mr_core": "MRCore",
}

# Allowed filesystem-friendly chars in the project's English name.
# Hyphen / underscore OK; spaces and CJK rejected (Unity tolerates
# spaces but git + many tools choke). User picks the english name in
# the inception drawer.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ScaffoldError(Exception):
    """Raised by clone_template on any unrecoverable failure. Caller
    (workflow_svc.start) catches and surfaces to the UI."""


# ── Public entry ──────────────────────────────────────────────────


async def clone_template(
    project_id: str,
    template_id: str,
    parent_dir: str,
    project_slug: str,
    *,
    on_progress=None,
    overwrite: bool = False,
) -> Path:
    """Clone the template matching `template_id` into
    `<parent_dir>/<project_slug>/`. Returns the resolved child path.

    `on_progress(stage: str, message: str)` is an async-callable hook
    fired at each milestone — caller wires it to the WS broadcaster so
    the frontend sees a live status string under the progress bar.

    `overwrite=True` (2026-05-17): used by the scaffold-repair flow.
    If the target already exists, force-delete it (Windows-safe rmtree)
    before re-cloning. WITHOUT overwrite, a target dir that we ourselves
    scaffolded earlier is still cleaned up (via the sentinel check) but
    a foreign dir refuses with ScaffoldError.

    Raises ScaffoldError on any invariant violation (bad name, unknown
    template, git failure, target exists without sentinel, etc).
    """
    # ── Pre-flight ────────────────────────────────────────────────
    if not _SAFE_NAME_RE.match(project_slug):
        raise ScaffoldError(
            f"项目名 '{project_slug}' 不是合法目录名 — "
            "只允许 [A-Za-z0-9_-]，需以字母或数字开头，不超过 64 字符"
        )
    sub_dir = TEMPLATE_ID_TO_DIR.get(template_id)
    if not sub_dir:
        raise ScaffoldError(
            f"模板 {template_id} 不支持脚手架 — 已知模板："
            f"{', '.join(TEMPLATE_ID_TO_DIR)}"
        )
    parent_path = Path(parent_dir).expanduser().resolve()
    if not parent_path.exists():
        try:
            parent_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ScaffoldError(
                f"创建父目录失败：{parent_path}（{exc}）"
            ) from exc
    if not parent_path.is_dir():
        raise ScaffoldError(f"父路径不是目录：{parent_path}")

    target = parent_path / project_slug
    if target.exists():
        # The target already has stuff. Three cases:
        #  - overwrite=True (repair flow): force-delete and re-clone
        #    regardless of who put files there. Caller already confirmed
        #    with the user via the audit modal.
        #  - scaffold_status='failed' carry-over: previous run partially
        #    populated it; clean and re-clone if our sentinel is there.
        #  - User stuffed their own files there: refuse to overwrite.
        sentinel = target / ".mycrew_scaffolded"
        if overwrite or sentinel.exists():
            why = ("repair mode（用户确认覆盖）" if overwrite
                   else "本工具历史克隆 — 删除后重克")
            await _progress(on_progress, "skip",
                            f"{target} 已存在且为 {why}")
            try:
                _safe_rmtree(target)
            except Exception as exc:
                raise ScaffoldError(
                    f"清理旧克隆失败：{target}（{exc}）"
                ) from exc
        else:
            raise ScaffoldError(
                f"目标目录已存在且不是本工具历史克隆，拒绝覆盖：{target}。"
                "请选择另一个父目录或换个项目名。"
            )

    # ── Clone via sparse-checkout to avoid pulling all 4 templates ──
    await _progress(on_progress, "git_clone",
                    f"从 {TEMPLATE_REPO_URL} 拉取 {sub_dir} 模板…")
    staging = parent_path / f".mycrew_clone_{project_slug}_{_short_id()}"
    try:
        # 2026-05-17: clone in two flavors with auto-retry. Phase 1 tries
        # the lightweight --filter=blob:none + sparse-checkout combo (200
        # MB instead of 600 MB total). If the checkout step ever trips on
        # an "RPC failed" / "Connection reset" (very common with flaky
        # CN proxies because checkout-time blob fetch is a second, long-
        # lived HTTP body), phase 2 falls back to a plain --depth 1
        # clone without filter — slower but a single continuous fetch
        # that survives intermittent resets better.
        sparse_failed = False
        last_err: ScaffoldError | None = None
        for attempt in range(1, 4):
            try:
                await _run_git([
                    "clone",
                    "--depth", "1",
                    "--filter=blob:none",
                    "--no-checkout",
                    "--branch", TEMPLATE_REPO_BRANCH,
                    TEMPLATE_REPO_URL,
                    str(staging),
                ])
                await _run_git(
                    ["sparse-checkout", "init", "--cone"],
                    cwd=staging,
                )
                await _run_git(
                    ["sparse-checkout", "set", sub_dir],
                    cwd=staging,
                )
                await _run_git(["checkout", TEMPLATE_REPO_BRANCH], cwd=staging)
                last_err = None
                break
            except ScaffoldError as exc:
                last_err = exc
                _safe_rmtree(staging)
                msg = str(exc).lower()
                if any(k in msg for k in (
                    "connection reset", "rpc failed", "early eof",
                    "fetch-pack", "could not fetch",
                )):
                    sparse_failed = True
                    if attempt < 3:
                        await _progress(
                            on_progress, "retry",
                            f"网络中断（attempt {attempt}/3），{2**attempt}s 后重试…",
                        )
                        await asyncio.sleep(2 ** attempt)
                        continue
                    # Final retry of sparse path also dead — break out
                    # to fallback below.
                    break
                # Non-network error → fail fast, no retry
                raise

        if last_err and sparse_failed:
            # Fallback: full --depth 1 clone (no blob filter). One
            # continuous fetch, much harder to half-disconnect midway.
            # We still sparse-checkout afterwards to avoid working-tree
            # bloat from sibling templates.
            await _progress(
                on_progress, "fallback",
                f"sparse-checkout 多次失败，改用全量浅克隆（更稳但更慢）…",
            )
            _safe_rmtree(staging)
            await _run_git([
                "clone",
                "--depth", "1",
                "--no-checkout",
                "--branch", TEMPLATE_REPO_BRANCH,
                TEMPLATE_REPO_URL,
                str(staging),
            ])
            await _run_git(
                ["sparse-checkout", "init", "--cone"],
                cwd=staging,
            )
            await _run_git(
                ["sparse-checkout", "set", sub_dir],
                cwd=staging,
            )
            await _run_git(["checkout", TEMPLATE_REPO_BRANCH], cwd=staging)

        sub_path = staging / sub_dir
        if not sub_path.exists():
            raise ScaffoldError(
                f"模板拉取成功但找不到子目录 {sub_dir}（仓库结构可能改了）"
            )

        # ── Move the subdir to its final home + drop the staging shell ──
        await _progress(on_progress, "rename",
                        f"重命名 {sub_dir} → {project_slug}")
        shutil.move(str(sub_path), str(target))
        # Wipe the now-empty .git + staging wrapper. The cloned project's
        # own .git would otherwise track the Templates repo, which the
        # user emphatically does NOT want — they should treat their new
        # project as a fresh repo (or not, but it shouldn't auto-tie to
        # the shared template upstream).
        _safe_rmtree(staging)
        # Drop the sentinel so a re-run can detect prior ownership.
        try:
            (target / ".mycrew_scaffolded").write_text(
                f"scaffolded by MyCrew (project_id={project_id})\n",
                encoding="utf-8",
            )
        except OSError:
            pass  # non-fatal
    except ScaffoldError:
        _safe_rmtree(staging)
        _safe_rmtree(target)
        raise
    except Exception as exc:
        _safe_rmtree(staging)
        _safe_rmtree(target)
        raise ScaffoldError(f"模板克隆未预期失败：{exc}") from exc

    await _progress(on_progress, "done", f"模板已部署到 {target}")
    log.info("template_clone.ok",
             project_id=project_id, template_id=template_id, target=str(target))
    return target


# ── Internal helpers ──────────────────────────────────────────────


# Per-call git http tweaks that make the clone tolerant of flaky
# proxies (Clash / V2Ray etc commonly used in CN). These get injected
# only for network-talking commands (clone / fetch / checkout). Tuning:
#   - http.postBuffer = 500 MB: don't switch to chunked encoding for big
#     bodies, fewer round-trips
#   - http.lowSpeedLimit / lowSpeedTime: tolerate up to 10 minutes of
#     trickle before aborting, instead of git's default ~20s @ 1B/s
_GIT_HTTP_TWEAKS = [
    "-c", "http.postBuffer=524288000",
    "-c", "http.lowSpeedLimit=0",
    "-c", "http.lowSpeedTime=600",
]
_NET_VERBS = {"clone", "fetch", "checkout", "pull", "remote"}


async def _run_git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run a git subprocess; raise ScaffoldError on non-zero exit.

    Network-touching verbs (clone / fetch / checkout / pull) get the
    proxy-tolerant http.* tweaks injected automatically. Local-only
    verbs (sparse-checkout init / set) don't need them so we skip to
    keep the command line readable in logs.
    """
    verb = args[0] if args else ""
    if verb in _NET_VERBS:
        cmd = ["git", *_GIT_HTTP_TWEAKS, *args]
    else:
        cmd = ["git", *args]
    log.debug("git.exec", cmd=" ".join(cmd), cwd=str(cwd) if cwd else None)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        snippet = (stderr.decode("utf-8", errors="replace")
                   or stdout.decode("utf-8", errors="replace"))[:600]
        raise ScaffoldError(
            f"git {args[0]} 失败 (exit {proc.returncode}): {snippet.strip()}"
        )
    return stdout.decode("utf-8", errors="replace")


def _safe_rmtree(p: Path) -> None:
    """Best-effort rmtree. Handles the Windows case where git marks
    pack files / index read-only — `shutil.rmtree(ignore_errors=True)`
    silently leaves the parent dir behind because individual unlinks
    fail with PermissionError. The onerror callback chmods the offender
    writable and retries."""
    if not p.exists():
        return
    import os
    import stat

    def _on_rm_error(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        except Exception:
            pass

    try:
        shutil.rmtree(p, onerror=_on_rm_error)
    except Exception:
        # Last-ditch retry with ignore_errors after a chmod-walk.
        try:
            for root, dirs, files in os.walk(p):
                for name in files:
                    try:
                        os.chmod(Path(root) / name, stat.S_IWRITE)
                    except Exception:
                        pass
            shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


def _short_id() -> str:
    """Cheap process-local nonce for staging dir uniqueness."""
    import secrets
    return secrets.token_hex(4)


async def _progress(hook, stage: str, message: str) -> None:
    """Invoke caller's progress hook if any; swallow its errors so a
    flaky broadcaster doesn't block the clone."""
    if hook is None:
        return
    try:
        result = hook(stage, message)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:  # noqa: BLE001
        log.warning("template_clone.progress_hook_failed",
                    stage=stage, error=str(exc))


# ── Status-column helpers (called by workflow_svc) ────────────────


async def mark_scaffold_status(project_id: str, status: str) -> None:
    """Update projects.scaffold_status. Valid values:
        pending      — template chosen but not yet cloned
        in_progress  — clone is running right now
        done         — clone succeeded; root_path points at child
        failed       — clone failed; user can retry
    """
    if status not in {"pending", "in_progress", "done", "failed"}:
        raise ValueError(f"invalid scaffold_status: {status!r}")
    await crud.update_by_id("projects", project_id, {
        "scaffold_status": status,
    })


async def update_project_root(project_id: str, new_root: Path) -> None:
    """Flip root_path to the freshly-cloned child dir. Called from
    workflow_svc after clone_template returns successfully."""
    await crud.update_by_id("projects", project_id, {
        "root_path": str(new_root),
    })


# ── Structure audit (2026-05-17) ──────────────────────────────────


# Per-template list of MINIMUM paths that must exist after a successful
# clone. Keep narrow — user decision 2026-05-17: only the 4 critical
# anchors below (not the full directory_skeleton, which includes
# recommended-but-optional dirs like Assets/Fonts/).
_AUDIT_REQUIRED_PATHS = (
    "Assets",  # The Unity Assets/ tree exists at all (any kind of project)
    "Packages/manifest.json",  # Package manifest — Unity refuses to open without it
    "ProjectSettings/ProjectVersion.txt",  # Editor version pin
    ".mycrew_scaffolded",  # Our own sentinel — drops after successful clone
)


def audit_against_skeleton(project_root: Path) -> list[str]:
    """Verify a scaffolded Unity project hasn't been corrupted /
    half-deleted between scaffold time and the first 开始 click.

    Returns a list of MISSING relative paths. Empty list = audit passed.
    Used by the new GET /workflow/projects/{id}/scaffold-audit route
    and by TaskHeader's first-start gate before allowing PM to run.

    template_id-agnostic for V1: all 4 Unity templates share the same
    4 critical anchors (Universal 2D/3D, AR Mobile, MR Core all use
    Assets + Packages/manifest.json + ProjectSettings/ProjectVersion.txt
    + the .mycrew_scaffolded marker). If template-specific audit rules
    are ever needed, add a per-template override in unity_templates.py.
    """
    if not project_root.exists() or not project_root.is_dir():
        # Whole root gone — report all paths missing so the repair flow
        # kicks in immediately.
        return list(_AUDIT_REQUIRED_PATHS)
    missing: list[str] = []
    for rel in _AUDIT_REQUIRED_PATHS:
        if not (project_root / rel).exists():
            missing.append(rel)
    return missing


__all__ = [
    "TEMPLATE_REPO_URL",
    "TEMPLATE_ID_TO_DIR",
    "ScaffoldError",
    "clone_template",
    "mark_scaffold_status",
    "update_project_root",
    "audit_against_skeleton",
]
