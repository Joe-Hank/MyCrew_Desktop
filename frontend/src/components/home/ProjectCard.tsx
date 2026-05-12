import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProject, useDeleteProject, type Project, type Task } from "../../queries/useProjectQuery";

const stateLabels: Record<string, string> = {
  ready: "未启动",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  completed_with_warnings: "完成(警告)",
  completed_with_issues: "完成(问题)",
  aborted: "已中止",
};

function primaryButtonLabel(state: string, progress: number): { text: string; tone: "primary" | "resume" } {
  if (state === "running") return { text: "暂停", tone: "primary" };
  if (state === "paused") return { text: "继续", tone: "resume" };
  if (progress > 0 && !["completed", "completed_with_warnings", "completed_with_issues", "aborted"].includes(state)) {
    return { text: "继续", tone: "resume" };
  }
  return { text: "开始", tone: "primary" };
}

function ProjectCard({
  project,
  onStart,
}: {
  project: Project;
  onStart: (id: string) => void;
}) {
  const navigate = useNavigate();
  const { data: detail } = useProject(project.id);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const deleteMut = useDeleteProject();

  const progress = project.progress_pct ?? 0;
  const tasks = detail?.tasks ?? [];
  const isTerminal = ["completed", "completed_with_warnings", "completed_with_issues", "aborted"].includes(project.state);
  const isRunning = project.state === "running";
  const isReady = project.state === "ready";
  const btn = primaryButtonLabel(project.state, progress);

  const dateStr = project.created_at?.substring(0, 10) ?? "";

  function handleDelete() {
    if (deleteInput === project.name) {
      deleteMut.mutate({ id: project.id, name: project.name });
      setDeleteConfirm(false);
      setDeleteInput("");
    }
  }

  return (
    <div
      className="group relative flex h-full cursor-pointer flex-col rounded-[10px] bg-white p-4 transition-shadow"
      style={{
        boxShadow: isRunning
          ? "0 0 16px 3px rgba(12, 140, 233, 0.28)"
          : "0 1px 2px rgba(0,0,0,0.04)",
        border: "1px solid var(--color-border-soft)",
      }}
      onClick={() => navigate(`/tasks/${project.id}`)}
    >
      {/* Header */}
      <div
        className="mb-1 flex items-start justify-between"
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <h3
          className="truncate text-base font-semibold leading-tight"
          style={{ color: "var(--color-ink-muted)" }}
          title={project.name}
        >
          {project.name}
        </h3>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setDeleteConfirm(true);
          }}
          className="ml-2 shrink-0 rounded p-1 transition-colors hover:bg-zinc-100"
          title="删除"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            style={{ color: "var(--color-ink-ghost)" }}>
            <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
          </svg>
        </button>
      </div>

      {/* Meta: date + progress */}
      <div
        className="mb-2 flex items-center justify-between text-[11px]"
        style={{ color: "var(--color-ink-muted)" }}
      >
        <span>{dateStr}</span>
        <span>{Math.round(progress)}%</span>
      </div>

      {/* Progress bar */}
      <div
        className="mb-3 h-1.5 w-full overflow-hidden rounded-full"
        style={{ backgroundColor: "var(--color-surface-alt)" }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${progress}%`,
            backgroundColor: "var(--color-brand-500)",
          }}
        />
      </div>

      {/* Actions row */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
      <div className="mb-3 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        {!isTerminal ? (
          <button
            onClick={() => onStart(project.id)}
            className="flex-1 rounded-lg py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
            style={{
              backgroundColor: btn.tone === "resume" ? "#d39a3b" : "var(--color-brand-500)",
            }}
          >
            {btn.text}
          </button>
        ) : (
          <button
            disabled
            className="flex-1 cursor-not-allowed rounded-lg py-2 text-sm"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-disabled)",
            }}
          >
            已结束
          </button>
        )}

        <PathButton
          locked={!!project.root_path}
          configured={!!project.root_path}
          onClick={(e) => {
            e.stopPropagation();
            // TODO: open path picker
          }}
        />

        <button
          onClick={(e) => {
            e.stopPropagation();
            // TODO: open iterate flow
          }}
          disabled={isReady}
          className="rounded-lg border bg-white px-3 py-2 text-sm transition-colors disabled:opacity-50"
          style={{
            borderColor: "var(--color-border-soft)",
            color: isReady ? "var(--color-ink-disabled)" : "var(--color-ink-label)",
          }}
          title="迭代"
        >
          迭代
        </button>
      </div>

      {/* State label */}
      <div
        className="mb-2 text-[10px] uppercase tracking-wide"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        {stateLabels[project.state] ?? project.state}
      </div>

      {/* Task pills list */}
      <div className="flex-1 space-y-2 overflow-y-auto pr-1">
        {tasks.length === 0 ? (
          <div
            className="rounded-lg py-3 text-center text-[11px]"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-ghost)",
            }}
          >
            无任务
          </div>
        ) : (
          tasks.map((task, idx) => <TaskPill key={task.id} task={task} index={idx} />)
        )}
      </div>

      {/* Delete confirm overlay */}
      {deleteConfirm && (
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
        <div
          className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-[10px] bg-white/95 p-4"
          onClick={(e) => e.stopPropagation()}
        >
          <p className="mb-2 text-xs" style={{ color: "var(--color-ink-soft)" }}>
            输入项目名 <strong>{project.name}</strong> 确认删除
          </p>
          <input
            value={deleteInput}
            onChange={(e) => setDeleteInput(e.target.value)}
            className="mb-3 w-full rounded border px-2 py-1 text-xs"
            style={{ borderColor: "var(--color-border-soft)" }}
            placeholder={project.name}
            autoFocus
          />
          <div className="flex gap-2">
            <button
              onClick={handleDelete}
              disabled={deleteInput !== project.name}
              className="rounded-lg bg-red-500 px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              确认删除
            </button>
            <button
              onClick={() => {
                setDeleteConfirm(false);
                setDeleteInput("");
              }}
              className="rounded-lg border bg-white px-3 py-1.5 text-xs"
              style={{ borderColor: "var(--color-border-soft)" }}
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PathButton({
  locked,
  configured,
  onClick,
}: {
  locked: boolean;
  configured: boolean;
  onClick: (e: React.MouseEvent) => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 rounded-lg border bg-white px-3 py-2 text-sm transition-colors hover:bg-zinc-50"
      style={{
        borderColor: "var(--color-border-soft)",
        color: configured ? "var(--color-ink-label)" : "var(--color-ink-disabled)",
      }}
      title={configured ? "已配置路径" : "配置路径"}
    >
      {locked && (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="11" width="18" height="11" rx="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      )}
      路径
    </button>
  );
}

function TaskPill({ task, index }: { task: Task; index: number }) {
  const agentLabel = task.agent_id ? task.agent_id.replace(/^agent_/, "") : "未分配";
  const statusDot: Record<string, string> = {
    pending: "#cbd5e1",
    running: "var(--color-brand-500)",
    done: "#10b981",
    failed: "#ef4444",
    validation_failed: "#f59e0b",
    aborted: "#737373",
    blocked: "#a78bfa",
    paused: "#facc15",
  };

  return (
    <div
      className="rounded-lg px-3 py-2"
      style={{ backgroundColor: "var(--color-surface-alt)" }}
    >
      <div className="flex items-start gap-2">
        <span
          className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: statusDot[task.status] ?? "#cbd5e1" }}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-medium" style={{ color: "var(--color-ink-soft)" }}>
            {`Task${index + 1}. ${task.title || "未命名"}`}
          </div>
          <div className="flex items-center gap-1.5 text-[10px]" style={{ color: "var(--color-ink-faint)" }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
            <span className="truncate">{agentLabel}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProjectCard;
