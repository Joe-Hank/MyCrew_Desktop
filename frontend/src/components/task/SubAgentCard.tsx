import { useAgents } from "../../queries/useTeamQuery";
import type { Task } from "../../queries/useProjectQuery";

export type SubStepStatus =
  | "pending"
  | "started"
  | "completed"
  | "failed";

export type SubStepAction =
  | { kind: "edit"; task: Task; stepIndex: number }
  | { kind: "pause"; task: Task; stepIndex: number }
  | { kind: "retry"; task: Task; stepIndex: number }
  | { kind: "sub_chat"; task: Task; stepIndex: number; agentId: string }
  | { kind: "sub_view_io"; task: Task; stepIndex: number };

interface SubAgentCardProps {
  task: Task;
  stepIndex: number;
  stepRole: "head" | "executor" | "qa";
  agentId: string;
  totalSteps: number;
  status: SubStepStatus;
  /** Filled when status='failed' so we can show the kind in tooltips. */
  errorText?: string;
  /** Crew-defined template like "生成中 ({count}/{total} 完成)". */
  progressTemplate?: string;
  onAction: (action: SubStepAction) => void;
}

const STATUS_DOT: Record<SubStepStatus, string> = {
  pending: "#cbd5e1",
  started: "var(--color-brand-500)",
  completed: "#10b981",
  failed: "#ef4444",
};

const STATUS_TEXT_ZH: Record<SubStepStatus, string> = {
  pending: "等待",
  started: "进行中",
  completed: "完成",
  failed: "失败",
};

const ROLE_BADGE_BG: Record<string, string> = {
  head: "rgba(12, 140, 233, 0.14)",
  executor: "rgba(99, 102, 241, 0.14)",
  qa: "rgba(245, 158, 11, 0.18)",
};

const ROLE_BADGE_FG: Record<string, string> = {
  head: "var(--color-brand-500)",
  executor: "#4f46e5",
  qa: "#92400e",
};

const ROLE_LABEL_ZH: Record<string, string> = {
  head: "Head",
  executor: "Executor",
  qa: "QA",
};

function SubAgentCard({
  task,
  stepIndex,
  stepRole,
  agentId,
  totalSteps,
  status,
  errorText,
  progressTemplate,
  onAction,
}: SubAgentCardProps) {
  const { data: agents } = useAgents();
  const agentLabel =
    (agents ?? []).find((a) => a.id === agentId)?.role ?? agentId.slice(-8);

  // Q11 sub-card action gating. Head retains the full action set;
  // Executor + QA are read-only (chat + IO viewer only).
  const isHead = stepRole === "head";
  // Mirror the parent task's status to decide which actions are alive.
  // ready: nothing; running: pause; paused: edit/resume; failed: edit/retry/chat;
  // done: nothing actionable except IO; stalled: edit/retry/chat.
  const parentStatus = task.status;
  const canEditHead = isHead && (parentStatus === "paused" || parentStatus === "failed" || parentStatus === "validation_failed" || parentStatus === "stalled");
  const canPauseHead = isHead && parentStatus === "running";
  const canRetryHead = isHead && (parentStatus === "failed" || parentStatus === "validation_failed" || parentStatus === "stalled");
  const canChat = parentStatus === "failed" || parentStatus === "validation_failed" || parentStatus === "stalled";

  const progressText = progressTemplate || STATUS_TEXT_ZH[status];

  return (
    <div
      // Match TaskNode's 240px width + p-3 padding + halo treatment so
      // expanded Crew children look like miniature task cards rather
      // than a separate compact list. User audit 2026-05-16: the
      // 150px-wide variant felt disconnected from the rest of the canvas.
      className={
        "relative w-[240px] shrink-0 cursor-default rounded-lg p-3 transition-shadow " +
        (status === "started" ? "task-halo-running " : "") +
        (status === "failed" ? "task-halo-stalled " : "")
      }
      style={{
        backgroundColor: "var(--color-card)",
        border: `1px solid ${status === "started" ? "var(--color-brand-500)" : "var(--color-border-soft)"}`,
        boxShadow: status === "started" || status === "failed"
          ? undefined
          : "0 1px 2px rgba(0, 0, 0, 0.04)",
      }}
      title={errorText || ""}
    >
      {/* Role + step index header — same row layout as TaskNode's
          top-row index pill + title pair. */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className="flex h-5 items-center justify-center rounded-full px-1.5 text-[10px] font-semibold"
            style={{
              backgroundColor: ROLE_BADGE_BG[stepRole],
              color: ROLE_BADGE_FG[stepRole],
            }}
          >
            {ROLE_LABEL_ZH[stepRole]}
          </span>
          <span
            className="text-sm font-medium truncate"
            style={{ color: "var(--color-ink-soft)" }}
            title={agentLabel}
          >
            {agentLabel}
          </span>
        </div>
        <span
          className="shrink-0 text-[10px]"
          style={{ color: "var(--color-ink-faint)" }}
        >
          {stepIndex + 1}/{totalSteps}
        </span>
      </div>

      {/* Progress / status line — mirrors TaskNode's status row */}
      <div
        className="mb-3 flex items-center gap-1.5 text-[11px]"
        style={{ color: "var(--color-ink-faint)" }}
      >
        <span
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: STATUS_DOT[status] }}
        />
        <span className="truncate">{progressText}</span>
      </div>

      {/* Action bar */}
      <div
        className="flex items-center justify-between gap-0.5 pt-1.5"
        style={{ borderTop: "1px solid var(--color-border-soft)" }}
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        {isHead && (
          <>
            <MiniBtn
              title="编辑 Head spec"
              disabled={!canEditHead}
              onClick={() => onAction({ kind: "edit", task, stepIndex })}
              icon="edit"
            />
            <MiniBtn
              title={canPauseHead ? "暂停 Crew" : "暂停（不可用）"}
              disabled={!canPauseHead}
              onClick={() => onAction({ kind: "pause", task, stepIndex })}
              icon="pause"
            />
            <MiniBtn
              title="从当前 step 重试"
              disabled={!canRetryHead}
              onClick={() => onAction({ kind: "retry", task, stepIndex })}
              icon="retry"
            />
          </>
        )}
        <MiniBtn
          title="对话（限定到本步骤上下文）"
          disabled={!canChat}
          onClick={() =>
            onAction({ kind: "sub_chat", task, stepIndex, agentId })
          }
          icon="chat"
        />
        <MiniBtn
          title="查看本步骤输入/输出"
          onClick={() => onAction({ kind: "sub_view_io", task, stepIndex })}
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
  icon: "edit" | "pause" | "retry" | "chat" | "io";
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

function renderIcon(kind: "edit" | "pause" | "retry" | "chat" | "io") {
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
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
        </svg>
      );
    case "pause":
      return (
        <svg {...common}>
          <rect x="6" y="4" width="4" height="16" rx="1" />
          <rect x="14" y="4" width="4" height="16" rx="1" />
        </svg>
      );
    case "retry":
      return (
        <svg {...common}>
          <polyline points="23 4 23 10 17 10" />
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
      );
    case "chat":
      return (
        <svg {...common}>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      );
    case "io":
      return (
        <svg {...common}>
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
      );
  }
}

export default SubAgentCard;
