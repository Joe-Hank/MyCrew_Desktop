import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { Task } from "../../queries/useProjectQuery";
import TaskNode, { type TaskAction } from "./TaskNode";

export interface CanvasTaskNodeData extends Record<string, unknown> {
  task: Task;
  index: number;
  projectRunning: boolean;
  onSelect: (task: Task) => void;
  onAction: (action: TaskAction) => void;
}

/** ReactFlow custom-node wrapper around the existing TaskNode. Adds the
 *  two connection handles (left = incoming-deps target, right = outgoing
 *  source) and forwards every other rendering responsibility to TaskNode
 *  so we don't duplicate the existing 200px card styling, icon bar, etc. */
// Handle hit-area: 20px wide invisible square so the user can grab the
// connection point from a generous margin around the card edge. The
// visible dot is a smaller centred child div so the styling still reads
// as a compact circle, per the user spec ("圆点图像尺寸维持，热点放大").
const HANDLE_HIT_SIZE = 20;
const HANDLE_DOT_SIZE = 9;

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

function CanvasTaskNode({ data, selected }: NodeProps) {
  const d = data as CanvasTaskNodeData;
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
      <TaskNode
        task={d.task}
        index={d.index}
        selected={!!selected}
        projectRunning={d.projectRunning}
        onSelect={d.onSelect}
        onAction={d.onAction}
      />
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

export default CanvasTaskNode;
