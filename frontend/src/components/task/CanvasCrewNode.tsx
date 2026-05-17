import { useMemo, useState, useCallback } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { Task } from "../../queries/useProjectQuery";
import { useCrews, type CrewSequenceStep } from "../../queries/useTeamQuery";
import { useEvent } from "../../hooks/useEvent";
import TaskNode, { type TaskAction } from "./TaskNode";
import SubAgentCard, { type SubStepStatus, type SubStepAction } from "./SubAgentCard";

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

  // Listen for task.sub_step events. Filter to events for THIS task and
  // update the status map; CanvasBlueprint also catches them but only
  // for its own purposes (it doesn't re-render every Crew node on each
  // sub-step — that would defeat the whole live-highlight experience).
  useEvent("task.sub_step", (msg) => {
    const payload = msg.payload as {
      task_id: string;
      step_index: number;
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
  });

  // Width broadcast — fire whenever expanded toggles. CanvasBlueprint
  // uses this to shift downstream nodes (Q-design "B 自动平移下游").
  const handleToggle = useCallback(() => {
    const next = !expanded;
    setExpanded(next);
    if (d.onWidthChange) {
      if (next) {
        const expandedWidth =
          EXPANDED_PADDING_X * 2
          + sequence.length * SUB_CARD_WIDTH
          + Math.max(0, sequence.length - 1) * SUB_CARD_GAP;
        d.onWidthChange(task.id, Math.max(0, expandedWidth - COLLAPSED_WIDTH));
      } else {
        d.onWidthChange(task.id, 0);
      }
    }
  }, [expanded, d, sequence.length, task.id]);

  // Collapsed mode: render the existing TaskNode + an ⊕ button overlay.
  // Functions just like a regular task card; the toggle reveals the
  // step pipeline.
  if (!expanded) {
    return (
      <div className="relative">
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
            className="canvas-crew-toggle absolute right-1.5 top-1.5 z-10 flex h-4 w-4 items-center justify-center rounded transition-colors"
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
  const dotColor =
    task.status === "running" ? "var(--color-brand-500)"
      : task.status === "done" ? "#10b981"
      : task.status === "failed" || task.status === "validation_failed" ? "#ef4444"
      : task.status === "paused" ? "#facc15"
      : "#cbd5e1";

  const showRunningHalo = task.status === "running";
  const showStalledHalo = task.status === "stalled";

  return (
    <div className="relative">
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
        className={
          "rounded-xl p-3 transition-shadow " +
          (showRunningHalo ? "task-halo-running " : "") +
          (showStalledHalo ? "task-halo-stalled " : "")
        }
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
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleToggle();
            }}
            title="收起 Crew"
            className="canvas-crew-toggle flex h-4 w-4 shrink-0 items-center justify-center rounded transition-colors"
            style={{ color: "var(--color-ink-faint)" }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
              <polygon points="8,1 1,5 8,9" />
            </svg>
          </button>
        </div>

        {/* Sub-cards in a row */}
        <div className="flex" style={{ gap: SUB_CARD_GAP }}>
          {sequence.map((step, i) => (
            <SubAgentCard
              key={`${task.id}-step-${i}`}
              task={task}
              stepIndex={i}
              stepRole={step.role}
              agentId={step.agent_id}
              totalSteps={sequence.length}
              status={subStepStatus[i] ?? (task.status === "done" ? "completed" : "pending")}
              errorText={subStepErrors[i]}
              progressTemplate={step.progress_template}
              onAction={onSubStepAction}
            />
          ))}
        </div>
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
