import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Project, Task } from "../../queries/useProjectQuery";
import {
  useStartProject,
  usePauseProject,
  useResumeProject,
  useRequiredMcps,
  useScaffoldAudit,
  useRepairScaffold,
  type RequiredMcp,
} from "../../queries/useWorkflowQuery";
import {
  useConnectMcpServer,
  useDisconnectMcpServer,
} from "../../queries/useMcpQuery";
import { useEvent } from "../../hooks/useEvent";
import { apiFetch, ApiError } from "../../net/api";
import { useDismissibleConfirm } from "../common/ConfirmDialog";
import { askPauseConfirm } from "../../lib/pauseConfirm";
import ScaffoldAuditModal from "./ScaffoldAuditModal";

const mcpDotColor: Record<string, string> = {
  connected: "#10b981",
  connecting: "#facc15",
  error: "#ef4444",
  disconnected: "#cbd5e1",
};

const mcpStatusLabel: Record<string, string> = {
  connected: "在线",
  connecting: "连接中",
  error: "错误",
  disconnected: "离线",
};

// Header redesign per Figma: NO background frame, NO border, info hugged
// to the top-left of the page. Drop the breadcrumb/chip clutter; surface
// just the selected task title + its progress, with the three project-
// level controls (pause-or-resume, 路径, 迭代) on the far right. Sidebar
// already shows where the user is, so the project name doesn't need its
// own breadcrumb row.

interface Props {
  project: Project;
  selectedTask: Task | null;
}

function PlayIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <polygon points="6,4 20,12 6,20" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="4" width="4" height="16" rx="1" />
      <rect x="14" y="4" width="4" height="16" rx="1" />
    </svg>
  );
}

function TaskHeader({ project, selectedTask }: Props) {
  const start = useStartProject();
  const pause = usePauseProject();
  const resume = useResumeProject();
  const confirm = useDismissibleConfirm();
  const connectMcp = useConnectMcpServer();

  // ── V5+ scaffold UI state (2026-05-17 redesign) ────────────────
  // The "config" modal moved to ProjectCard. TaskHeader now only owns:
  //   - the live "正在构建项目雏形" progress strip
  //   - the first-start structure audit + ScaffoldAuditModal popup
  const [scaffoldProgress, setScaffoldProgress] = useState<string>("");
  const [auditModalOpen, setAuditModalOpen] = useState(false);
  const [auditMissing, setAuditMissing] = useState<string[]>([]);
  const repairScaffold = useRepairScaffold();
  // Audit query — runs lazily when we manually refetch on first-start.
  // Don't auto-poll; cheap stat but not free.
  const scaffoldAudit = useScaffoldAudit(project.id);

  // MCP servers this project's tasks actually need (server-side walk
  // through tasks → agents → tools → mcp_servers). Refetched on every
  // mcp.status_changed WS event so the chips track real-time pool state.
  const { data: requiredMcps = [] } = useRequiredMcps(project.id);
  const qc = useQueryClient();
  const handleMcpEvent = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["workflow", "requiredMcps", project.id] });
  }, [qc, project.id]);
  useEvent("mcp.status_changed", handleMcpEvent);

  // Scaffold WS lifecycle — placed after `qc` so the invalidation
  // closure resolves. Each event invalidates the project query so the
  // row's scaffold_status / root_path stay fresh.
  useEvent("project.scaffold_progress", (msg) => {
    const payload = msg.payload as { project_id?: string; message?: string };
    if (payload?.project_id !== project.id) return;
    if (typeof payload.message === "string") setScaffoldProgress(payload.message);
  });
  useEvent("project.scaffold_complete", (msg) => {
    const payload = msg.payload as { project_id?: string };
    if (payload?.project_id !== project.id) return;
    setScaffoldProgress("");
    qc.invalidateQueries({ queryKey: ["project", project.id] });
  });
  useEvent("project.scaffold_failed", (msg) => {
    const payload = msg.payload as { project_id?: string; error?: string };
    if (payload?.project_id !== project.id) return;
    setScaffoldProgress("");
    qc.invalidateQueries({ queryKey: ["project", project.id] });
    alert(`项目雏形构建失败：${payload?.error ?? "未知错误"}`);
  });

  /** Walk the required-MCP list; for each offline one, call connect;
   *  after all attempts settle, refetch and try again up to
   *  `maxAttempts` rounds. Returns the names of the servers that are
   *  STILL offline at the end. */
  const connectOfflineMcps = useCallback(
    async (maxAttempts = 2): Promise<string[]> => {
      for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const fresh = await qc.fetchQuery<RequiredMcp[]>({
          queryKey: ["workflow", "requiredMcps", project.id],
        });
        const offline = (fresh ?? []).filter((m) => m.status !== "connected");
        if (offline.length === 0) return [];
        const tryConnect = offline.map((m) =>
          connectMcp.mutateAsync(m.server_id).catch(() => undefined),
        );
        await Promise.all(tryConnect);
      }
      // Final read after the last attempt's results have invalidated
      // the cache (the useConnectMcpServer onSuccess invalidates).
      const final = await qc.fetchQuery<RequiredMcp[]>({
        queryKey: ["workflow", "requiredMcps", project.id],
      });
      return (final ?? [])
        .filter((m) => m.status !== "connected")
        .map((m) => m.name);
    },
    [qc, project.id, connectMcp],
  );

  const isRunning = project.state === "running";
  const isPaused = project.state === "paused";
  const isReady = project.state === "ready";
  const isStalled = project.state === "stalled";
  const isTerminal = ["completed", "completed_with_warnings", "completed_with_issues", "aborted"]
    .includes(project.state);
  // V5+ scaffold gating: when scaffold_status is 'pending', clicking
  // 开始 must show the config modal first. While 'in_progress' the
  // start button reads as a busy spinner.
  const scaffoldStatus = project.scaffold_status ?? null;
  const scaffoldPending =
    scaffoldStatus === "pending" || scaffoldStatus === "failed";
  const scaffoldInProgress = scaffoldStatus === "in_progress";

  // Tasks in any of these statuses are blocking the workflow — the user
  // needs to manually fix them (edit detail / change agent / retry)
  // before the project can keep going. Surfacing them here lets the
  // start button intercept the click with a clear explanation instead
  // of silently no-op-ing or hitting a generic backend error.
  const BLOCKING_STATUSES = new Set(["failed", "validation_failed", "blocked"]);
  const blockingTasks = (project.tasks ?? []).filter(
    (t) => BLOCKING_STATUSES.has(t.status),
  );
  const isBlockedByTasks = isStalled || blockingTasks.length > 0;

  async function handlePrimary() {
    // V5+ scaffold gating (2026-05-17 redesign):
    //   - pending/failed: scaffold must be triggered on the home card,
    //     not here. Tell the user where to click.
    //   - in_progress: clicking is a no-op; the spinner conveys "wait".
    if (scaffoldPending) {
      alert(
        "项目尚未构建雏形。请回主页项目卡片【路径】按钮，"
        + "选好父目录 + 英文项目名后等下载完成，再回来启动。",
      );
      return;
    }
    if (scaffoldInProgress) return;

    // First-start structure audit. Runs only on Unity-template projects
    // (audit-applicable=true). If 4 critical anchors are missing, pop
    // the ScaffoldAuditModal instead of starting; user can repair from
    // there. We refetch on each click so a manual mid-session delete
    // gets caught too.
    if (isReady && project.template_id) {
      try {
        const auditResult = await scaffoldAudit.refetch();
        const data = auditResult.data;
        if (data?.applicable && data.missing.length > 0) {
          setAuditMissing(data.missing);
          setAuditModalOpen(true);
          return;
        }
      } catch (exc) {
        console.error("[TaskHeader] scaffold audit failed", exc);
        // Don't block start on audit error — fall through.
      }
    }

    // Stalled or has blocking tasks → tell the user to fix them first.
    // The watchdog parked the project here because something needs human
    // intervention; restarting without fixing it would just stall again.
    if (isBlockedByTasks && !isRunning && !isPaused) {
      const lines = blockingTasks.length > 0
        ? blockingTasks
            .slice(0, 5)
            .map((t) => `· ${t.title || "未命名"}（${t.status}）`)
            .join("\n")
        : "（看不到具体卡住的任务，但项目处于 stalled 状态）";
      const more = blockingTasks.length > 5
        ? `\n…还有 ${blockingTasks.length - 5} 个`
        : "";
      alert(
        `当前项目受阻，需要先人工疏通才能继续：\n\n${lines}${more}\n\n` +
        "在画布上点击卡住的任务卡片 → 编辑详情 / 改 Agent → 然后点任务上的【重试】键。\n" +
        "如果不确定原因，可以打开任务卡片上的 💬 Agent 对话，让诊断助手解释。",
      );
      return;
    }
    if (isReady) {
      // Pre-flight: refuse to start when any task has no executable
      // performer bound. PM v4 tasks bind via performer_kind +
      // performer_id; legacy / setup tasks still use the agent_id
      // column alone. A task is missing a performer only when BOTH
      // channels are empty — otherwise workflow_svc can dispatch.
      // Mirrors backend workflow_svc._start_locked exactly so the
      // friendly alert here and the wire-level rejection there agree.
      const tasks = project.tasks ?? [];
      const missing = tasks.filter((t) => {
        if (t.performer_kind === "crew") return !t.performer_id;
        return !t.agent_id && !t.performer_id;
      });
      if (missing.length > 0) {
        const lines = missing.map((t) => `· ${t.title || "未命名"}`).join("\n");
        alert(
          `以下任务尚未指定执行者（Agent/Crew），无法启动项目：\n\n${lines}\n\n请在画布上点击任务卡片 → 编辑 → 选择执行者。`,
        );
        return;
      }

      // Pre-flight: every required MCP must be connected before we
      // kick off, otherwise each task that needs (say) ComfyUI fails
      // one-by-one as it tries to call the tool — wasted tokens +
      // opaque "tool not found" errors. Auto-retry the connect 2x
      // before bothering the user — most "offline" cases are just
      // "haven't been told to connect yet since boot".
      const stillOffline = await connectOfflineMcps(2);
      if (stillOffline.length > 0) {
        alert(
          "以下项目所需的 MCP 服务器尝试连接两次后仍未连上，无法启动：\n\n" +
          stillOffline.map((n) => `· ${n}`).join("\n") +
          "\n\n请检查对应服务的本地进程是否在运行（ComfyUI / Unity Editor / Blender 等）。",
        );
        return;
      }
      try {
        await start.mutateAsync(project.id);
      } catch (exc) {
        // Backend rejected (e.g. DAG cycle / orphan dep / racing
        // agent-missing). Surface the message directly.
        alert((exc as Error).message ?? "启动失败");
      }
    } else if (isRunning) {
      // Stage G: warn that pause is cooperative — the in-flight task
      // (or Crew step) will finish before the project actually parks.
      // Dismissible so power users only see it once.
      const runningTasks = (project.tasks ?? []).filter(
        (t) => t.status === "running",
      );
      const shouldPause = await askPauseConfirm(
        confirm,
        runningTasks.length,
      );
      if (!shouldPause) return;
      try {
        await pause.mutateAsync(project.id);
      } catch (exc) {
        alert((exc as Error).message ?? "暂停失败");
      }
    } else if (isPaused) {
      // Surface resume failures — backend may 404 / 500 when state has
      // drifted (e.g. project finalized in the meantime). Silent failure
      // here looks like a dead button.
      try {
        await resume.mutateAsync(project.id);
      } catch (exc) {
        alert((exc as Error).message ?? "继续失败");
      }
    }
  }

  /** Handler for ScaffoldAuditModal's 「一键修复」 button. Fires the
   *  repair mutation (POST /scaffold-repair) and closes the modal —
   *  WS events drive the rest of the UI (spinner, progress text,
   *  eventual scaffold_complete). */
  async function handleRepair(): Promise<void> {
    setAuditModalOpen(false);
    setScaffoldProgress("正在重新下载…");
    try {
      await repairScaffold.mutateAsync(project.id);
    } catch (exc) {
      setScaffoldProgress("");
      alert((exc as Error).message ?? "修复失败");
    }
  }

  /** Open the project's root_path in the OS file explorer.
   *  Surfaces a clean alert when the path is missing or not configured
   *  instead of a generic failure toast. */
  async function handleOpenPath() {
    try {
      const res = await apiFetch<{ path: string }>(
        `/projects/${project.id}/open-root`,
        { method: "POST" },
      );
      void res;
    } catch (exc) {
      if (exc instanceof ApiError && exc.kind === "envelope") {
        alert(exc.message);
      } else {
        alert(`无法打开路径：${(exc as Error).message ?? exc}`);
      }
    }
  }

  // Task-level progress placeholder — once the backend exposes a real
  // per-task progress field, plug it in here.
  const taskProgress = (() => {
    if (!selectedTask) return 0;
    if (selectedTask.status === "done") return 100;
    if (selectedTask.status === "running") return 50;
    return 0;
  })();

  const primaryDisabled =
    start.isPending || pause.isPending || resume.isPending || scaffoldInProgress;
  const primaryTitle = scaffoldInProgress
    ? "正在构建项目雏形…"
    : scaffoldPending
      ? "项目尚未构建雏形 — 请在主页项目卡【路径】按钮配置"
      : isBlockedByTasks && !isRunning && !isPaused
        ? `项目受阻（${blockingTasks.length || "stalled"}）— 点击查看详情`
        : isReady
          ? "启动项目"
          : isRunning
            ? "暂停项目"
            : isPaused
              ? "继续项目"
              : "已结束";

  return (
    // No background, no border — sits directly on the page. Everything
    // hugs the top-LEFT in a single cluster per docs/figma/task.png:
    //   [Task title] [▬▬▬▬▬▬▬▬▬ N%] [⏸] [路径] [迭代]
    // No ml-auto / no flex-1 spacer — buttons stay tight against the
    // title block instead of getting pushed to the far right.
    <div className="flex items-center gap-3 px-5 pt-3 pb-2">
      {selectedTask ? (
        <h1
          className="truncate text-base font-semibold"
          style={{ color: "var(--color-ink-strong)" }}
          title={`${project.name} / ${selectedTask.title}`}
        >
          {selectedTask.title}
        </h1>
      ) : (
        <h1
          className="truncate text-base font-semibold"
          style={{ color: "var(--color-ink-muted)" }}
        >
          {project.name}
        </h1>
      )}

      {/* Inline progress bar + percentage — short, just enough to read
          quickly. Width 96px keeps the cluster compact.
          V5+ override: while scaffolding, the slot reads
          「正在构建项目雏形」 + the live WS progress message instead of
          the per-task progress percentage. */}
      {(scaffoldInProgress || selectedTask) && (
        <div className="flex items-center gap-1.5">
          {scaffoldInProgress ? (
            <>
              <div
                className="h-1 w-32 overflow-hidden rounded-full"
                style={{ backgroundColor: "var(--color-surface-alt)" }}
                title="正在构建项目雏形"
              >
                {/* Indeterminate progress — animate a band sliding
                    across the track since we don't have a discrete %
                    from the cloner. */}
                <div className="scaffold-progress-band h-full rounded-full" />
              </div>
              <span
                className="truncate text-[11px]"
                style={{
                  color: "var(--color-brand-500)",
                  maxWidth: "260px",
                }}
                title={scaffoldProgress || "正在构建项目雏形"}
              >
                正在构建项目雏形{scaffoldProgress ? ` · ${scaffoldProgress}` : "…"}
              </span>
            </>
          ) : selectedTask ? (
            <>
              <div
                className="h-1 w-24 overflow-hidden rounded-full"
                style={{ backgroundColor: "var(--color-surface-alt)" }}
                title={`任务进度 ${Math.round(taskProgress)}%`}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${taskProgress}%`,
                    backgroundColor: "var(--color-brand-500)",
                  }}
                />
              </div>
              <span
                className="text-[11px] tabular-nums"
                style={{ color: "var(--color-ink-muted)" }}
              >
                {Math.round(taskProgress)}%
              </span>
            </>
          ) : null}
        </div>
      )}

      {/* Action buttons — sit right after the progress cluster, NOT
          pushed to the right edge. Small gap between the progress
          block and the first button so it reads as a separate group. */}
      <div className="ml-1 flex items-center gap-2">
        {!isTerminal ? (
          <button
            onClick={handlePrimary}
            disabled={primaryDisabled}
            title={primaryTitle}
            className="flex h-7 w-7 items-center justify-center rounded-lg transition-colors disabled:opacity-50"
            style={{
              backgroundColor: "var(--color-card)",
              border: scaffoldInProgress
                ? "1px solid var(--color-brand-500)"
                : isBlockedByTasks && !isRunning && !isPaused
                  ? "1px solid #f59e0b"  // amber border = needs attention
                  : "1px solid var(--color-border-soft)",
              color: scaffoldInProgress
                ? "var(--color-brand-500)"
                : isBlockedByTasks && !isRunning && !isPaused
                  ? "#f59e0b"
                  : isRunning
                    ? "var(--color-brand-500)"
                    : "var(--color-ink-muted)",
            }}
          >
            {scaffoldInProgress ? (
              <span
                className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current"
                style={{ borderTopColor: "transparent" }}
              />
            ) : isRunning ? <PauseIcon /> : <PlayIcon />}
          </button>
        ) : (
          <span
            className="text-[10px] uppercase tracking-wide"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            已结束
          </span>
        )}

        <button
          onClick={handleOpenPath}
          className="rounded-lg px-3 py-1 text-xs transition-colors hover:opacity-80"
          style={{
            backgroundColor: "var(--color-card)",
            border: "1px solid var(--color-border-soft)",
            color: "var(--color-ink-label)",
          }}
          title="在资源管理器中打开项目根路径"
        >
          路径
        </button>

        <button
          className="rounded-lg px-3 py-1 text-xs transition-colors"
          style={{
            backgroundColor: "var(--color-card)",
            border: "1px solid var(--color-border-soft)",
            color: "var(--color-ink-label)",
          }}
          title="迭代（占位）"
        >
          迭代
        </button>
      </div>

      {/* Right-aligned MCP status chips for the servers this project's
          tasks actually need. ml-auto pushes the whole group to the
          right edge so the title cluster on the left isn't shoved
          around when the chip count grows. Same data the Start
          pre-flight reads — clicking a grey/red chip toggles connect,
          a green chip toggles disconnect. The whole row is hidden
          when the project needs no MCPs (pure-text tasks etc). */}
      {requiredMcps.length > 0 && (
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <span
            className="text-[11px]"
            style={{ color: "var(--color-ink-faint)" }}
            title="本项目运行所需的 MCP 服务器（任务用到的工具反推出来）"
          >
            所需 MCP
          </span>
          {requiredMcps.map((m) => (
            <RequiredMcpChip key={m.server_id} server={m} />
          ))}
          <ConnectAllButton
            disabled={requiredMcps.every((m) => m.status === "connected")}
            pending={connectMcp.isPending}
            onClick={async () => {
              const stillOffline = await connectOfflineMcps(2);
              if (stillOffline.length > 0) {
                alert(
                  "以下 MCP 尝试两次仍未连上：\n\n" +
                  stillOffline.map((n) => `· ${n}`).join("\n") +
                  "\n\n请检查对应服务的本地进程是否在运行。",
                );
              }
            }}
          />
        </div>
      )}

      {auditModalOpen && (
        <ScaffoldAuditModal
          missing={auditMissing}
          rootPath={project.root_path}
          onRepair={handleRepair}
          onCancel={() => setAuditModalOpen(false)}
        />
      )}
    </div>
  );
}

function ConnectAllButton({
  disabled,
  pending,
  onClick,
}: {
  disabled: boolean;
  pending: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || pending}
      className="rounded-full px-3 py-0.5 text-[11px] transition-opacity hover:opacity-80 disabled:opacity-40"
      style={{
        backgroundColor: "var(--color-brand-500)",
        color: "white",
      }}
      title={
        disabled
          ? "所有所需 MCP 已连接"
          : "尝试连接所有未在线的 MCP（最多重试 2 次）"
      }
    >
      {pending ? "连接中…" : "连接"}
    </button>
  );
}

function RequiredMcpChip({ server }: { server: RequiredMcp }) {
  const connect = useConnectMcpServer();
  const disconnect = useDisconnectMcpServer();
  const isOnline = server.status === "connected";
  const isPending = connect.isPending || disconnect.isPending;

  const handleClick = () => {
    if (isPending) return;
    if (isOnline) disconnect.mutate(server.server_id);
    else connect.mutate(server.server_id);
  };

  return (
    <button
      onClick={handleClick}
      disabled={isPending}
      title={
        `${server.name} (${mcpStatusLabel[server.status] ?? server.status})` +
        ` — 本项目用到 ${server.tools_used.length} 个工具` +
        (server.tools_used.length
          ? `: ${server.tools_used.slice(0, 5).join(", ")}` +
            (server.tools_used.length > 5 ? "…" : "")
          : "")
      }
      className="flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] transition-opacity hover:opacity-80 disabled:opacity-50"
      style={{
        backgroundColor: "var(--color-card)",
        border: "1px solid var(--color-border-soft)",
        color: "var(--color-ink-label)",
      }}
    >
      <span className="max-w-[80px] truncate">{server.name}</span>
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{
          backgroundColor: mcpDotColor[server.status] ?? mcpDotColor.disconnected,
        }}
      />
    </button>
  );
}

export default TaskHeader;
