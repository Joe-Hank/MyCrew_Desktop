import { useMemo, useState, useCallback, useEffect } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { Task } from "../../queries/useProjectQuery";
import { useCrews, type CrewSequenceStep } from "../../queries/useTeamQuery";
import { useEvent } from "../../hooks/useEvent";
import { apiFetch } from "../../net/api";
import TaskNode, { STATUS_DOT, IconBtn, type TaskAction } from "./TaskNode";
import SubAgentCard, { type SubStepStatus, type SubStepAction } from "./SubAgentCard";
import ContractCheckCard from "./ContractCheckCard";

export interface CanvasCrewNodeData extends Record<string, unknown> {
  task: Task;
  index: number;
  projectRunning: boolean;
  onSelect: (task: Task) => void;
  onAction: (action: TaskAction) => void;
  /** Bubbled to TaskPage so it can route sub-step actions to the right
   *  drawer / endpoint (chat, IO viewer, edit Head spec, retry-from-step). */
  onSubStepAction: (action: SubStepAction) => void;
  /** Reports the width delta (expanded - collapsed) so CanvasBlueprint
   *  can push downstream nodes to the right while expanded. 0 when
   *  collapsed. */
  onWidthChange?: (taskId: string, deltaPx: number) => void;
}

const HANDLE_HIT_SIZE = 20;
const HANDLE_DOT_SIZE = 9;

// Match SubAgentCard sizing (audit 2026-05-16: sub-cards bumped to
// 240px to match TaskNode visual rhythm). Expanded width =
//   N * 240 + (N-1) * 8 gap + 2 * 12 outer padding
const SUB_CARD_WIDTH = 240;
const SUB_CARD_GAP = 8;
const EXPANDED_PADDING_X = 12;
const COLLAPSED_WIDTH = 240;

function HandleDot() {
  return (
    <span
      style={{
        width: HANDLE_DOT_SIZE,
        height: HANDLE_DOT_SIZE,
        borderRadius: "50%",
        backgroundColor: "var(--color-brand-500)",
        position: "absolute",
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        pointerEvents: "none",
        boxShadow: "0 0 0 2px var(--color-card)",
      }}
    />
  );
}

function CanvasCrewNode({ data, selected }: NodeProps) {
  const d = data as CanvasCrewNodeData;
  const { task, projectRunning, onSelect, onAction, onSubStepAction } = d;

  const [expanded, setExpanded] = useState(false);
  // Live status per step, updated via the task.sub_step WS event below.
  const [subStepStatus, setSubStepStatus] = useState<Record<number, SubStepStatus>>({});
  const [subStepErrors, setSubStepErrors] = useState<Record<number, string>>({});
  // Contract-check step (V5 Stage B). **Realised** state — populated
  // either from the crew_progress endpoint (which reads
  // <task_dir>/sub/<N>_contract_out.json) or from a live task.sub_step
  // WS event with role="contract".
  // **A null value here doesn't mean "no contract"** — see derived
  // `displayContractStep` below which falls back to a pending placeholder
  // whenever task.code_contract is non-null. Goal: every task that
  // declares a code_contract shows the contract sub-card consistently —
  // before / during / after run; not only after the regex pass finishes.
  const [contractStep, setContractStep] = useState<
    { stepIndex: number; status: SubStepStatus; errors: string[] } | null
  >(null);

  const { data: crews } = useCrews();
  const crew = useMemo(
    () => (crews ?? []).find((c) => c.id === task.performer_id),
    [crews, task.performer_id],
  );

  // agent_sequence comes in as either parsed array or raw JSON string.
  // Normalise once per render so the rest of the component sees an array.
  const sequence: CrewSequenceStep[] = useMemo(() => {
    if (!crew) return [];
    const raw = crew.agent_sequence;
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }, [crew]);

  // Seed subStepStatus from on-disk artifacts on mount (and whenever
  // the parent task's status changes — e.g. a retry that flips an
  // earlier "failed" Crew back to "running"). The WS-driven map alone
  // is volatile: a hard page refresh while a Crew is mid-flight loses
  // every "step N started/completed" event that fired before the
  // refresh, leaving every sub-card gray-pending until the next
  // sub_step event happens to fire. The backend route inspects
  // output/<pid>/<tid>/sub/*.json and infers status from which files
  // exist, so we can pre-populate without waiting.
  useEffect(() => {
    let cancelled = false;
    async function loadProgress() {
      try {
        const res = await apiFetch<{
          steps: {
            step_index: number; role: string; status: SubStepStatus;
            errors?: string[];
          }[];
        }>(`/tasks/${task.id}/crew_progress`);
        if (cancelled) return;
        const data = res?.data;
        if (!data?.steps) return;
        setSubStepStatus((prev) => {
          const next = { ...prev };
          for (const s of data.steps) {
            // Don't overwrite a fresher WS update with a stale disk read.
            if (next[s.step_index] === undefined) next[s.step_index] = s.status;
          }
          return next;
        });
        // Pull the contract step out of the same response — it's just
        // another sub-step on disk, but the frontend renders it with a
        // dedicated card next to the agent triplet.
        const contract = data.steps.find((s) => s.role === "contract");
        if (contract) {
          setContractStep({
            stepIndex: contract.step_index,
            status: contract.status,
            errors: contract.errors ?? [],
          });
        }
      } catch {
        // Non-fatal — sub-cards just stay at their default pending state
        // until the next WS event lands.
      }
    }
    loadProgress();
    return () => { cancelled = true; };
  }, [task.id, task.status]);

  // Listen for task.sub_step events. Filter to events for THIS task and
  // update the status map; CanvasBlueprint also catches them but only
  // for its own purposes (it doesn't re-render every Crew node on each
  // sub-step — that would defeat the whole live-highlight experience).
  useEvent("task.sub_step", (msg) => {
    const payload = msg.payload as {
      task_id: string;
      step_index: number;
      role?: string;
      status: SubStepStatus;
      error?: string;
    };
    if (payload?.task_id !== task.id) return;
    setSubStepStatus((prev) => ({
      ...prev,
      [payload.step_index]: payload.status,
    }));
    if (payload.status === "failed" && payload.error) {
      setSubStepErrors((prev) => ({ ...prev, [payload.step_index]: payload.error! }));
    }
    // Contract check broadcasts the same event shape but with
    // role="contract" — promote it into the dedicated contract state
    // so the card appears the moment verification finishes, without
    // waiting for the next crew_progress refetch.
    if (payload.role === "contract") {
      const liveErrors = payload.error
        ? payload.error.split("; ").filter(Boolean)
        : [];
      setContractStep({
        stepIndex: payload.step_index,
        status: payload.status,
        errors: liveErrors,
      });
    }
  });

  // Width broadcast — fire whenever expanded toggles. CanvasBlueprint
  // uses this to shift downstream nodes (Q-design "B 自动平移下游").
  // The contract card counts as a regular-width sub-card whenever it
  // *renders* — and per the displayContract logic in the JSX below,
  // it renders for ANY task whose code_contract is non-null (pending
  // placeholder pre-run, real status post-run). Previously this
  // counted only `contractStep` (the realised state) so a pending
  // task's downstream nodes got shoved short by SUB_CARD_WIDTH +
  // SUB_CARD_GAP px — visible misalignment.
  const hasContractCard = !!(contractStep || task.code_contract);
  const handleToggle = useCallback(() => {
    const next = !expanded;
    setExpanded(next);
    if (d.onWidthChange) {
      if (next) {
        const visibleCount = sequence.length + (hasContractCard ? 1 : 0);
        const expandedWidth =
          EXPANDED_PADDING_X * 2
          + visibleCount * SUB_CARD_WIDTH
          + Math.max(0, visibleCount - 1) * SUB_CARD_GAP;
        d.onWidthChange(task.id, Math.max(0, expandedWidth - COLLAPSED_WIDTH));
      } else {
        d.onWidthChange(task.id, 0);
      }
    }
  }, [expanded, d, sequence.length, hasContractCard, task.id]);

  // Halo class derived from the parent task's status — promoted to the
  // outermost wrapper (rather than the inner TaskNode) so the box-shadow
  // paints at the React Flow node root, matching the way ProjectCard
  // hangs `card-halo-running` on its top-level div. 2026-05-17 fix: the
  // previous placement on TaskNode's inner div looked visually identical
  // for regular tasks (CanvasTaskNode wraps TaskNode at the same depth)
  // but for Crew tasks the extra nesting + the toggle-button overlay
  // ate the glow.
  const haloClass =
    (task.status === "running" ? "task-halo-running " : "") +
    (task.status === "stalled" ? "task-halo-stalled " : "");

  // Collapsed mode: render the existing TaskNode + an ⊕ button overlay.
  // Functions just like a regular task card; the toggle reveals the
  // step pipeline.
  if (!expanded) {
    return (
      <div className={"relative " + haloClass}>
        <Handle
          type="target"
          position={Position.Left}
          style={{
            width: HANDLE_HIT_SIZE,
            height: HANDLE_HIT_SIZE,
            left: -HANDLE_HIT_SIZE / 2,
            background: "transparent",
            border: "none",
          }}
        >
          <HandleDot />
        </Handle>
        <div className="relative">
          <TaskNode
            task={task}
            index={d.index}
            selected={!!selected}
            projectRunning={projectRunning}
            onSelect={onSelect}
            onAction={onAction}
            // Reserve enough horizontal space in the title row so the
            // ▶ button (12px glyph + 8px right offset = ~20px) doesn't
            // overlap the truncated title.
            titleRightReserve={24}
          />
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleToggle();
            }}
            title={`展开 Crew (${sequence.length} 步子任务)`}
            // 2026-05-17 v2: 极简版 — 单个右向实心三角形。展开 = 向右，
            // 收起 = 向左（见下方展开态）。没有文字、没有边框、纯灰色
            // SVG，hover 才变蓝。
            className="canvas-crew-toggle absolute right-1.5 top-3.5 z-10 flex h-4 w-4 items-center justify-center rounded transition-colors"
            style={{ color: "var(--color-ink-faint)" }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
              <polygon points="2,1 9,5 2,9" />
            </svg>
          </button>
        </div>
        <Handle
          type="source"
          position={Position.Right}
          style={{
            width: HANDLE_HIT_SIZE,
            height: HANDLE_HIT_SIZE,
            right: -HANDLE_HIT_SIZE / 2,
            background: "transparent",
            border: "none",
          }}
        >
          <HandleDot />
        </Handle>
      </div>
    );
  }

  // Expanded mode: outer frame around N sub-cards in a row, head-first.
  // Status dot — same mapping as TaskNode so stalled/aborted/blocked
  // render with the right tone (previously they fell through to gray
  // because this ternary only covered the five "happy path" states).
  const dotColor = STATUS_DOT[task.status] ?? STATUS_DOT.pending;

  // Enable rules for the inline action row in expanded mode. Mirror
  // TaskNode's local logic verbatim so behaviour stays consistent
  // between collapsed and expanded views.
  const isFailureState = ["failed", "validation_failed", "aborted"].includes(task.status);
  const canRetry = isFailureState || (task.status === "done" && !projectRunning);
  const canChat = ["failed", "validation_failed", "blocked"].includes(task.status);

  return (
    <div className={"relative " + haloClass}>
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: HANDLE_HIT_SIZE,
          height: HANDLE_HIT_SIZE,
          left: -HANDLE_HIT_SIZE / 2,
          background: "transparent",
          border: "none",
        }}
      >
        <HandleDot />
      </Handle>
      <div
        className="rounded-xl p-3 transition-shadow"
        style={{
          backgroundColor: "var(--color-surface-alt)",
          border: `1px solid ${selected ? "var(--color-brand-500)" : "var(--color-border-soft)"}`,
          minWidth: COLLAPSED_WIDTH,
        }}
        onClick={(e) => {
          // Selecting the Crew is equivalent to selecting the parent task
          e.stopPropagation();
          onSelect(task);
        }}
      >
        {/* Header — title truncates with ellipsis at a fixed max width so
            the ◀ collapse triangle on the right never gets covered. */}
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <span
              className="inline-block h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: dotColor }}
            />
            <span
              className="truncate text-sm font-semibold"
              style={{
                color: "var(--color-ink-soft)",
                // Cap to ~28 CJK chars-ish so the row never expands and
                // the ◀ stays anchored at top-right. The flex layout
                // already truncates, this just provides a hard ceiling
                // for very wide expanded Crew widths.
                maxWidth: "28ch",
              }}
              title={`${crew?.name ?? "Crew"} · ${task.title}`}
            >
              {crew?.name ?? "Crew"} · {task.title}
            </span>
            <span
              className="shrink-0 rounded px-1.5 py-0.5 text-[9px]"
              style={{
                backgroundColor: "rgba(99, 102, 241, 0.14)",
                color: "#4f46e5",
              }}
              title={crew?.applicable_scenarios || ""}
            >
              Crew
            </span>
          </div>
          {/* Action buttons — mirror TaskNode's retry/IO/edit/view-
              failure trio so the user doesn't lose access to "retry
              outer task" when the Crew is expanded. The collapse
              triangle is the rightmost item in this row. canRetry /
              canChat conditions match TaskNode (failure states + done-
              while-paused). 2026-05-19 fix per user report: "Crew
              卡片出问题时，外层卡片也应可以重试". */}
          <div
            className="flex shrink-0 items-center gap-0.5"
            onClick={(e) => e.stopPropagation()}
            role="presentation"
          >
            <IconBtn
              title="编辑"
              onClick={() => onAction({ kind: "edit", task })}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
            </IconBtn>
            <IconBtn
              title="重试"
              disabled={!canRetry}
              onClick={() => onAction({ kind: "retry", task })}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
            </IconBtn>
            <IconBtn
              title="查看失败原因"
              disabled={!canChat}
              onClick={() => onAction({ kind: "view_failure_reason", task })}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 2h6a1 1 0 0 1 1 1v2H8V3a1 1 0 0 1 1-1z" />
                <rect x="5" y="4" width="14" height="18" rx="2" />
                <line x1="9" y1="11" x2="15" y2="11" />
                <line x1="9" y1="15" x2="15" y2="15" />
              </svg>
            </IconBtn>
            <IconBtn
              title="查看输出"
              onClick={() => onAction({ kind: "view_io", task, direction: "out" })}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            </IconBtn>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleToggle();
              }}
              title="收起 Crew"
              className="canvas-crew-toggle ml-1 flex h-4 w-4 shrink-0 items-center justify-center rounded transition-colors"
              style={{ color: "var(--color-ink-faint)" }}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
                <polygon points="8,1 1,5 8,9" />
              </svg>
            </button>
          </div>
        </div>

        {/* Sub-cards in a row. The contract check (V5 Stage B) is
            rendered as a synthetic post-QA card for every task that
            *declares* a code_contract — independent of whether the
            verification has actually run. Before run: pending placeholder.
            After run: status reflects the actual regex/AST pass result. */}
        {(() => {
          // Derive the contract card we should display:
          //   - If we have a realised step (from disk or WS) → use it
          //   - Else if task.code_contract is non-null → pending placeholder
          //   - Else → no contract card
          const hasContract = !!task.code_contract;
          const displayContract = contractStep ?? (
            hasContract
              ? { stepIndex: sequence.length, status: "pending" as SubStepStatus, errors: [] }
              : null
          );
          const totalSteps = sequence.length + (displayContract ? 1 : 0);
          return (
            <div className="flex" style={{ gap: SUB_CARD_GAP }}>
              {sequence.map((step, i) => (
                <SubAgentCard
                  key={`${task.id}-step-${i}`}
                  task={task}
                  stepIndex={i}
                  stepRole={step.role}
                  agentId={step.agent_id}
                  totalSteps={totalSteps}
                  status={subStepStatus[i] ?? (task.status === "done" ? "completed" : "pending")}
                  errorText={subStepErrors[i]}
                  progressTemplate={step.progress_template}
                  onAction={onSubStepAction}
                />
              ))}
              {displayContract && (
                <ContractCheckCard
                  key={`${task.id}-contract`}
                  task={task}
                  stepIndex={displayContract.stepIndex}
                  totalSteps={totalSteps}
                  status={displayContract.status}
                  errors={displayContract.errors}
                  onViewDetail={() =>
                    onSubStepAction({
                      kind: "sub_view_failure_reason",
                      task,
                      stepIndex: displayContract.stepIndex,
                    })
                  }
                />
              )}
            </div>
          );
        })()}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: HANDLE_HIT_SIZE,
          height: HANDLE_HIT_SIZE,
          right: -HANDLE_HIT_SIZE / 2,
          background: "transparent",
          border: "none",
        }}
      >
        <HandleDot />
      </Handle>
    </div>
  );
}

export default CanvasCrewNode;
export { COLLAPSED_WIDTH };
