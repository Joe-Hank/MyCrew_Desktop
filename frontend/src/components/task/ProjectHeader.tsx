import type { Project } from "../../queries/useProjectQuery";
import {
  useStartProject,
  usePauseProject,
  useResumeProject,
  useAbortProject,
} from "../../queries/useWorkflowQuery";
import { useState } from "react";

const STATE_LABEL: Record<string, string> = {
  ready: "就绪",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  completed_with_warnings: "完成(有警告)",
  completed_with_issues: "完成(有问题)",
  aborted: "已中止",
};

const STATE_COLOR: Record<string, string> = {
  ready: "bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  paused: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300",
  completed: "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
  completed_with_warnings: "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300",
  completed_with_issues: "bg-red-100 text-red-600 dark:bg-red-900 dark:text-red-300",
  aborted: "bg-red-100 text-red-600 dark:bg-red-900 dark:text-red-300",
};

function ProjectHeader({ project }: { project: Project }) {
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

  const primaryLabel = isReady ? "开始" : isRunning ? "暂停" : isPaused ? "继续" : "";
  const primaryDisabled = isTerminal || start.isPending || pause.isPending || resume.isPending;

  return (
    <div className="flex items-center justify-between border-b border-zinc-200 bg-white px-5 py-3 dark:border-zinc-700 dark:bg-zinc-900">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold">{project.name}</h1>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATE_COLOR[project.state] ?? STATE_COLOR.ready}`}>
          {STATE_LABEL[project.state] ?? project.state}
        </span>
        {project.root_path && (
          <span className="max-w-[200px] truncate text-[11px] text-zinc-400" title={project.root_path}>
            {project.root_path}
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        {/* Progress */}
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
            <div
              className="h-full rounded-full bg-blue-500 transition-all"
              style={{ width: `${project.progress_pct}%` }}
            />
          </div>
          <span className="text-[11px] text-zinc-500">
            {project.done_count ?? 0}/{project.task_count ?? 0}
          </span>
        </div>

        {/* Primary action */}
        {!isTerminal && (
          <button
            onClick={handlePrimary}
            disabled={primaryDisabled}
            className={`rounded px-3 py-1 text-xs font-medium text-white disabled:opacity-50 ${
              isRunning
                ? "bg-yellow-500 hover:bg-yellow-600"
                : "bg-blue-500 hover:bg-blue-600"
            }`}
          >
            {primaryLabel}
          </button>
        )}

        {/* Abort */}
        {(isRunning || isPaused) && (
          <>
            {showAbortConfirm ? (
              <div className="flex items-center gap-1">
                <span className="text-[11px] text-red-500">确认中止?</span>
                <button
                  onClick={handleAbort}
                  className="rounded bg-red-500 px-2 py-0.5 text-[10px] text-white"
                >
                  确认
                </button>
                <button
                  onClick={() => setShowAbortConfirm(false)}
                  className="rounded border border-zinc-300 px-2 py-0.5 text-[10px] dark:border-zinc-600"
                >
                  取消
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowAbortConfirm(true)}
                className="rounded border border-red-300 px-2 py-1 text-xs text-red-500 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
              >
                中止
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default ProjectHeader;
