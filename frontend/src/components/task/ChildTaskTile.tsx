import type { Task } from "../../queries/useProjectQuery";
import { STATUS_DOT, type TaskAction } from "./TaskNode";

/** Compact tile for a single fan-out child task. Lives inside the parent
 *  Crew node's expanded parallel row. Same outer dimensions as
 *  SubAgentCard (240px wide) so the row reads as a continuation of the
 *  step pipeline — per V5 spec "并发任务子卡片与顺序卡片的展示形式一致".
 *
 *  Behaviour:
 *   - Click body → selects the child task (TaskHeader / drawer switch).
 *   - Status dot + halo mirrors TaskNode's status mapping.
 *   - Action row mirrors TaskNode (edit / retry / view_failure / view_io)
 *     but gated on the child task's individual status.
 */
export interface ChildTaskTileProps {
  task: Task;
  selected: boolean;
  projectRunning: boolean;
  onSelect: (task: Task) => void;
  onAction: (action: TaskAction) => void;
}

const STATUS_TEXT_ZH: Record<string, string> = {
  pending: "等待",
  running: "进行中",
  paused: "暂停",
  done: "完成",
  failed: "失败",
  aborted: "已中止",
  validation_failed: "校验失败",
  blocked: "受阻",
  stalled: "停滞",
};

export default function ChildTaskTile({
  task,
  selected,
  projectRunning,
  onSelect,
  onAction,
}: ChildTaskTileProps) {
  const dotColor = STATUS_DOT[task.status] ?? STATUS_DOT.pending;
  const statusText = STATUS_TEXT_ZH[task.status] ?? task.status;

  const isRunning = task.status === "running";
  const isStalled = task.status === "stalled";
  const isFailed =
    task.status === "failed" || task.status === "validation_failed";

  // Action gating mirrors TaskNode but for the child's own state — a
  // child can be retried independently of its siblings.
  const isFailureState = isFailed || task.status === "aborted" || isStalled;
  const canRetry =
    isFailureState || (task.status === "done" && !projectRunning);
  const canChat =
    isFailed || task.status === "blocked" || isStalled;
  const canEdit = !projectRunning && task.status !== "running";

  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onSelect(task);
      }}
      className={
        "relative w-[240px] shrink-0 cursor-pointer rounded-lg p-3 transition-shadow "
        + (isRunning ? "task-halo-running " : "")
        + (isStalled || isFailed ? "task-halo-stalled " : "")
      }
      style={{
        backgroundColor: "var(--color-card)",
        border: `1px solid ${
          selected
            ? "var(--color-brand-500)"
            : isRunning
              ? "var(--color-brand-500)"
              : "var(--color-border-soft)"
        }`,
        boxShadow:
          isRunning || isStalled || isFailed
            ? undefined
            : "0 1px 2px rgba(0, 0, 0, 0.04)",
      }}
      title={task.last_error || ""}
    >
      {/* Header — status dot + title. No left "Task N" badge because
          children aren't part of the top-level wave numbering. */}
      <div className="mb-2 flex items-center gap-1.5">
        <span
          className="inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: dotColor }}
        />
        <span
          className="min-w-0 flex-1 truncate text-sm font-semibold"
          style={{ color: "var(--color-ink-soft)" }}
          title={task.title}
        >
          {task.title}
        </span>
      </div>

      {/* Status / progress line — matches SubAgentCard's secondary row. */}
      <div
        className="mb-3 flex items-center gap-1.5 text-[11px]"
        style={{ color: "var(--color-ink-faint)" }}
      >
        <span className="truncate">{statusText}</span>
      </div>

      {/* Action row */}
      <div
        className="flex items-center justify-between gap-0.5 pt-1.5"
        style={{ borderTop: "1px solid var(--color-border-soft)" }}
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <MiniBtn
          title="编辑"
          disabled={!canEdit}
          onClick={() => onAction({ kind: "edit", task })}
          icon="edit"
        />
        <MiniBtn
          title="重试此子任务"
          disabled={!canRetry}
          onClick={() => onAction({ kind: "retry", task })}
          icon="retry"
        />
        <MiniBtn
          title="查看失败原因"
          disabled={!canChat}
          onClick={() => onAction({ kind: "view_failure_reason", task })}
          icon="failure"
        />
        <MiniBtn
          title="查看输出"
          onClick={() => onAction({ kind: "view_io", task, direction: "out" })}
          icon="io"
        />
      </div>
    </div>
  );
}

function MiniBtn({
  title,
  disabled,
  onClick,
  icon,
}: {
  title: string;
  disabled?: boolean;
  onClick: () => void;
  icon: "edit" | "retry" | "failure" | "io";
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="rounded p-1 transition-opacity hover:opacity-70 disabled:cursor-not-allowed disabled:opacity-30"
      style={{ color: "var(--color-ink-muted)" }}
    >
      {renderIcon(icon)}
    </button>
  );
}

function renderIcon(kind: "edit" | "retry" | "failure" | "io") {
  const common = {
    width: 12,
    height: 12,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (kind) {
    case "edit":
      return (
        <svg {...common}>
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
        </svg>
      );
    case "retry":
      return (
        <svg {...common}>
          <polyline points="23 4 23 10 17 10" />
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
      );
    case "failure":
      return (
        <svg {...common}>
          <path d="M9 2h6a1 1 0 0 1 1 1v2H8V3a1 1 0 0 1 1-1z" />
          <rect x="5" y="4" width="14" height="18" rx="2" />
          <line x1="9" y1="11" x2="15" y2="11" />
          <line x1="9" y1="15" x2="15" y2="15" />
        </svg>
      );
    case "io":
      return (
        <svg {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
      );
  }
}
