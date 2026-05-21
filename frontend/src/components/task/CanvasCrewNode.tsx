import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { Task } from "../../queries/useProjectQuery";
import { useCrews, type CrewSequenceStep } from "../../queries/useTeamQuery";
import { useEvent } from "../../hooks/useEvent";
import { apiFetch } from "../../net/api";
import TaskNode, { STATUS_DOT, IconBtn, type TaskAction } from "./TaskNode";
import SubAgentCard, { type SubStepStatus, type SubStepAction } from "./SubAgentCard";
import ParallelSubCard from "./ParallelSubCard";
import ChildTaskTile from "./ChildTaskTile";
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
  /** Reports the height delta induced by expanded parallel rows so
   *  CanvasBlueprint can shift cards BELOW down a corresponding amount.
   *  0 when no parallel sub-cards are expanded. V5 (2026-05-20). */
  onHeightChange?: (taskId: string, deltaPx: number) => void;
  /** Crew v5 fan-out children of this parent task — pre-sorted by
   *  parent_step_index then id. Pulled from `childrenByParent` map in
   *  CanvasBlueprint so each crew node receives only its own slice. */
  children?: Task[];
  /** Currently selected task id (so child tiles can highlight when
   *  selected). */
  selectedTaskId?: string | null;
}

const HANDLE_HIT_SIZE = 20;
const HANDLE_DOT_SIZE = 9;

// Match SubAgentCard sizing. Expanded width formula remains the same as
// the legacy implementation; the parallel row sits BELOW the step row so
// it doesn't change the horizontal footprint.
const SUB_CARD_WIDTH = 240;
const SUB_CARD_GAP = 8;
const EXPANDED_PADDING_X = 12;
const EXPANDED_PADDING_Y = 12;
const COLLAPSED_WIDTH = 240;
// Vertical bookkeeping for the parallel-children row. Used by the
// onHeightChange contract so CanvasBlueprint can push downstream
// (vertical) cards out of the way when a parallel row pops into view.
const CHILD_ROW_HEIGHT = 130;       // ChildTaskTile is ~110px tall + margins
const CHILD_ROW_DIVIDER_GAP = 12;   // mt-3 between step row and child row

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

/** Aggregate state for one fan-out step, populated from the
 *  task.parallel_progress WS event. Concurrency_cap defaults to 1 if
 *  the WS hasn't landed yet (we still want to render the card with the
 *  child count from the children array). */
interface ParallelProgress {
  total: number;
  completed: number;
  failed: number;
  running: number;
  concurrencyCap: number;
}

function CanvasCrewNode({ data, selected }: NodeProps) {
  const d = data as CanvasCrewNodeData;
  const {
    task, projectRunning, onSelect, onAction, onSubStepAction,
    onWidthChange, onHeightChange,
    children = [], selectedTaskId,
  } = d;

  const [expanded, setExpanded] = useState(false);
  // Live status per step, updated via the task.sub_step WS event below.
  const [subStepStatus, setSubStepStatus] = useState<Record<number, SubStepStatus>>({});
  const [subStepErrors, setSubStepErrors] = useState<Record<number, string>>({});
  // Per-step parallel progress (only populated for fan-out steps). Keyed
  // by step_index so a Crew with two fan-out steps tracks each independently.
  const [parallelProgress, setParallelProgress] = useState<Record<number, ParallelProgress>>({});
  // Per-step expansion state for the children row. Keyed by step_index.
  // Multiple parallel steps can be expanded simultaneously; the rendered
  // children row stacks the union of all their child sets in step order.
  const [expandedParallel, setExpandedParallel] = useState<Record<number, boolean>>({});
  // Contract-check step (V5 Stage B). See the legacy implementation for
  // the rationale — the placeholder logic is unchanged.
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

  // Group children by parent_step_index so each fan-out card knows which
  // child tiles belong under it.
  //
  // parent_step_index is NULL on children **until the Crew actually
  // dispatches that step** — backend's `_fanout_step` stamps the column
  // at dispatch time, not at PM-merge time. So between PM planning and
  // the Crew kicking off, every child has a NULL value. Defaulting to
  // 0 (the legacy fallback) routed them to the head step, leaving the
  // executor's ParallelSubCard with childList=[] → "0/0" display even
  // though the children are visible right there in the DB.
  //
  // Smart default: pick the first step in the sequence that *declares*
  // fanout — that's where these children will land once the Crew runs.
  // If the sequence has no fanout step at all, fall back to 0.
  const childrenByStep = useMemo(() => {
    const fanoutIdx = sequence.findIndex((s) => !!s.fanout);
    const fallbackIdx = fanoutIdx >= 0 ? fanoutIdx : 0;
    const map = new Map<number, Task[]>();
    for (const c of children) {
      const idx = c.parent_step_index ?? fallbackIdx;
      const list = map.get(idx) ?? [];
      list.push(c);
      map.set(idx, list);
    }
    return map;
  }, [children, sequence]);

  // Initial seed from crew_progress endpoint — refreshes on task.status
  // change so retries / reruns start with a clean slate instead of
  // showing the previous run's "completed" / "failed" / progress badges
  // mixed with the new run's live updates.
  //
  // Reset rule (2026-05-20): when a NEW RUN begins — task.status flips
  // from a terminal state (done/failed/validation_failed/aborted/stalled)
  // to an active state (pending/running/blocked) — wipe every piece of
  // per-step memory before re-seeding from disk. Without this, on
  // Retry the user sees old red error halos for a few seconds until
  // the next WS sub_step event lands, which is the "状态混淆" the user
  // reported. We track the previous status in a ref so we can detect
  // the edge.
  const prevStatusRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevStatusRef.current;
    const cur = task.status;
    prevStatusRef.current = cur;

    const TERMINAL = new Set([
      "done", "failed", "validation_failed", "aborted", "stalled",
    ]);
    const ACTIVE = new Set(["pending", "running", "blocked"]);
    const isNewRun =
      prev !== null && TERMINAL.has(prev) && ACTIVE.has(cur);

    if (isNewRun) {
      // Drop all local progress memory — sub-step status, errors,
      // parallel-progress aggregates, contract verdict. Children rows
      // are DB-driven (rendered from the `children` prop), so they
      // reset naturally when the parent's retry handler resets child
      // task rows in the DB.
      setSubStepStatus({});
      setSubStepErrors({});
      setParallelProgress({});
      setContractStep(null);
      // Keep `expandedParallel` intact — if the user had a row open
      // before retry, they probably want it still open to watch the
      // new run unfold.
    }

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
        const payload = res?.data;
        if (!payload?.steps) return;
        if (isNewRun) {
          // Hard replace — the disk just got cleaned by
          // workflow_svc._cleanup_task_artifacts, so any state we
          // read here is canonical for the new run.
          setSubStepStatus(() => {
            const next: Record<number, SubStepStatus> = {};
            for (const s of payload.steps) next[s.step_index] = s.status;
            return next;
          });
        } else {
          setSubStepStatus((prevState) => {
            const next = { ...prevState };
            for (const s of payload.steps) {
              if (next[s.step_index] === undefined) next[s.step_index] = s.status;
            }
            return next;
          });
        }
        const contract = payload.steps.find((s) => s.role === "contract");
        if (contract) {
          setContractStep({
            stepIndex: contract.step_index,
            status: contract.status,
            errors: contract.errors ?? [],
          });
        }
      } catch {
        // Non-fatal; sub-cards stay at default pending until next WS event.
      }
    }
    loadProgress();
    return () => { cancelled = true; };
  }, [task.id, task.status]);

  // task.sub_step — same as the legacy implementation. Used for
  // sequential cards + the contract sentinel; fan-out steps do NOT
  // broadcast sub_step (their per-child progress lives on
  // task.parallel_progress instead).
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

  // task.parallel_progress — the per-step aggregate the backend
  // broadcasts from `_broadcast_parallel_progress`. Payload:
  //   { parent_task_id, step_index, concurrency_cap,
  //     total, completed, failed, running, ts }
  // We only care about events whose parent_task_id matches this Crew's
  // task id — the same WS bus is shared across the whole canvas.
  useEvent("task.parallel_progress", (msg) => {
    const payload = msg.payload as {
      parent_task_id: string;
      step_index: number;
      concurrency_cap: number;
      total: number;
      completed: number;
      failed: number;
      running: number;
    };
    if (payload?.parent_task_id !== task.id) return;
    setParallelProgress((prev) => ({
      ...prev,
      [payload.step_index]: {
        total: payload.total,
        completed: payload.completed,
        failed: payload.failed,
        running: payload.running,
        concurrencyCap: payload.concurrency_cap,
      },
    }));
  });

  // Derived: should step_index render as a parallel fan-out card?
  //   - Crew step must declare `fanout`.
  //   - AND this parent task must actually have v5-fanout children
  //     under it. Standalone (leaf) tasks landing on a fanout-capable
  //     Crew (e.g. a single .png handed to 2D 美术) hit the executor's
  //     leaf-task path in `_fanout_step` and run inline — there's no
  //     real x/y progress to show. Rendering the ParallelSubCard for a
  //     childless leaf would parrot "0/0" forever; treat it as a
  //     sequential step instead so the progress reads from sub_step
  //     events like the rest of the chain.
  const isFanoutStep = useCallback(
    (stepIndex: number) =>
      !!sequence[stepIndex]?.fanout && children.length > 0,
    [sequence, children.length],
  );

  // ── Width / height bookkeeping for CanvasBlueprint ────────────────
  //
  // Width: expanded shell is `sequence.length + (hasContract?1:0)` cards
  // in a row → identical formula to legacy. Width doesn't change when
  // parallel rows pop into view, only height does.
  //
  // Height: every expanded parallel step contributes one child row =
  // CHILD_ROW_HEIGHT + CHILD_ROW_DIVIDER_GAP px below the step row.

  const hasContractCard = !!(contractStep || task.code_contract);

  const widthDelta = useMemo(() => {
    if (!expanded) return 0;
    const visibleCount = sequence.length + (hasContractCard ? 1 : 0);
    const expandedWidth =
      EXPANDED_PADDING_X * 2
      + visibleCount * SUB_CARD_WIDTH
      + Math.max(0, visibleCount - 1) * SUB_CARD_GAP;
    return Math.max(0, expandedWidth - COLLAPSED_WIDTH);
  }, [expanded, sequence.length, hasContractCard]);

  const heightDelta = useMemo(() => {
    if (!expanded) return 0;
    const rowCount = Object.values(expandedParallel).filter(Boolean).length;
    if (rowCount === 0) return 0;
    return rowCount * (CHILD_ROW_HEIGHT + CHILD_ROW_DIVIDER_GAP);
  }, [expanded, expandedParallel]);

  // Broadcast width/height changes upward. CRITICAL: depend on the
  // destructured callback ref (stable via useCallback in Blueprint), NOT
  // on `d` — `d` is a new object literal every render, so listing it in
  // deps would loop: effect → setExpandedDeltas → Blueprint rerender →
  // new `d` → effect → … (the infinite-update crash).
  useEffect(() => {
    onWidthChange?.(task.id, widthDelta);
    return () => {
      // Node leaving the canvas (project switch, task deletion) should
      // drop its delta entry so Blueprint's offsetFor doesn't keep
      // shifting downstream cards for a ghost.
      onWidthChange?.(task.id, 0);
    };
  }, [onWidthChange, task.id, widthDelta]);
  useEffect(() => {
    onHeightChange?.(task.id, heightDelta);
    return () => {
      onHeightChange?.(task.id, 0);
    };
  }, [onHeightChange, task.id, heightDelta]);

  // Closing the outer Crew collapses every parallel row too — spec point
  // 5: "收起Crew任务卡片时，一并收起并行卡片行". We don't clear the map
  // outright (preserves user intent across re-expansion), but the height
  // delta useMemo above already returns 0 when `expanded` is false.

  const handleToggle = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  const handleToggleParallel = useCallback((stepIndex: number) => {
    setExpandedParallel((prev) => ({
      ...prev,
      [stepIndex]: !prev[stepIndex],
    }));
  }, []);

  const haloClass =
    (task.status === "running" ? "task-halo-running " : "") +
    (task.status === "stalled" ? "task-halo-stalled " : "");

  // ── Collapsed mode ────────────────────────────────────────────────
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
            titleRightReserve={24}
          />
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleToggle();
            }}
            title={`展开 Crew (${sequence.length} 步子任务)`}
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

  // ── Expanded mode ─────────────────────────────────────────────────
  const dotColor = STATUS_DOT[task.status] ?? STATUS_DOT.pending;

  const isFailureState = ["failed", "validation_failed", "aborted", "stalled"].includes(task.status);
  const canRetry = isFailureState || (task.status === "done" && !projectRunning);
  const canChat = ["failed", "validation_failed", "blocked", "stalled"].includes(task.status);

  // Contract card derivation (unchanged from legacy).
  const hasContract = !!task.code_contract;
  const displayContract = contractStep ?? (
    hasContract
      ? { stepIndex: sequence.length, status: "pending" as SubStepStatus, errors: [] }
      : null
  );

  // Each fan-out step that's currently expanded shows a child row
  // beneath the step pipeline. Render them in step order so they line
  // up vertically with their step.
  const expandedFanoutSteps = sequence
    .map((step, i) => ({ step, i }))
    .filter(({ step, i }) => !!step.fanout && expandedParallel[i]);

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
        className="rounded-xl"
        style={{
          backgroundColor: "var(--color-surface-alt)",
          border: `1px solid ${selected ? "var(--color-brand-500)" : "var(--color-border-soft)"}`,
          minWidth: COLLAPSED_WIDTH,
          padding: EXPANDED_PADDING_Y + "px " + EXPANDED_PADDING_X + "px",
        }}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(task);
        }}
      >
        {/* Header row */}
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

        {/* Step pipeline row — head → executor(s) → qa [→ contract] */}
        <div className="flex" style={{ gap: SUB_CARD_GAP }}>
          {sequence.map((step, i) => {
            if (isFanoutStep(i)) {
              const progress = parallelProgress[i];
              const childList = childrenByStep.get(i) ?? [];
              // Total: prefer the live WS value, fall back to the children
              // array length so the badge isn't blank pre-flight.
              const total = progress?.total ?? childList.length;
              const completed = progress?.completed ?? childList.filter(
                (c) => c.status === "done",
              ).length;
              const failed = progress?.failed ?? childList.filter(
                (c) =>
                  c.status === "failed"
                  || c.status === "validation_failed",
              ).length;
              return (
                <ParallelSubCard
                  key={`${task.id}-step-${i}`}
                  task={task}
                  stepIndex={i}
                  stepRole={step.role}
                  agentId={step.agent_id}
                  total={total}
                  completed={completed}
                  failed={failed}
                  concurrencyCap={
                    progress?.concurrencyCap ?? step.fanout?.concurrency_cap ?? 1
                  }
                  expanded={!!expandedParallel[i]}
                  onToggleExpand={() => handleToggleParallel(i)}
                  onAction={onSubStepAction}
                />
              );
            }
            return (
              <SubAgentCard
                key={`${task.id}-step-${i}`}
                task={task}
                stepIndex={i}
                stepRole={step.role}
                agentId={step.agent_id}
                status={subStepStatus[i] ?? (task.status === "done" ? "completed" : "pending")}
                errorText={subStepErrors[i]}
                progressTemplate={step.progress_template}
                stepKind={step.kind ?? null}
                onAction={onSubStepAction}
              />
            );
          })}
          {displayContract && (
            <ContractCheckCard
              key={`${task.id}-contract`}
              task={task}
              stepIndex={displayContract.stepIndex}
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

        {/* Parallel-children rows. One row per expanded fan-out step,
            each separated from the row above by a 1px divider per spec.
            Scrollable horizontally so wide fan-outs don't push the
            outer node to comical widths. */}
        {expandedFanoutSteps.map(({ i }) => {
          const childList = childrenByStep.get(i) ?? [];
          return (
            <div
              key={`${task.id}-children-${i}`}
              className="mt-3 pt-3 overflow-x-auto"
              style={{
                borderTop: "1px solid var(--color-border-soft)",
              }}
              onClick={(e) => e.stopPropagation()}
              role="presentation"
            >
              {childList.length === 0 ? (
                <div
                  className="px-1 py-2 text-[11px]"
                  style={{ color: "var(--color-ink-faint)" }}
                >
                  暂无并行子任务（Crew 尚未启动该步骤）
                </div>
              ) : (
                <div className="flex" style={{ gap: SUB_CARD_GAP }}>
                  {childList.map((c) => (
                    <ChildTaskTile
                      key={c.id}
                      task={c}
                      selected={c.id === selectedTaskId}
                      projectRunning={projectRunning}
                      onSelect={onSelect}
                      onAction={onAction}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
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
