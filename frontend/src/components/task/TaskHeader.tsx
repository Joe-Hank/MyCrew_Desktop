import type { Project, Task } from "../../queries/useProjectQuery";
import {
  useStartProject,
  usePauseProject,
  useResumeProject,
} from "../../queries/useWorkflowQuery";

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

  const isRunning = project.state === "running";
  const isPaused = project.state === "paused";
  const isReady = project.state === "ready";
  const isTerminal = ["completed", "completed_with_warnings", "completed_with_issues", "aborted"]
    .includes(project.state);

  function handlePrimary() {
    if (isReady) start.mutate(project.id);
    else if (isRunning) pause.mutate(project.id);
    else if (isPaused) resume.mutate(project.id);
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
  const primaryTitle = isReady
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
              border: "1px solid var(--color-border-soft)",
              color: isRunning ? "var(--color-brand-500)" : "var(--color-ink-muted)",
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
          className="rounded-lg px-3 py-1 text-xs transition-colors"
          style={{
            backgroundColor: "var(--color-card)",
            border: "1px solid var(--color-border-soft)",
            color: "var(--color-ink-label)",
          }}
          title="项目根路径（开发中）"
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
