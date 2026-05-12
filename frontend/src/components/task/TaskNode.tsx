import type { Task } from "../../queries/useProjectQuery";

export type TaskAction =
  | { kind: "edit"; task: Task }
  | { kind: "pause"; task: Task }
  | { kind: "retry"; task: Task }
  | { kind: "agent_chat"; task: Task }
  | { kind: "view_io"; task: Task; direction: "in" | "out" };

const STATUS_DOT: Record<string, string> = {
  pending: "#cbd5e1",
  running: "var(--color-brand-500)",
  paused: "#facc15",
  done: "#10b981",
  failed: "#ef4444",
  aborted: "#737373",
  validation_failed: "#f59e0b",
  blocked: "#a78bfa",
};

function TaskNode({
  task,
  index,
  selected,
  projectRunning,
  onSelect,
  onAction,
}: {
  task: Task;
  index: number;
  selected: boolean;
  projectRunning: boolean;
  onSelect: (task: Task) => void;
  onAction: (action: TaskAction) => void;
}) {
  const dotColor = STATUS_DOT[task.status] ?? STATUS_DOT.pending;

  const canEdit = !projectRunning && task.status !== "running";
  const canPause = task.status === "running";
  const canRetry = ["done", "failed", "validation_failed", "aborted"].includes(task.status) && !projectRunning;
  const canChat = ["failed", "validation_failed", "blocked"].includes(task.status);

  const needsInput = task.status === "blocked" || task.status === "validation_failed";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(task)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect(task);
      }}
      className="relative w-[200px] cursor-pointer rounded-lg bg-white p-3 transition-shadow hover:shadow-md"
      style={{
        border: `1px solid ${selected ? "var(--color-brand-500)" : "var(--color-border-soft)"}`,
        boxShadow: selected ? "0 0 0 3px rgba(12, 140, 233, 0.12)" : "0 1px 2px rgba(0, 0, 0, 0.04)",
      }}
    >
      {/* Status indicator dot - top-right corner if needs input */}
      {needsInput && (
        <div
          className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full text-[10px] text-white"
          style={{ backgroundColor: "#f59e0b" }}
          title="需要用户介入"
        >
          !
        </div>
      )}

      {/* Title */}
      <div className="mb-1 flex items-center gap-1.5">
        <span
          className="inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: dotColor }}
        />
        <h3
          className="truncate text-sm font-semibold"
          style={{ color: "var(--color-ink-soft)" }}
        >
          Task{index + 1}. {task.title || "未命名"}
        </h3>
      </div>

      {/* Agent line */}
      <div
        className="mb-2 flex items-center gap-1 text-[10px]"
        style={{ color: "var(--color-ink-faint)" }}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
        <span className="truncate">{task.agent_id ? task.agent_id.slice(-12) : "未指定 Agent"}</span>
      </div>

      {/* Detail */}
      {task.detail && (
        <p
          className="mb-2 line-clamp-3 text-[11px] leading-snug"
          style={{ color: "var(--color-ink-muted)" }}
        >
          {task.detail}
        </p>
      )}

      {/* Bottom icon bar (5 icons) */}
      <div
        className="flex items-center justify-between pt-2"
        style={{ borderTop: "1px solid var(--color-border-soft)" }}
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <IconBtn
          title="编辑"
          disabled={!canEdit}
          onClick={() => onAction({ kind: "edit", task })}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
          </svg>
        </IconBtn>

        <IconBtn
          title={canPause ? "暂停" : "暂停（不可用）"}
          disabled={!canPause}
          onClick={() => onAction({ kind: "pause", task })}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="6" y="4" width="4" height="16" rx="1" />
            <rect x="14" y="4" width="4" height="16" rx="1" />
          </svg>
        </IconBtn>

        <IconBtn
          title="重试"
          disabled={!canRetry}
          onClick={() => onAction({ kind: "retry", task })}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round">
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
        </IconBtn>

        <IconBtn
          title="对话"
          disabled={!canChat}
          onClick={() => onAction({ kind: "agent_chat", task })}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </IconBtn>

        <IconBtn
          title="查看输入/输出"
          onClick={() => onAction({ kind: "view_io", task, direction: "out" })}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
        </IconBtn>
      </div>
    </div>
  );
}

function IconBtn({
  title,
  disabled,
  onClick,
  children,
}: {
  title: string;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="rounded p-1 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-30"
      style={{ color: "var(--color-ink-muted)" }}
    >
      {children}
    </button>
  );
}

export default TaskNode;
