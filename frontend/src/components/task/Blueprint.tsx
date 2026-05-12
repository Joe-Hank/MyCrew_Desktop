import { useEffect, useMemo, useRef, useState } from "react";
import type { Task } from "../../queries/useProjectQuery";
import TaskNode, { type TaskAction } from "./TaskNode";

interface Wave {
  tasks: Task[];
}

function buildWaves(tasks: Task[]): Wave[] {
  if (tasks.length === 0) return [];

  const placed = new Set<string>();
  const waves: Wave[] = [];

  for (let safety = 0; safety < tasks.length; safety++) {
    const wave: Task[] = [];
    for (const t of tasks) {
      if (placed.has(t.id)) continue;
      const depsReady = t.deps.every((d) => placed.has(d));
      if (depsReady) wave.push(t);
    }
    if (wave.length === 0) break;
    for (const t of wave) placed.add(t.id);
    waves.push({ tasks: wave });
  }

  for (const t of tasks) {
    if (!placed.has(t.id)) {
      waves.push({ tasks: [t] });
      placed.add(t.id);
    }
  }

  return waves;
}

interface NodeRect {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

function Blueprint({
  tasks,
  selectedTaskId,
  projectRunning,
  onSelect,
  onAction,
}: {
  tasks: Task[];
  selectedTaskId: string | null;
  projectRunning: boolean;
  onSelect: (task: Task) => void;
  onAction: (action: TaskAction) => void;
}) {
  const waves = useMemo(() => buildWaves(tasks), [tasks]);
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Map<string, HTMLDivElement | null>>(new Map());
  const [rects, setRects] = useState<NodeRect[]>([]);

  // Index map: task id → its position in original tasks array
  const indexById = useMemo(() => {
    const m = new Map<string, number>();
    tasks.forEach((t, i) => m.set(t.id, i));
    return m;
  }, [tasks]);

  // Recompute node rects after layout
  useEffect(() => {
    if (!containerRef.current) return;
    const cRect = containerRef.current.getBoundingClientRect();
    const next: NodeRect[] = [];
    for (const [id, el] of nodeRefs.current) {
      if (!el) continue;
      const r = el.getBoundingClientRect();
      next.push({
        id,
        x: r.left - cRect.left + containerRef.current.scrollLeft,
        y: r.top - cRect.top + containerRef.current.scrollTop,
        width: r.width,
        height: r.height,
      });
    }
    setRects(next);
  }, [tasks, waves]);

  // Also recompute on resize
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(() => {
      if (!containerRef.current) return;
      const cRect = containerRef.current.getBoundingClientRect();
      const next: NodeRect[] = [];
      for (const [id, el] of nodeRefs.current) {
        if (!el) continue;
        const r = el.getBoundingClientRect();
        next.push({
          id,
          x: r.left - cRect.left + containerRef.current.scrollLeft,
          y: r.top - cRect.top + containerRef.current.scrollTop,
          width: r.width,
          height: r.height,
        });
      }
      setRects(next);
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  if (tasks.length === 0) {
    return (
      <div
        className="flex h-full items-center justify-center text-sm"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        暂无任务
      </div>
    );
  }

  const rectMap = new Map(rects.map((r) => [r.id, r]));

  // Compute SVG dimensions to cover content
  const maxX = rects.reduce((m, r) => Math.max(m, r.x + r.width), 0);
  const maxY = rects.reduce((m, r) => Math.max(m, r.y + r.height), 0);

  // Build curves: for each task with deps, draw curve from each dep's right-center → this task's left-center
  const curves: Array<{ d: string; key: string }> = [];
  for (const task of tasks) {
    const target = rectMap.get(task.id);
    if (!target) continue;
    for (const depId of task.deps) {
      const source = rectMap.get(depId);
      if (!source) continue;
      const x1 = source.x + source.width;
      const y1 = source.y + source.height / 2;
      const x2 = target.x;
      const y2 = target.y + target.height / 2;
      const dx = Math.max(40, (x2 - x1) * 0.5);
      const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
      curves.push({ d, key: `${depId}->${task.id}` });
    }
  }

  return (
    <div
      ref={containerRef}
      className="relative h-full overflow-auto"
      style={{ backgroundColor: "var(--color-surface)" }}
    >
      {/* SVG layer for connectors (positioned absolutely behind nodes) */}
      <svg
        className="pointer-events-none absolute left-0 top-0"
        width={Math.max(maxX + 40, 800)}
        height={Math.max(maxY + 40, 400)}
      >
        {curves.map((c) => (
          <path
            key={c.key}
            d={c.d}
            fill="none"
            stroke="var(--color-border-strong)"
            strokeWidth="1.5"
            strokeDasharray="0"
          />
        ))}
      </svg>

      {/* Nodes wave by wave */}
      <div className="relative flex items-start gap-12 p-6">
        {waves.map((wave, wi) => (
          <div key={wi} className="flex flex-col gap-4">
            {wave.tasks.map((task) => {
              const idx = indexById.get(task.id) ?? 0;
              return (
                <div
                  key={task.id}
                  ref={(el) => {
                    nodeRefs.current.set(task.id, el);
                  }}
                >
                  <TaskNode
                    task={task}
                    index={idx}
                    selected={selectedTaskId === task.id}
                    projectRunning={projectRunning}
                    onSelect={onSelect}
                    onAction={onAction}
                  />
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export default Blueprint;
