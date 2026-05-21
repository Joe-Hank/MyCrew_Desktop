import { useAgents } from "../../queries/useTeamQuery";
import type { Task } from "../../queries/useProjectQuery";
import type { SubStepStatus, SubStepAction } from "./SubAgentCard";

/** Crew V5 parallel sub-card. Replaces the sequential SubAgentCard for
 *  any step whose `agent_sequence` entry carries a `fanout` marker. The
 *  difference vs SubAgentCard:
 *
 *  - Top-right shows progress `x/y` (completed / total children) instead
 *    of the (now-dropped) sequential n/m index. This is the user-visible
 *    "fan-out is in progress" signal.
 *  - Carries an [展开] toggle. When expanded the parent's Crew shell
 *    reveals a thin row of child task cards below the step row,
 *    separated by a 1px divider, scrollable horizontally for overflow.
 *  - Status is derived from the aggregate, not from a single agent's
 *    sub-step event: any failed child → failed; any running child →
 *    started; all complete → completed; default → pending.
 */
export interface ParallelSubCardProps {
  task: Task;
  stepIndex: number;
  stepRole: "head" | "executor" | "qa";
  agentId: string;
  /** Total fan-out children (from progress event, or from the children
   *  array length before any progress lands). */
  total: number;
  /** Completed children count from `task.parallel_progress`. */
  completed: number;
  /** Failed children count from `task.parallel_progress`. */
  failed: number;
  /** Concurrency cap from the crew step config — shown in the tooltip
   *  for transparency ("最多并发 N"). */
  concurrencyCap: number;
  /** Whether the children row is currently shown below the card. */
  expanded: boolean;
  onToggleExpand: () => void;
  /** Sub-card actions (failure / IO viewer). The fan-out step itself has
   *  no Head spec, so edit/pause/retry are intentionally absent — those
   *  belong on the children. */
  onAction: (action: SubStepAction) => void;
}

const STATUS_DOT: Record<SubStepStatus, string> = {
  pending: "#cbd5e1",
  started: "var(--color-brand-500)",
  completed: "#10b981",
  failed: "#ef4444",
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

/** Roll the per-child counts into the same SubStepStatus enum the
 *  sequential cards use, so the halo/border treatment matches. */
function deriveStatus(
  total: number, completed: number, failed: number,
): SubStepStatus {
  if (total <= 0) return "pending";
  if (failed > 0) return "failed";
  if (completed >= total) return "completed";
  if (completed > 0 || (completed === 0 && failed === 0 && total > 0)) {
    // We can't reliably distinguish "0 done, in flight" from "0 done,
    // not started yet" without watching the started events. Fall back
    // to `started` whenever at least one child has launched per the
    // running count (= total - completed - failed > 0). When the
    // backend hasn't yet broadcast a progress event total may be 0;
    // that case is handled by the early-return above.
    const running = total - completed - failed;
    return running > 0 ? "started" : "pending";
  }
  return "pending";
}

export default function ParallelSubCard({
  task,
  stepIndex,
  stepRole,
  agentId,
  total,
  completed,
  failed,
  concurrencyCap,
  expanded,
  onToggleExpand,
  onAction,
}: ParallelSubCardProps) {
  const { data: agents } = useAgents();
  const agentLabel =
    (agents ?? []).find((a) => a.id === agentId)?.role ?? agentId.slice(-8);

  const status = deriveStatus(total, completed, failed);
  const running = Math.max(0, total - completed - failed);

  const isFailed = status === "failed";
  const isRunning = status === "started";
  // Re-use the sub-card chat/IO entry points — even though the parallel
  // card itself has no narrative output, users still want to inspect the
  // step (typically to see the executor template used for all children).
  const canChat =
    task.status === "failed"
    || task.status === "validation_failed"
    || task.status === "stalled";

  // Progress line: "完成 3/5 · 进行中 2 · 失败 0" — keep it terse so it
  // fits inside the 240px width even with all three counters visible.
  const progressLine = (
    <>
      <span style={{ color: "var(--color-ink-soft)" }}>
        {completed}/{total}
      </span>
      {running > 0 && (
        <span className="ml-2" style={{ color: "var(--color-brand-500)" }}>
          · 进行中 {running}
        </span>
      )}
      {failed > 0 && (
        <span className="ml-2" style={{ color: "#ef4444" }}>
          · 失败 {failed}
        </span>
      )}
    </>
  );

  return (
    <div
      className={
        "relative w-[240px] shrink-0 cursor-default rounded-lg p-3 transition-shadow "
        + (isRunning ? "task-halo-running " : "")
        + (isFailed ? "task-halo-stalled " : "")
      }
      style={{
        backgroundColor: "var(--color-card)",
        border: `1px solid ${
          isRunning ? "var(--color-brand-500)" : "var(--color-border-soft)"
        }`,
        boxShadow:
          isRunning || isFailed ? undefined : "0 1px 2px rgba(0, 0, 0, 0.04)",
      }}
      title={`最多并发 ${concurrencyCap}`}
    >
      {/* Header — role pill + agent label on the left, progress badge
          on the right. The badge replaces the sequential n/m index;
          it's the headline "are we done yet" signal. */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="flex h-5 shrink-0 items-center justify-center rounded-full px-1.5 text-[10px] font-semibold"
            style={{
              backgroundColor: ROLE_BADGE_BG[stepRole],
              color: ROLE_BADGE_FG[stepRole],
            }}
          >
            {ROLE_LABEL_ZH[stepRole]}
          </span>
          <span
            className="min-w-0 flex-1 truncate text-sm font-medium"
            style={{ color: "var(--color-ink-soft)" }}
            title={agentLabel}
          >
            {agentLabel}
          </span>
        </div>
        <span
          className="shrink-0 rounded px-1 py-0.5 text-[10px] font-semibold"
          style={{
            backgroundColor: isFailed
              ? "rgba(239, 68, 68, 0.12)"
              : isRunning
                ? "rgba(12, 140, 233, 0.12)"
                : "rgba(148, 163, 184, 0.16)",
            color: isFailed
              ? "#ef4444"
              : isRunning
                ? "var(--color-brand-500)"
                : "var(--color-ink-muted)",
          }}
          title={`并发执行 ${total} 个子任务`}
        >
          {completed}/{total}
        </span>
      </div>

      {/* Progress detail line */}
      <div
        className="mb-3 flex items-center gap-1.5 text-[11px]"
        style={{ color: "var(--color-ink-faint)" }}
      >
        <span
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: STATUS_DOT[status] }}
        />
        <span className="truncate">{progressLine}</span>
      </div>

      {/* Action row: 展开/收起 (left) + failure / IO (right). */}
      <div
        className="flex items-center justify-between gap-0.5 pt-1.5"
        style={{ borderTop: "1px solid var(--color-border-soft)" }}
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <button
          onClick={onToggleExpand}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium transition-opacity hover:opacity-70"
          style={{
            color: "var(--color-ink-muted)",
            backgroundColor: "rgba(148, 163, 184, 0.12)",
          }}
          title={expanded ? "收起并行子任务" : "展开并行子任务"}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            fill="currentColor"
            style={{
              transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
              transition: "transform 120ms ease-out",
            }}
          >
            <polygon points="2,1 9,5 2,9" />
          </svg>
          {expanded ? "收起" : "展开"}
        </button>
        <div className="flex items-center gap-0.5">
          <MiniBtn
            title="查看失败原因（任务级自动诊断）"
            disabled={!canChat}
            onClick={() =>
              onAction({ kind: "sub_view_failure_reason", task, stepIndex })
            }
            icon="failure"
          />
          <MiniBtn
            title="查看本步骤模板输入/输出"
            onClick={() => onAction({ kind: "sub_view_io", task, stepIndex })}
            icon="io"
          />
        </div>
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
  icon: "failure" | "io";
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

function renderIcon(kind: "failure" | "io") {
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
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
      );
  }
}
