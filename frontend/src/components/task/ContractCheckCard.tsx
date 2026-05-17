import type { Task } from "../../queries/useProjectQuery";
import type { SubStepStatus } from "./SubAgentCard";

/** Compact post-QA card that surfaces the V5 code-contract verification
 *  result (regex scan of generated .cs files against PM-declared public
 *  signatures). Visually parallels SubAgentCard but strips out the
 *  agent-specific affordances (no Head/Executor/QA badge, no edit/pause
 *  buttons) because the contract check isn't an agent — it's a static
 *  regex pass. Status:
 *
 *    pending   → grey dot, "等待 QA 完成"
 *    started   → blue dot, "正在校验" (very brief window in practice)
 *    completed → green dot, "✓ 全部签名已满足"
 *    failed    → red dot,   "✗ N 项签名缺失" + tooltip with the first
 *                            error line; click opens the failure-reason
 *                            drawer (same one the parent task uses).
 */
export interface ContractCheckCardProps {
  task: Task;
  stepIndex: number;
  totalSteps: number;
  status: SubStepStatus;
  errors?: string[];
  onViewDetail: () => void;
}

const STATUS_DOT: Record<SubStepStatus, string> = {
  pending: "#cbd5e1",
  started: "var(--color-brand-500)",
  completed: "#10b981",
  failed: "#ef4444",
};

function statusLine(status: SubStepStatus, errors: string[]): string {
  switch (status) {
    case "pending":
      return "等待 QA 完成";
    case "started":
      return "正在校验签名…";
    case "completed":
      return "✓ 全部签名已满足";
    case "failed":
      return `✗ ${errors.length} 项签名缺失`;
  }
}

export default function ContractCheckCard({
  task: _task,
  stepIndex,
  totalSteps,
  status,
  errors = [],
  onViewDetail,
}: ContractCheckCardProps) {
  const isFailed = status === "failed";
  const isRunning = status === "started";
  return (
    <div
      className={
        "relative w-[240px] shrink-0 cursor-default rounded-lg p-3 transition-shadow " +
        (isRunning ? "task-halo-running " : "") +
        (isFailed ? "task-halo-stalled " : "")
      }
      style={{
        backgroundColor: "var(--color-card)",
        border: `1px solid ${isRunning ? "var(--color-brand-500)" : "var(--color-border-soft)"}`,
        boxShadow: isRunning || isFailed
          ? undefined
          : "0 1px 2px rgba(0, 0, 0, 0.04)",
      }}
      title={errors[0] || ""}
    >
      {/* Header — role pill mirrors SubAgentCard layout but reads "契约"
          and uses a teal palette to telegraph "this isn't an agent". */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className="flex h-5 items-center justify-center rounded-full px-1.5 text-[10px] font-semibold"
            style={{
              backgroundColor: "rgba(20, 184, 166, 0.16)",
              color: "#0d9488",
            }}
          >
            契约
          </span>
          <span
            className="text-sm font-medium truncate"
            style={{ color: "var(--color-ink-soft)" }}
            title="V5 代码契约校验：正则扫描已生成的 .cs 文件"
          >
            代码契约
          </span>
        </div>
        <span
          className="shrink-0 text-[10px]"
          style={{ color: "var(--color-ink-faint)" }}
        >
          {stepIndex + 1}/{totalSteps}
        </span>
      </div>

      {/* Status line — mirrors SubAgentCard's progress row */}
      <div
        className="mb-3 flex items-center gap-1.5 text-[11px]"
        style={{ color: "var(--color-ink-faint)" }}
      >
        <span
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: STATUS_DOT[status] }}
        />
        <span className="truncate">{statusLine(status, errors)}</span>
      </div>

      {/* Single action — only relevant on failure (opens the parent's
          failure-reason drawer which lists every missing signature). */}
      <div
        className="flex items-center justify-end gap-0.5 pt-1.5"
        style={{ borderTop: "1px solid var(--color-border-soft)" }}
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <button
          onClick={onViewDetail}
          disabled={!isFailed}
          title={isFailed ? "查看缺失的签名列表" : "校验已通过，无需介入"}
          className="rounded p-1 transition-opacity hover:opacity-70 disabled:cursor-not-allowed disabled:opacity-30"
          style={{ color: "var(--color-ink-muted)" }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 2h6a1 1 0 0 1 1 1v2H8V3a1 1 0 0 1 1-1z" />
            <rect x="5" y="4" width="14" height="18" rx="2" />
            <line x1="9" y1="11" x2="15" y2="11" />
            <line x1="9" y1="15" x2="15" y2="15" />
          </svg>
        </button>
      </div>
    </div>
  );
}
