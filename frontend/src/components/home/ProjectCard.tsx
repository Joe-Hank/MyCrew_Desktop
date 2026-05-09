import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Project } from "../../queries/useProjectQuery";
import { useCloneProject, useDeleteProject } from "../../queries/useProjectQuery";

const stateLabels: Record<string, string> = {
  ready: "未启动",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  completed_with_warnings: "完成(警告)",
  completed_with_issues: "完成(问题)",
  aborted: "已中止",
};

const stateColors: Record<string, string> = {
  ready: "bg-zinc-400",
  running: "bg-blue-500 animate-pulse",
  paused: "bg-yellow-500",
  completed: "bg-green-500",
  completed_with_warnings: "bg-yellow-500",
  completed_with_issues: "bg-red-500",
  aborted: "bg-zinc-500",
};

function ProjectCard({
  project,
  onStart,
}: {
  project: Project;
  onStart: (id: string) => void;
}) {
  const navigate = useNavigate();
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const cloneMut = useCloneProject();
  const deleteMut = useDeleteProject();

  const progress = project.progress_pct ?? 0;
  const taskInfo = project.task_count
    ? `${project.done_count ?? 0}/${project.task_count}`
    : "无任务";

  const isRunning = project.state === "running";
  const isTerminal = ["completed", "completed_with_warnings", "completed_with_issues", "aborted"].includes(project.state);

  function handleDelete() {
    if (deleteInput === project.name) {
      deleteMut.mutate({ id: project.id, name: project.name });
      setDeleteConfirm(false);
      setDeleteInput("");
    }
  }

  return (
    <div
      className="group relative flex cursor-pointer flex-col rounded-lg border border-zinc-200 bg-white p-4 transition-shadow hover:shadow-md dark:border-zinc-700 dark:bg-zinc-900"
      onClick={() => navigate(`/tasks/${project.id}`)}
    >
      {/* Header */}
      <div className="mb-2 flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${stateColors[project.state] ?? "bg-zinc-400"}`} />
          <h3 className="text-sm font-semibold leading-tight">{project.name}</h3>
        </div>
        <span className="text-xs text-zinc-400">
          {stateLabels[project.state] ?? project.state}
        </span>
      </div>

      {/* Progress */}
      <div className="mb-3">
        <div className="mb-1 flex justify-between text-xs text-zinc-500">
          <span>进度 {Math.round(progress)}%</span>
          <span>任务 {taskInfo}</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
          <div
            className="h-full rounded-full bg-blue-500 transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Meta */}
      <div className="mb-3 text-xs text-zinc-400">
        {project.created_at?.substring(0, 10)}
        {project.root_path && (
          <span className="ml-2 truncate" title={project.root_path}>
            {project.root_path}
          </span>
        )}
      </div>

      {/* Actions */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
      <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        {!isTerminal && (
          <button
            onClick={() => onStart(project.id)}
            className="rounded bg-blue-500 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-blue-600"
          >
            {progress > 0 && !isRunning ? "继续" : isRunning ? "暂停" : "开始"}
          </button>
        )}
        {isTerminal && (
          <span className="rounded bg-zinc-200 px-3 py-1 text-xs text-zinc-500 dark:bg-zinc-700">
            已结束
          </span>
        )}
        <button
          onClick={() => cloneMut.mutate(project.id)}
          disabled={cloneMut.isPending}
          className="rounded border border-zinc-300 px-2 py-1 text-xs transition-colors hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800"
        >
          复制
        </button>
        <button
          onClick={() => setDeleteConfirm(true)}
          className="rounded border border-red-200 px-2 py-1 text-xs text-red-500 transition-colors hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
        >
          删除
        </button>
      </div>

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-lg bg-white/95 p-4 dark:bg-zinc-900/95">
          <p className="mb-2 text-xs text-zinc-600 dark:text-zinc-300">
            输入项目名 <strong>{project.name}</strong> 确认删除
          </p>
          <input
            value={deleteInput}
            onChange={(e) => setDeleteInput(e.target.value)}
            className="mb-2 w-full rounded border border-zinc-300 px-2 py-1 text-xs dark:border-zinc-600 dark:bg-zinc-800"
            placeholder={project.name}
            autoFocus
          />
          <div className="flex gap-2">
            <button
              onClick={handleDelete}
              disabled={deleteInput !== project.name}
              className="rounded bg-red-500 px-3 py-1 text-xs text-white disabled:opacity-50"
            >
              确认删除
            </button>
            <button
              onClick={() => { setDeleteConfirm(false); setDeleteInput(""); }}
              className="rounded border border-zinc-300 px-3 py-1 text-xs dark:border-zinc-600"
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default ProjectCard;
