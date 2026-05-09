import { useMemo } from "react";
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

  // orphan tasks (cycles or broken deps)
  for (const t of tasks) {
    if (!placed.has(t.id)) {
      waves.push({ tasks: [t] });
      placed.add(t.id);
    }
  }

  return waves;
}

function Blueprint({
  tasks,
  projectRunning,
  onAction,
}: {
  tasks: Task[];
  projectRunning: boolean;
  onAction: (action: TaskAction) => void;
}) {
  const waves = useMemo(() => buildWaves(tasks), [tasks]);

  if (tasks.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-400">
        暂无任务
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-auto p-6">
      <div className="flex items-start gap-4">
        {waves.map((wave, wi) => (
          <div key={wi} className="flex items-start gap-4">
            {/* Wave column: parallel tasks stacked vertically */}
            <div className="flex flex-col gap-3">
              {wave.tasks.map((task) => (
                <TaskNode
                  key={task.id}
                  task={task}
                  projectRunning={projectRunning}
                  onAction={onAction}
                />
              ))}
            </div>

            {/* Connector arrow between waves */}
            {wi < waves.length - 1 && (
              <div className="flex items-center self-center">
                <div className="h-px w-8 bg-zinc-300 dark:bg-zinc-600" />
                <svg viewBox="0 0 8 12" className="h-3 w-2 text-zinc-300 dark:text-zinc-600" fill="currentColor">
                  <path d="M0 0 L8 6 L0 12 Z" />
                </svg>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default Blueprint;
