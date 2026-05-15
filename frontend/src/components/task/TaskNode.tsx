import type { Task } from "../../queries/useProjectQuery";
import { useAgents } from "../../queries/useTeamQuery";

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
  // Resolve agent_id → role for display. Uses the full agents list
  // (not the assignable-filtered one) so even auto-generated agents
  // surface their real role instead of a truncated id slice.
  const { data: agents } = useAgents();
  const agentLabel = task.agent_id
    ? (agents ?? []).find((a) => a.id === task.agent_id)?.role ?? task.agent_id.slice(-8)
    : "待指定";

  const canEdit = !projectRunning && task.status !== "running";
  const canPause = task.status === "running";
  const canRetry = ["done", "failed", "validation_failed", "aborted"].includes(task.status) && !projectRunning;
  const canChat = ["failed", "validation_failed", "blocked"].includes(task.status);

  // "Needs input" = task is in a state requiring manual intervention.
  // failed/stalled are added so the amber badge appears for every
  // case the start button would refuse to ignore (TaskHeader uses the
  // same BLOCKING_STATUSES set + stalled).
  const needsInput = ["blocked", "validation_failed", "failed", "stalled"]
    .includes(task.status);
  const warningTooltip = needsInput ? buildWarningTooltip(task) : "";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(task)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect(task);
      }}
      className={
        "relative w-[200px] cursor-pointer rounded-lg p-3 transition-shadow hover:shadow-md " +
        (task.status === "running" ? "task-halo-running " : "") +
        (task.status === "stalled" ? "task-halo-stalled " : "")
      }
      style={{
        // Explicit theme-aware bg via CSS variable — `bg-white` was being
        // resolved unpredictably under Tailwind v4 + ReactFlow's stacking
        // context, producing light cards in dark mode and vice versa.
        backgroundColor: "var(--color-card)",
        border: `1px solid ${selected ? "var(--color-brand-500)" : "var(--color-border-soft)"}`,
        // selected ring takes precedence; otherwise the running/stalled
        // halo class above adds an animated/static shadow via globals.css
        boxShadow: selected
          ? "0 0 0 3px rgba(12, 140, 233, 0.12)"
          : task.status === "running" || task.status === "stalled"
            ? undefined
            : "0 1px 2px rgba(0, 0, 0, 0.04)",
      }}
    >
      {/* Status indicator dot - top-right corner if needs input.
          Tooltip is built from the persisted last_error_kind + last_error
          (workflow_svc classifies the exception when the task fails) so
          hover shows e.g. "Token 配额不足" / "MCP 服务未连接 (Unity Bridge)"
          instead of the generic "需要用户介入". */}
      {needsInput && (
        <div
          className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full text-[10px] text-white"
          style={{ backgroundColor: "#f59e0b" }}
          title={warningTooltip}
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
        <span className="truncate">{agentLabel}</span>
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

/** Maps the persisted last_error_kind (set by backend's
 *  workflow_svc._classify_task_error) into a short Chinese headline.
 *  Falls back to the task status when no last_error_kind is available
 *  (e.g. older rows from before the column was added). */
const KIND_HEADLINES: Record<string, string> = {
  quota: "⚠️ Token 配额不足 / 计费问题",
  auth: "⚠️ LLM 鉴权失败（API Key 无效）",
  mcp: "⚠️ MCP 依赖未连接（如 Unity Bridge / Blender / ComfyUI）",
  network: "⚠️ 网络问题（超时 / DNS / 5xx）",
  validation: "⚠️ 输出校验未通过",
  stalled: "⚠️ 任务长时间无活动，被监控强制停摆",
  tool: "⚠️ 工具执行被拒或失败",
  unknown: "⚠️ Agent 执行异常（具体原因见日志）",
};

const STATUS_FALLBACK: Record<string, string> = {
  blocked: "⚠️ 依赖任务未完成，无法启动",
  validation_failed: "⚠️ 输出校验未通过",
  failed: "⚠️ Agent 执行失败",
  stalled: "⚠️ 任务长时间无活动",
};

function buildWarningTooltip(task: Task): string {
  const kind = task.last_error_kind ?? "";
  const headline = KIND_HEADLINES[kind] ?? STATUS_FALLBACK[task.status]
    ?? "⚠️ 需要用户介入";
  const detail = (task.last_error ?? "").trim();
  if (!detail) {
    return `${headline}\n\n点击卡片 → 💬 Agent 对话，让诊断助手解释。`;
  }
  // Cap exception text so the native tooltip stays readable.
  const trimmed = detail.length > 240 ? detail.slice(0, 240) + "…" : detail;
  return `${headline}\n\n${trimmed}\n\n点击卡片 → 💬 Agent 对话，可获取更详细的修复建议。`;
}

export default TaskNode;
