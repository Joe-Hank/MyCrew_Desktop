import type { Project, Task } from "../../queries/useProjectQuery";
import {
  useStartProject,
  usePauseProject,
  useResumeProject,
} from "../../queries/useWorkflowQuery";
import { apiFetch, ApiError } from "../../net/api";
import { useDismissibleConfirm } from "../common/ConfirmDialog";
import { askPauseConfirm } from "../../lib/pauseConfirm";

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

  const isRunning = project.state === "running";
  const isPaused = project.state === "paused";
  const isReady = project.state === "ready";
  const isStalled = project.state === "stalled";
  const isTerminal = ["completed", "completed_with_warnings", "completed_with_issues", "aborted"]
    .includes(project.state);

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
      pause.mutate(project.id);
    } else if (isPaused) resume.mutate(project.id);
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

  const primaryDisabled = start.isPending || pause.isPending || resume.isPending;
  const primaryTitle = isBlockedByTasks && !isRunning && !isPaused
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
          quickly. Width 96px keeps the cluster compact. */}
      {selectedTask && (
        <div className="flex items-center gap-1.5">
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
              border: isBlockedByTasks && !isRunning && !isPaused
                ? "1px solid #f59e0b"  // amber border = needs attention
                : "1px solid var(--color-border-soft)",
              color: isBlockedByTasks && !isRunning && !isPaused
                ? "#f59e0b"
                : isRunning
                  ? "var(--color-brand-500)"
                  : "var(--color-ink-muted)",
            }}
          >
            {isRunning ? <PauseIcon /> : <PlayIcon />}
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
    </div>
  );
}

export default TaskHeader;
