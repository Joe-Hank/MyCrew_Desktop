import { useState } from "react";
import type { Blueprint } from "../../queries/useInceptionQuery";

interface Props {
  blueprint: Blueprint;
  onChange: (bp: Blueprint) => void;
  onFinalize: () => void;
  onReEvaluate: () => void;
  finalizing: boolean;
  reEvaluating: boolean;
}

function TaskBlueprintEditor({
  blueprint,
  onChange,
  onFinalize,
  onReEvaluate,
  finalizing,
  reEvaluating,
}: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);

  function updateTask(index: number, patch: Partial<Blueprint["tasks"][0]>) {
    const tasks = blueprint.tasks.map((t, i) =>
      i === index ? { ...t, ...patch } : t,
    );
    onChange({ ...blueprint, tasks });
  }

  function removeTask(index: number) {
    const tasks = blueprint.tasks.filter((_, i) => i !== index);
    const updated = tasks.map((t) => ({
      ...t,
      deps: t.deps.filter((d) => d !== index).map((d) => (d > index ? d - 1 : d)),
    }));
    onChange({ ...blueprint, tasks: updated });
    setEditingIndex(null);
  }

  function addTask() {
    const tasks = [
      ...blueprint.tasks,
      { title: "新任务", detail: "", deps: [], output_schema: {}, kind: "regular" as const },
    ];
    onChange({ ...blueprint, tasks });
    setEditingIndex(tasks.length - 1);
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">
          任务蓝图
        </h3>
        <div className="flex items-center gap-1.5">
          <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] dark:bg-zinc-700">
            {blueprint.execution_kind}
          </span>
          <button
            onClick={onReEvaluate}
            disabled={reEvaluating}
            className="rounded border border-zinc-300 px-2 py-0.5 text-[10px] transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-600 dark:hover:bg-zinc-800"
            title="让 AI 重新评估架构"
          >
            {reEvaluating ? "评估中..." : "AI 复核"}
          </button>
        </div>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-auto">
        {blueprint.tasks.map((task, i) => (
          <div
            key={i}
            className="mb-2 rounded border border-zinc-200 bg-white p-2 dark:border-zinc-700 dark:bg-zinc-900"
          >
            {editingIndex === i ? (
              /* Edit mode */
              <div className="space-y-1.5">
                <input
                  value={task.title}
                  onChange={(e) => updateTask(i, { title: e.target.value })}
                  className="w-full rounded border border-zinc-300 px-2 py-1 text-xs dark:border-zinc-600 dark:bg-zinc-800"
                  placeholder="任务标题"
                />
                <textarea
                  value={task.detail}
                  onChange={(e) => updateTask(i, { detail: e.target.value })}
                  rows={2}
                  className="w-full resize-none rounded border border-zinc-300 px-2 py-1 text-xs dark:border-zinc-600 dark:bg-zinc-800"
                  placeholder="详细描述"
                />
                <div className="flex items-center gap-2">
                  <label className="text-[10px] text-zinc-500">依赖:</label>
                  <input
                    value={task.deps.map((d) => d + 1).join(",")}
                    onChange={(e) => {
                      const deps = e.target.value
                        .split(",")
                        .map((s) => parseInt(s.trim()) - 1)
                        .filter((n) => !isNaN(n) && n >= 0 && n < blueprint.tasks.length && n !== i);
                      updateTask(i, { deps });
                    }}
                    className="flex-1 rounded border border-zinc-300 px-1.5 py-0.5 text-[10px] dark:border-zinc-600 dark:bg-zinc-800"
                    placeholder="如: 1,2"
                  />
                </div>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => setEditingIndex(null)}
                    className="rounded bg-blue-500 px-2 py-0.5 text-[10px] text-white"
                  >
                    完成
                  </button>
                  <button
                    onClick={() => removeTask(i)}
                    className="rounded border border-red-300 px-2 py-0.5 text-[10px] text-red-500"
                  >
                    删除
                  </button>
                </div>
              </div>
            ) : (
              /* View mode */
              <div
                className="cursor-pointer"
                onClick={() => setEditingIndex(i)}
              >
                <div className="flex items-center gap-1.5">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-100 text-[10px] font-bold text-blue-600 dark:bg-blue-900 dark:text-blue-300">
                    {i + 1}
                  </span>
                  <span className="text-xs font-medium">{task.title}</span>
                  {task.kind === "final_qa" && (
                    <span className="rounded bg-orange-100 px-1 text-[10px] text-orange-600 dark:bg-orange-900 dark:text-orange-300">
                      QA
                    </span>
                  )}
                </div>
                {task.detail && (
                  <p className="mt-1 text-[11px] text-zinc-500 line-clamp-2">
                    {task.detail}
                  </p>
                )}
                {task.deps.length > 0 && (
                  <p className="mt-1 text-[10px] text-zinc-400">
                    依赖: {task.deps.map((d) => `#${d + 1}`).join(", ")}
                  </p>
                )}
              </div>
            )}
          </div>
        ))}

        <button
          onClick={addTask}
          className="mb-2 w-full rounded border border-dashed border-zinc-300 py-1.5 text-xs text-zinc-400 transition-colors hover:border-blue-400 hover:text-blue-500 dark:border-zinc-600"
        >
          + 添加任务
        </button>
      </div>

      {/* Finalize */}
      <button
        onClick={onFinalize}
        disabled={finalizing || blueprint.tasks.length === 0}
        className="mt-2 w-full rounded bg-green-500 py-2 text-xs font-semibold text-white transition-colors hover:bg-green-600 disabled:opacity-50"
      >
        {finalizing ? "生成中..." : "确认 → 生成项目卡"}
      </button>
    </div>
  );
}

export default TaskBlueprintEditor;
