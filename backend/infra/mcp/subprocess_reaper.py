"""Force-kill leftover MCP subprocesses (Windows --reload survivors).

Why this exists: the MCP SDK's `stdio_client` manages subprocess lifecycle
internally via an AsyncExitStack. On Windows ProactorEventLoop the
context-manager `__aexit__` sometimes never returns — `wait_for(aclose,
timeout=5)` raises TimeoutError, our code logs a warning, and the
subprocess (npx / uvx) is orphaned. With `uvicorn --reload`, every
backend reload leaves a fresh batch of zombies; the next boot's `npx -y
…-mcp` blocks indefinitely on the npm cache lock those zombies hold.

This module provides two helpers built on psutil:

- `reap_my_subprocesses(...)`: walk THIS python's child tree (the
  workers spawned by mcp_pool.start) and SIGKILL anything left after
  the polite SDK disconnect. Called from mcp_pool.stop().

- `sweep_orphan_mcp_subprocesses(server_configs)`: at boot, scan all
  node/uvx/uv processes whose cmdline matches one of our configured
  MCP server signatures AND that started before this Python — those
  are cross-boot orphans. Kill them so new spawns don't deadlock.

Both helpers are best-effort: every kill is wrapped in try/except so a
single AccessDenied / NoSuchProcess doesn't break the sweep.
"""
from __future__ import annotations

import json
import os
from typing import Any

import psutil
import structlog

log = structlog.get_logger()

# Process names we might spawn as MCP children (Windows .exe suffixed).
_TARGET_NAMES = {"node.exe", "uvx.exe", "uv.exe", "node", "uvx", "uv"}


def _proc_name(p: psutil.Process) -> str:
    try:
        return (p.name() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _kill_proc(p: psutil.Process) -> bool:
    """Polite terminate, then SIGKILL the survivors. Returns True if
    the process is gone after the attempt."""
    try:
        p.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True
    try:
        p.wait(timeout=1.5)
        return True
    except psutil.TimeoutExpired:
        pass
    try:
        p.kill()
        p.wait(timeout=1.0)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True
    except psutil.TimeoutExpired:
        return False


def reap_my_subprocesses(reason: str = "shutdown") -> int:
    """Walk this python's child tree and kill any node/uvx/uv children.

    Called from mcp_pool.stop() after the polite SDK disconnect — those
    are the MCP server subprocesses the SDK's AsyncExitStack failed to
    clean up. WatchFiles --reload's shutdown hook used to skip this,
    leaving one batch of orphans per reload.

    Returns the count killed (informational).
    """
    try:
        me = psutil.Process(os.getpid())
    except psutil.NoSuchProcess:
        return 0

    try:
        children = me.children(recursive=True)
    except psutil.NoSuchProcess:
        return 0

    targets = [c for c in children if _proc_name(c) in _TARGET_NAMES]
    if not targets:
        return 0

    killed = 0
    for p in targets:
        if _kill_proc(p):
            killed += 1
    log.info("mcp.reaper.subprocesses_killed",
             reason=reason, killed=killed, total=len(targets))
    return killed


def _extract_mcp_signature(server_config: dict) -> set[str]:
    """Return distinctive cmdline tokens we'd expect to see in an MCP
    child process spawned from this config. For stdio servers, that's
    any arg containing '-mcp' (the canonical package-name convention,
    e.g. 'comfyui-mcp', 'figma-developer-mcp', 'mcp-server-git')."""
    if server_config.get("transport") != "stdio":
        return set()
    args_raw = server_config.get("args") or "[]"
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except (json.JSONDecodeError, TypeError):
            return set()
    else:
        args = args_raw or []
    sigs = set()
    for a in args:
        if not isinstance(a, str):
            continue
        lowered = a.lower()
        if "-mcp" in lowered or "mcp-server" in lowered:
            sigs.add(lowered)
    return sigs


def sweep_orphan_mcp_subprocesses(server_configs: list[dict]) -> int:
    """Cross-boot orphan sweep: kill node/uvx/uv processes whose
    cmdline contains one of our MCP signatures AND that started before
    this Python (a previous boot's children, re-parented after that
    boot crashed/reloaded without cleanup).

    Cmdline-pattern matching is narrowed by package signature (e.g.
    'figma-developer-mcp') so we don't touch unrelated npx invocations
    the user might be running for other projects.
    """
    sigs: set[str] = set()
    for s in server_configs:
        sigs.update(_extract_mcp_signature(s))
    if not sigs:
        return 0

    try:
        me = psutil.Process(os.getpid())
        my_start = me.create_time()
    except psutil.NoSuchProcess:
        return 0

    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in _TARGET_NAMES:
                continue
            # Only kill ones older than this python — anything newer
            # might be our own newly-spawned children.
            ct = proc.info.get("create_time")
            if ct is None or ct >= my_start:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if not any(sig in cmdline for sig in sigs):
                continue
            if _kill_proc(proc):
                killed += 1
                log.info("mcp.reaper.orphan_killed",
                         pid=proc.pid, name=name,
                         age_s=int(my_start - ct))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if killed:
        log.info("mcp.reaper.orphan_sweep_complete", killed=killed)
    return killed


def _tcp_probe(host: str, port: int, timeout_s: float = 2.0) -> bool:
    """Quick synchronous TCP connect probe. Returns True if the port
    accepts a connection within `timeout_s`. Used to fail-fast on
    HTTP MCP servers whose backing daemon isn't running (e.g. Unity
    Editor not open → port 8090 refuses → no point waiting 30s on
    the SDK's streamable_http_client to time out)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    try:
        s.connect((host, port))
        return True
    except (OSError, socket.timeout):
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def http_url_reachable(url: str, timeout_s: float = 2.0) -> bool:
    """Parse a URL → host:port → run _tcp_probe. Used by _safe_connect
    before letting HttpMCPClient.connect attempt the full SDK handshake."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return _tcp_probe(host, port, timeout_s)
