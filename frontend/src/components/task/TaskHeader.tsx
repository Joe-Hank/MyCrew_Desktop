import { useNavigate } from "react-router-dom";
import type { Project, Task } from "../../queries/useProjectQuery";
import {
  useStartProject,
  usePauseProject,
  useResumeProject,
  useAbortProject,
} from "../../queries/useWorkflowQuery";
import { useState } from "react";

const PROJECT_STATE_LABEL: Record<string, string> = {
  ready: "就绪",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  completed_with_warnings: "完成(警告)",
  completed_with_issues: "完成(问题)",
  aborted: "已中止",
};

const TASK_STATE_LABEL: Record<string, string> = {
  pending: "待执行",
  running: "运行中",
  paused: "已暂停",
  done: "已完成",
  failed: "失败",
  validation_failed: "验证失败",
  aborted: "已中止",
  blocked: "阻塞",
};

interface Props {
  project: Project;
  selectedTask: Task | null;
}

function TaskHeader({ project, selectedTask }: Props) {
  const navigate = useNavigate();
  const start = useStartProject();
  const pause = usePauseProject();
  const resume = useResumeProject();
  const abort = useAbortProject();
  const [showAbortConfirm, setShowAbortConfirm] = useState(false);

  const isRunning = project.state === "running";
  const isPaused = project.state === "paused";
  const isReady = project.state === "ready";
  const isTerminal = ["completed", "completed_with_warnings", "completed_with_issues", "aborted"].includes(project.state);

  function handlePrimary() {
    if (isReady) start.mutate(project.id);
    else if (isRunning) pause.mutate(project.id);
    else if (isPaused) resume.mutate(project.id);
  }

  function handleAbort() {
    abort.mutate({ projectId: project.id, reason: "user abort" });
    setShowAbortConfirm(false);
  }

  // Task-level computed: progress, action label
  const taskProgress = (() => {
    if (!selectedTask) return 0;
    if (selectedTask.status === "done") return 100;
    if (selectedTask.status === "running") return 50;
    return 0;
  })();

  return (
    <div
      className="flex flex-col"
      style={{
        backgroundColor: "var(--color-card)",
        borderBottom: "1px solid var(--color-border-soft)",
      }}
    >
      {/* Top thin breadcrumb */}
      <div className="flex items-center gap-2 px-5 pt-2 text-[11px]" style={{ color: "var(--color-ink-ghost)" }}>
        <button
          onClick={() => navigate("/")}
          className="hover:underline"
        >
          首页
        </button>
        <span>/</span>
        <span>{project.name}</span>
        <span
          className="rounded px-1.5 py-0.5 text-[10px]"
          style={{
            backgroundColor: "var(--color-surface-alt)",
            color: "var(--color-ink-faint)",
          }}
        >
          {PROJECT_STATE_LABEL[project.state] ?? project.state}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {/* Project-level progress mini */}
          <div
            className="h-1 w-20 overflow-hidden rounded-full"
            style={{ backgroundColor: "var(--color-surface-alt)" }}
            title={`项目进度 ${project.progress_pct}%`}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${project.progress_pct}%`,
                backgroundColor: "var(--color-brand-500)",
              }}
            />
          </div>
          <span className="tabular-nums">
            {project.done_count ?? 0}/{project.task_count ?? 0}
          </span>

          {!isTerminal && (
            <button
              onClick={handlePrimary}
              disabled={start.isPending || pause.isPending || resume.isPending}
              className="rounded-md px-2 py-0.5 text-[10px] font-medium text-white disabled:opacity-50"
              style={{ backgroundColor: "var(--color-brand-500)" }}
            >
              {isReady ? "启动项目" : isRunning ? "暂停项目" : "继续项目"}
            </button>
          )}
          {(isRunning || isPaused) &&
            (showAbortConfirm ? (
              <span className="flex items-center gap-1">
                <span className="text-red-500">中止?</span>
                <button onClick={handleAbort} className="rounded bg-red-500 px-1.5 py-0.5 text-white">
                  确认
                </button>
                <button
                  onClick={() => setShowAbortConfirm(false)}
                  className="rounded border px-1.5 py-0.5"
                  style={{ borderColor: "var(--color-border-soft)" }}
                >
                  取消
                </button>
              </span>
            ) : (
              <button
                onClick={() => setShowAbortConfirm(true)}
                className="rounded border px-1.5 py-0.5 text-red-500"
                style={{ borderColor: "var(--color-border-soft)" }}
              >
                中止
              </button>
            ))}
        </div>
      </div>

      {/* Main row: selected task + actions */}
      <div className="flex items-center gap-3 px-5 py-3">
        {selectedTask ? (
          <>
            <h1
              className="truncate text-lg font-semibold"
              style={{ color: "var(--color-ink-strong)" }}
              title={selectedTask.title}
            >
              {selectedTask.title}
            </h1>
            <span className="text-sm tabular-nums" style={{ color: "var(--color-ink-muted)" }}>
              {Math.round(taskProgress)}%
            </span>
            <span
              className="rounded px-1.5 py-0.5 text-[10px]"
              style={{
                backgroundColor: "var(--color-surface-alt)",
                color: "var(--color-ink-faint)",
              }}
            >
              {TASK_STATE_LABEL[selectedTask.status] ?? selectedTask.status}
            </span>

            <div className="ml-auto flex items-center gap-2">
              <button
                className="flex items-center gap-1 rounded-lg border bg-white px-3 py-1.5 text-sm transition-colors hover:bg-zinc-50"
                style={{ borderColor: "var(--color-border-soft)", color: "var(--color-ink-label)" }}
                title="暂停任务"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="6" y="4" width="4" height="16" rx="1" />
                  <rect x="14" y="4" width="4" height="16" rx="1" />
                </svg>
              </button>
              <button
                className="rounded-lg border bg-white px-3 py-1.5 text-sm transition-colors hover:bg-zinc-50"
                style={{ borderColor: "var(--color-border-soft)", color: "var(--color-ink-label)" }}
              >
                路径
              </button>
              <button
                className="rounded-lg border bg-white px-3 py-1.5 text-sm transition-colors hover:bg-zinc-50"
                style={{ borderColor: "var(--color-border-soft)", color: "var(--color-ink-label)" }}
              >
                迭代
              </button>
            </div>
          </>
        ) : (
          <h1
            className="text-lg font-semibold"
            style={{ color: "var(--color-ink-muted)" }}
          >
            {project.name}
          </h1>
        )}
      </div>
    </div>
  );
}

export default TaskHeader;
